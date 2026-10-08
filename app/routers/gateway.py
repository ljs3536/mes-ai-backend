import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from .. import gateway
from ..config import get_settings
from ..db import get_db
from ..schemas import HeartbeatIn, HeartbeatOut, JobCompleteIn, WorkOrderOut


def require_machine_key(x_machine_key: Annotated[str, Header()] = "") -> None:
    if not secrets.compare_digest(x_machine_key, get_settings().machine_api_key):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "설비 인증 키가 올바르지 않습니다.")


router = APIRouter(
    prefix="/gateway/machines/{code}",
    tags=["machine-gateway"],
    dependencies=[Depends(require_machine_key)],
)
Db = Annotated[Session, Depends(get_db)]


@router.post("/heartbeat", response_model=HeartbeatOut)
def heartbeat(code: str, body: HeartbeatIn, db: Db):
    return gateway.heartbeat(db, code, body)


@router.post("/complete", response_model=WorkOrderOut)
def complete(code: str, body: JobCompleteIn, db: Db):
    return gateway.complete_job(db, code, body)
