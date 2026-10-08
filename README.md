# MES AI Backend

부품/설비 가공 공장 MES Core API (FastAPI + SQLAlchemy 2 + MariaDB).

시나리오: 자재 입고(LOT 발행) → 작업지시 → 작업 시작(WIP) → 설비 가공/진행 보고 → 가공 완료(PROCESSED) → 품질 판정 → 출하 → 이력 추적.
2단계 AI 이상감지는 `services.hold_machine()`을 호출해 설비 STOP + LOT HOLD를 재사용하도록 설계했습니다.

## 구조

```
app/
  main.py        # 앱, 헬스체크(/healthz, /readyz), 라우터 등록
  config.py      # 환경변수 설정 (DATABASE_URL, CORS_ORIGINS, SEED_DEMO, MACHINE_API_KEY)
  gateway.py     # 설비 heartbeat/완료 처리 (IoT-Ingestion으로 분리할 경계)
  models.py      # SQLAlchemy 모델
  schemas.py     # Pydantic 스키마 (응답은 camelCase)
  services.py    # 상태 전이 트랜잭션 로직
  queries.py     # 조회 로직
  routers/       # /api/lots, /api/work-orders, /api/machines, /api/dashboard ...
  seed.py        # 데모 데이터 (빈 DB일 때만)
```

API 문서: 실행 후 `http://localhost:8000/docs`

## 설비 게이트웨이 (에뮬레이터 연동)

[mes-ai-machine-emulator](https://github.com/ljs3536/mes-ai-machine-emulator)가 호출하는 API입니다.
`x-machine-key` 헤더(`MACHINE_API_KEY`)로 인증합니다.

| 메서드 | 경로 | 설명 |
| --- | --- | --- |
| POST | `/api/gateway/machines/{code}/heartbeat` | 센서값 + 진행수량 보고, 응답으로 수행할 job(없으면 `null`) |
| POST | `/api/gateway/machines/{code}/complete` | 가공 완료 → 작업지시 `COMPLETED`, LOT `PROCESSED`, 설비 `IDLE` |
| GET | `/api/machines/{id}/telemetry?minutes=5` | 최근 센서 원시값 (차트/AI 분석용) |

센서값은 `sensor_readings` 테이블에 `sensor_code/value/unit` 형태로 저장되므로 센서를 추가해도 스키마 변경이 없습니다.
설비가 `MACHINE_OFFLINE_AFTER_SECONDS`(기본 10초) 동안 보고하지 않으면 화면에 오프라인으로 표시됩니다.

## 로컬 실행

```bash
docker run -d --name mes-db -p 3306:3306 \
  -e MARIADB_DATABASE=mes -e MARIADB_USER=mes -e MARIADB_PASSWORD=mes -e MARIADB_ROOT_PASSWORD=root \
  mariadb:11.4
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
