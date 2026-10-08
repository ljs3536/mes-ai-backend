from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import queries, services
from ..db import get_db
from ..models import Machine
from ..mqtt_bridge import bridge
from ..schemas import MachineDetailOut, MachineOut, SensorReadingOut
from ..services import DomainError

# 설비 상태와 텔레메트리. 보류는 진행 중 작업을 멈추고, 코드 기준 보류는 분석 백엔드가 호출한다.
router = APIRouter(prefix="/machines", tags=["machines"])
Db = Annotated[Session, Depends(get_db)]


@router.get("", response_model=list[MachineDetailOut])
def list_machines(db: Db):
    return queries.list_machines(db)


@router.get("/{machine_id}/telemetry", response_model=list[SensorReadingOut])
def telemetry(machine_id: int, db: Db, minutes: Annotated[int, Query(ge=1, le=60)] = 5):
    return queries.recent_readings(db, machine_id, minutes)


@router.post("/by-code/{code}/hold", response_model=MachineOut)
def hold_by_code(code: str, db: Db, reason: Annotated[str, Query(min_length=1, max_length=200)] = "AI 이상 감지"):
    """분석 백엔드가 이상 판정 연속 발생 시 호출한다."""
    machine = db.scalar(select(Machine).where(Machine.code == code))
    if machine is None:
        raise DomainError("설비를 찾을 수 없습니다.", 404)
    machine = services.hold_machine(db, machine.id, reason)
    bridge.publish_job(db, machine)
    return machine


@router.post("/{machine_id}/hold", response_model=MachineOut)
def hold(machine_id: int, db: Db):
    machine = services.hold_machine(db, machine_id)
    bridge.publish_job(db, machine)
    return machine


@router.post("/{machine_id}/resume", response_model=MachineOut)
def resume(machine_id: int, db: Db):
    machine = services.resume_machine(db, machine_id)
    bridge.publish_job(db, machine)
    return machine
