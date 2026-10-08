"""MES ↔ MQTT 브로커 연동.

구독 (공유 구독이라 backend 레플리카가 여러 개여도 메시지는 한 곳에서만 처리된다)
- mes/machines/+/sensors  부착 센서 값
- mes/machines/+/state    게이트웨이가 읽은 PLC 상태
- mes/machines/+/events   job_completed 등
발행
- mes/machines/{code}/job (retained) 설비별 목표 작업. 게이트웨이가 PLC를 이 값에 맞춘다.
"""

import json
import logging
import socket
import threading
import time

import paho.mqtt.client as mqtt
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import gateway
from .config import get_settings
from .db import SessionLocal
from .models import Machine
from .services import DomainError

log = logging.getLogger("mes.mqtt")
SHARE_GROUP = "mes-backend"
JOB_PROGRESS_REFRESH_SECONDS = 5.0


class MqttBridge:
    def __init__(self) -> None:
        self.client: mqtt.Client | None = None
        self.prefix = get_settings().mqtt_topic_prefix
        self._lock = threading.Lock()
        self._job_published_at: dict[str, float] = {}

    def start(self) -> None:
        s = get_settings()
        if not s.mqtt_enabled:
            log.info("MQTT 비활성화")
            return
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"mes-backend-{socket.gethostname()}")
        client.on_connect = self._on_connect
        client.on_disconnect = lambda *_: log.warning("MQTT 연결 끊김, 재연결 대기")
        client.on_message = self._on_message
        client.reconnect_delay_set(1, 30)
        client.connect_async(s.mqtt_host, s.mqtt_port, keepalive=30)
        client.loop_start()
        self.client = client

    def stop(self) -> None:
        if self.client:
            self.client.loop_stop()
            self.client.disconnect()

    def _on_connect(self, client, _userdata, _flags, reason_code, _props):
        if reason_code.is_failure:
            log.error("MQTT 연결 거부: %s", reason_code)
            return
        client.subscribe(
            [(f"$share/{SHARE_GROUP}/{self.prefix}/machines/+/{kind}", 1) for kind in ("sensors", "state", "events")]
        )
        log.info("MQTT 연결됨, 설비 토픽 구독")
        with SessionLocal() as db:
            self.sync_all(db)

    def _on_message(self, _client, _userdata, msg):
        parts = msg.topic.split("/")
        if len(parts) < 4:
            return
        code, kind = parts[-2], parts[-1]
        try:
            payload = json.loads(msg.payload)
        except ValueError:
            log.warning("JSON 아님 %s", msg.topic)
            return
        try:
            with SessionLocal() as db:
                machine = gateway.machine_by_code(db, code)
                if machine is None:
                    log.warning("미등록 설비 %s", code)
                    return
                if kind == "sensors":
                    gateway.record_sensors(db, machine, payload)
                elif kind == "state":
                    if gateway.record_state(db, machine, payload):
                        self._refresh_job_progress(db, machine)
                elif kind == "events":
                    self._handle_event(db, machine, payload)
        except Exception:
            log.exception("MQTT 메시지 처리 실패 %s", msg.topic)

    def _handle_event(self, db: Session, machine: Machine, event: dict) -> None:
        if event.get("type") != "job_completed":
            log.info("%s 이벤트 무시: %s", machine.code, event.get("type"))
            return
        try:
            wo = gateway.complete_job(db, machine, int(event["workOrderId"]), int(event["producedQty"]))
            log.info("%s 작업 완료 %s %d/%d", machine.code, wo.wo_no, wo.produced_qty, wo.quantity)
        except DomainError as e:
            log.warning("%s 완료 보고 거부: %s", machine.code, e.message)
        self.publish_job(db, machine)

    def publish_job(self, db: Session, machine: Machine) -> None:
        if self.client is None:
            return
        job = gateway.desired_job(db, machine)
        with self._lock:
            self.client.publish(
                f"{self.prefix}/machines/{machine.code}/job", json.dumps({"job": job}), qos=1, retain=True
            )
            self._job_published_at[machine.code] = time.monotonic()

    def _refresh_job_progress(self, db: Session, machine: Machine) -> None:
        """retained 목표 작업의 producedQty를 주기적으로 갱신해 PLC 재시작 시 이어서 가공하게 한다."""
        if time.monotonic() - self._job_published_at.get(machine.code, 0.0) >= JOB_PROGRESS_REFRESH_SECONDS:
            self.publish_job(db, machine)

    def sync_machine(self, db: Session, machine_id: int) -> None:
        machine = db.get(Machine, machine_id)
        if machine is not None:
            self.publish_job(db, machine)

    def sync_all(self, db: Session) -> None:
        for machine in db.scalars(select(Machine)):
            self.publish_job(db, machine)


bridge = MqttBridge()
