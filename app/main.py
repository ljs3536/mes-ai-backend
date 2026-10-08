import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from .config import get_settings
from .db import Base, SessionLocal, engine
from .mqtt_bridge import bridge
from .routers import lots, machines, overview, work_orders
from .seed import seed_if_empty
from .services import DomainError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)
    if get_settings().seed_demo:
        with SessionLocal() as db:
            seed_if_empty(db)
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


for router in (overview.router, lots.router, work_orders.router, machines.router):
    app.include_router(router, prefix="/api")
