from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import queries, services
from ..db import get_db
from ..schemas import MachineDetailOut, MachineOut

router = APIRouter(prefix="/machines", tags=["machines"])
Db = Annotated[Session, Depends(get_db)]


@router.get("", response_model=list[MachineDetailOut])
def list_machines(db: Db):
    return queries.list_machines(db)


@router.post("/{machine_id}/hold", response_model=MachineOut)
def hold(machine_id: int, db: Db):
    return services.hold_machine(db, machine_id)


@router.post("/{machine_id}/resume", response_model=MachineOut)
def resume(machine_id: int, db: Db):
    return services.resume_machine(db, machine_id)
