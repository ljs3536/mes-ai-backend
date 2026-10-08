"""설비 MQTT 메시지 처리. 3단계에서 IoT-Ingestion 서비스로 분리할 경계."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .domain import LotStatus, Location, MachineStatus, WorkOrderStatus
from .models import Machine, SensorReading, TraceEvent, WorkOrder
from .services import DomainError, active_work_order


def machine_by_code(db: Session, code: str) -> Machine | None:
    return db.scalar(select(Machine).where(Machine.code == code))


def desired_job(db: Session, machine: Machine) -> dict | None:
    """설비가 지금 수행해야 할 작업. 게이트웨이는 이 값에 PLC를 맞춘다."""
    wo = active_work_order(db, machine.id)
    if wo is None or machine.status != MachineStatus.RUN:
        return None
    return {
        "workOrderId": wo.id,
        "woNo": wo.wo_no,
        "productName": wo.product_name,
        "quantity": wo.quantity,
        "producedQty": wo.produced_qty,
        "lotNo": wo.lot.lot_no,
    }


def _parse_ts(value: str | None) -> datetime:
    now = datetime.now()
    if not value:
        return now
    try:
        ts = datetime.fromisoformat(value).replace(tzinfo=None)
    except ValueError:
        return now
    return min(ts, now)


def record_sensors(db: Session, machine: Machine, payload: dict) -> None:
    values = [v for v in payload.get("values", []) if isinstance(v, dict) and "code" in v and "value" in v]
    if not values:
        return
    ts = _parse_ts(payload.get("ts"))
    wo = active_work_order(db, machine.id) if machine.status == MachineStatus.RUN else None
    machine.last_telemetry = [
        {"code": str(v["code"]), "value": float(v["value"]), "unit": str(v.get("unit", ""))} for v in values
    ]
    db.add_all(
        SensorReading(
            machine_id=machine.id,
            work_order_id=wo.id if wo else None,
            sensor_code=v["code"],
            value=v["value"],
            unit=v["unit"],
            recorded_at=ts,
        )
        for v in machine.last_telemetry
    )
    db.commit()


def record_state(db: Session, machine: Machine, payload: dict) -> bool:
    """PLC 상태 반영. 진행수량이 늘었으면 True."""
    if not payload.get("plcOnline"):
        return False
    machine.last_seen_at = _parse_ts(payload.get("ts"))
    wo = active_work_order(db, machine.id)
    produced = payload.get("producedQty")
    advanced = False
    if wo and payload.get("workOrderId") == wo.id and isinstance(produced, int):
        new_qty = min(max(wo.produced_qty, produced), wo.quantity)
        advanced = new_qty > wo.produced_qty
        wo.produced_qty = new_qty
    db.commit()
    return advanced


def complete_job(db: Session, machine: Machine, work_order_id: int, produced_qty: int) -> WorkOrder:
    wo = db.get(WorkOrder, work_order_id)
    if wo is None or wo.machine_id != machine.id:
        raise DomainError("이 설비에 할당된 작업지시가 아닙니다.", 404)
    if wo.status == WorkOrderStatus.COMPLETED:
        return wo
    if wo.status != WorkOrderStatus.IN_PROGRESS:
        raise DomainError(f"진행 중인 작업이 아닙니다 ({wo.status}).", 409)

    wo.produced_qty = min(produced_qty, wo.quantity)
    wo.status = WorkOrderStatus.COMPLETED
    wo.completed_at = datetime.now()
    wo.lot.status = LotStatus.PROCESSED
    wo.lot.location = Location.INSPECTION_WAIT
    machine.status = MachineStatus.IDLE
    db.add(
        TraceEvent(
            lot_id=wo.lot_id,
            type="COMPLETE",
            message=f"{machine.name} 가공 완료 {wo.produced_qty}/{wo.quantity}ea · 품질검사 대기",
        )
    )
    db.commit()
    return wo
