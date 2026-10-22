import re
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import queries, services
from ..auth import OPERATOR, require_internal, require_role
from ..db import get_db
from ..models import Machine, Operator
from ..mqtt_bridge import bridge
from ..schemas import MachineDetailOut, MachineOut, SensorReadingOut
from ..services import DomainError

# 설비 상태와 텔레메트리. 작업자는 배정된 설비만 보고 정지하고 재개한다. 코드 기준 정지는 내부 토큰이 있는 분석 백엔드만 호출한다.
router = APIRouter(prefix="/machines", tags=["machines"])
Db = Annotated[Session, Depends(get_db)]


def _own_machine(user: Operator, machine_id: int) -> None:
    if user.machine_id != machine_id:
        raise DomainError("배정된 설비만 조작할 수 있습니다.", 403)


@router.get("", response_model=list[MachineDetailOut])
def list_machines(db: Db, user: Annotated[Operator, Depends(require_role("PLANNER", "OPERATOR", "ADMIN"))]):
    rows = queries.list_machines(db)
    if user.role == OPERATOR:
        return [row for row in rows if row.id == user.machine_id]
    return rows


@router.get("/{machine_id}/telemetry", response_model=list[SensorReadingOut])
def telemetry(
    machine_id: int,
    db: Db,
    user: Annotated[Operator, Depends(require_role("OPERATOR", "ADMIN"))],
    minutes: Annotated[int, Query(ge=1, le=60)] = 5,
):
    if user.role == OPERATOR and user.machine_id != machine_id:
        raise DomainError("배정된 설비의 측정값만 볼 수 있습니다.", 403)
    return queries.recent_readings(db, machine_id, minutes)


@router.post("/by-code/{code}/hold", response_model=MachineOut)
def hold_by_code(
    code: str,
    db: Db,
    _: Annotated[None, Depends(require_internal)],
    reason: Annotated[str, Query(min_length=1, max_length=200)] = "AI 이상 감지",
):
    """분석 백엔드가 이상 판정 연속 발생 시 내부 토큰으로 호출한다."""
    if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", code) is None:
        raise DomainError("설비 코드가 올바르지 않습니다.", 422)
    machine = db.scalar(select(Machine).where(Machine.code == code))
    if machine is None:
        raise DomainError("설비를 찾을 수 없습니다.", 404)
    machine = services.hold_machine(db, machine.id, reason)
    bridge.publish_job(db, machine)
    return machine


@router.post("/{machine_id}/hold", response_model=MachineOut)
def hold(machine_id: int, db: Db, user: Annotated[Operator, Depends(require_role("OPERATOR"))]):
    _own_machine(user, machine_id)
    machine = services.hold_machine(db, machine_id)
    bridge.publish_job(db, machine)
    return machine


@router.post("/{machine_id}/resume", response_model=MachineOut)
def resume(machine_id: int, db: Db, user: Annotated[Operator, Depends(require_role("OPERATOR"))]):
    _own_machine(user, machine_id)
    machine = services.resume_machine(db, machine_id)
    bridge.publish_job(db, machine)
    return machine
