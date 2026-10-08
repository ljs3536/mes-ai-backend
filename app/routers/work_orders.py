from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from .. import queries, services
from ..db import get_db
from ..mqtt_bridge import bridge
from ..schemas import CancelWorkOrderIn, StartWorkIn, WorkOrderCreateIn, WorkOrderOut

# 작업지시 생성, 작업 시작, 예정 상태 취소. 취소는 삭제 대신 상태와 사유를 남긴다.
router = APIRouter(prefix="/work-orders", tags=["work-orders"])
Db = Annotated[Session, Depends(get_db)]


@router.get("", response_model=list[WorkOrderOut])
def list_work_orders(db: Db, status_: Annotated[list[str] | None, Query(alias="status")] = None):
    return queries.list_work_orders(db, status_)


@router.post("", response_model=WorkOrderOut, status_code=status.HTTP_201_CREATED)
def create_work_order(body: WorkOrderCreateIn, db: Db):
    return services.create_work_order(db, body)


@router.post("/{work_order_id}/start", response_model=WorkOrderOut)
def start_work(work_order_id: int, body: StartWorkIn, db: Db):
    wo = services.start_work(db, work_order_id, body.operator_id)
    bridge.sync_machine(db, wo.machine_id)
    return wo


@router.post("/{work_order_id}/cancel", response_model=WorkOrderOut)
def cancel_work_order(work_order_id: int, body: CancelWorkOrderIn, db: Db):
    return services.cancel_work_order(db, work_order_id, body.reason)
