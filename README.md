# MES AI Backend

부품/설비 가공 공장 MES Core API (FastAPI + SQLAlchemy 2 + MariaDB).

시나리오: 자재 입고(LOT 발행) → 작업지시 → 작업 시작(WIP) → 설비 정지/HOLD → 품질 판정 → 출하 → 이력 추적.
2단계 AI 이상감지는 `services.hold_machine()`을 호출해 설비 STOP + LOT HOLD를 재사용하도록 설계했습니다.

## 구조

```
app/
  main.py        # 앱, 헬스체크(/healthz, /readyz), 라우터 등록
  config.py      # 환경변수 설정 (DATABASE_URL, CORS_ORIGINS, SEED_DEMO)
  models.py      # SQLAlchemy 모델
  schemas.py     # Pydantic 스키마 (응답은 camelCase)
  services.py    # 상태 전이 트랜잭션 로직
  queries.py     # 조회 로직
  routers/       # /api/lots, /api/work-orders, /api/machines, /api/dashboard ...
  seed.py        # 데모 데이터 (빈 DB일 때만)
```

API 문서: 실행 후 `http://localhost:8000/docs`

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
