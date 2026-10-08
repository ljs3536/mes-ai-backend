# MES AI Backend

부품/설비 가공 공장 MES Core API (FastAPI + SQLAlchemy 2 + MariaDB).

시나리오: 자재 입고(LOT 발행) → 작업지시 → 작업 시작(WIP) → 설비 가공/진행 보고 → 가공 완료(PROCESSED) → 품질 판정 → 출하 → 이력 추적.
AI 이상감지는 `services.hold_machine()`을 호출한다. 상태 전이의 개선 기준과 사용자 실행 단계는 [README.txt](README.txt)에 있다.

## 구조

```
app/
  main.py        # 앱, 헬스체크(/healthz, /readyz), 라우터 등록
  config.py      # 환경변수 설정 (DATABASE_URL, CORS_ORIGINS, SEED_DEMO, MQTT_*)
  mqtt_bridge.py # MQTT 구독/발행 (IoT-Ingestion으로 분리할 경계)
  gateway.py     # 센서/PLC 상태 저장, 완료 처리
  models.py      # SQLAlchemy 모델
  schemas.py     # Pydantic 스키마 (응답은 camelCase)
  services.py    # 상태 전이 트랜잭션 로직
  queries.py     # 조회 로직
  routers/       # /api/lots, /api/work-orders, /api/machines, /api/dashboard ...
  seed.py        # 데모 데이터 (빈 DB일 때만)
```

API 문서: 실행 후 `http://localhost:8000/docs`

## 설비 연동 (MQTT)

PLC는 [mes-ai-edge-gateway](https://github.com/ljs3536/mes-ai-edge-gateway)가 Modbus TCP로 제어하고,
센서는 [mes-ai-machine-emulator](https://github.com/ljs3536/mes-ai-machine-emulator)가 MQTT로 직접 발행합니다.
백엔드는 공유 구독(`$share/mes-backend/...`)을 써서 레플리카를 늘려도 메시지를 한 번만 처리합니다.

| 토픽 | 방향 | QoS | 내용 |
| --- | --- | --- | --- |
| `mes/machines/{code}/sensors` | 센서 → MES | 0 | `{"ts", "values": [{"code","value","unit"}]}` → `sensor_readings` 저장 |
| `mes/machines/{code}/state` | 게이트웨이 → MES | 0 | `{"plcOnline","state","workOrderId","producedQty",...}` → 진행수량·온라인 갱신 |
| `mes/machines/{code}/events` | 게이트웨이 → MES | 1 | `{"type":"job_completed","workOrderId","producedQty"}` → 작업지시 `COMPLETED`, LOT `PROCESSED` |
| `mes/machines/{code}/job` | MES → 게이트웨이 | 1, retained | `{"job": {workOrderId, woNo, quantity, producedQty, ...} \| null}` 목표 작업 |

- 작업 시작/정지/재개/품질판정 시 `job`을 다시 발행하고, 진행 중에는 `producedQty`를 5초마다 갱신합니다
  (PLC가 재시작돼도 게이트웨이가 이어서 가공하도록).
- 센서값은 `sensor_code/value/unit` 형태로 저장되므로 센서를 추가해도 스키마 변경이 없습니다.
- PLC 상태가 `MACHINE_OFFLINE_AFTER_SECONDS`(기본 10초) 동안 오지 않으면 화면에 오프라인으로 표시됩니다.
- 최근 센서 원시값(차트/AI 분석용): `GET /api/machines/{id}/telemetry?minutes=5`

## 로컬 실행

```bash
docker run -d --name mes-db -p 3306:3306 \
  -e MARIADB_DATABASE=mes -e MARIADB_USER=mes -e MARIADB_PASSWORD=mes -e MARIADB_ROOT_PASSWORD=root \
  mariadb:11.4
docker run -d --name mes-mqtt -p 1883:1883 eclipse-mosquitto:2 mosquitto -c /mosquitto-no-auth.conf
python -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env
.venv/bin/uvicorn app.main:app --reload
```

## 컨테이너

```bash
docker build -t factory-mes/backend .
docker run -p 8000:8000 -e DATABASE_URL=mysql+pymysql://mes:mes@<db>:3306/mes?charset=utf8mb4 factory-mes/backend
```

테이블은 기동 시 `create_all`로 생성합니다. Kubernetes 다중 레플리카로 갈 때 Alembic 마이그레이션(Job)으로 전환할 예정입니다.
