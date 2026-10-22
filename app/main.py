"""MES 핵심 API.

현재 기능:
- 사원 로그인. 관리자가 직무를 정하고, 작업자는 담당 설비에 연결한다
- 대시보드와 사원 목록은 관리자, 입고와 출하는 자재, 작업지시 발행은 생산관리
- 작업 시작과 설비 정지·재개는 배정된 작업자. 관리자는 품목별 검사 기준을 두고, 품질은 실측값이 공차 밖인 수량을 재가공 또는 폐기한다
- 자재 LOT 입고와 LOT 이력
- 설비 상태와 텔레메트리. 작업자는 배정된 설비만 보고, 정지는 가공을 멈추고 재개는 같은 작업을 잇는다. 분석 서비스의 설비 보류는 내부 토큰이 있어야 한다
- 설비에 PIEZO 센서를 연결하고 수집 설정을 저장. 목록은 관리자 또는 내부 토큰만 본다
- MQTT로 게이트웨이에 작업을 내리고 설비 상태를 받음. 계정이 있으면 그 계정으로 접속한다
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from .auth import ensure_auth_secret, ensure_operator_auth
from .config import get_settings
from .db import Base, SessionLocal, engine
from .mqtt_bridge import bridge
from .routers import auth, inspection_specs, lots, machines, operators, overview, sensors, work_orders
from .seed import (
    ensure_inspection_quantities,
    ensure_inspection_specs,
    ensure_job_roles,
    ensure_machine_sensors,
    ensure_operator_machine_column,
    seed_if_empty,
)
from .services import DomainError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_auth_secret()
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        ensure_operator_machine_column(db)
        ensure_inspection_quantities(db)
        ensure_operator_auth(db)
    if get_settings().seed_demo:
        with SessionLocal() as db:
            seed_if_empty(db)
            ensure_machine_sensors(db)
            ensure_job_roles(db)
            ensure_inspection_specs(db)
    bridge.start()
    yield
    bridge.stop()


app = FastAPI(title="Factory MES Core API", version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(DomainError)
async def domain_error_handler(_: Request, exc: DomainError):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})


@app.get("/healthz", tags=["health"])
def healthz():
    return {"status": "ok"}


@app.get("/readyz", tags=["health"])
def readyz():
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ready", "mqtt": bool(bridge.client and bridge.client.is_connected())}


for router in (
    auth.router,
    operators.router,
    overview.router,
    lots.router,
    work_orders.router,
    machines.router,
    sensors.router,
    inspection_specs.router,
):
    app.include_router(router, prefix="/api")
