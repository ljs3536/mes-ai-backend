from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from .. import queries, services
from ..auth import require_role
from ..db import get_db
from ..models import Operator, WorkOrder
from ..mqtt_bridge import bridge
from ..schemas import CancelWorkOrderIn, WorkOrderCreateIn, WorkOrderOut
from ..services import DomainError

# 생산관리가 작업지시를 만들고 시작 전에 취소한다. 시작은 그 설비에 배정된 작업자가 한다.
router = APIRouter(prefix="/work-orders", tags=["work-orders"])
Db = Annotated[Session, Depends(get_db)]


@router.get("", response_model=list[WorkOrderOut])
def list_work_orders(
    db: Db,
    _: Annotated[Operator, Depends(require_role("PLANNER", "OPERATOR"))],
    status_: Annotated[list[str] | None, Query(alias="status")] = None,
):
    return queries.list_work_orders(db, status_)


@router.post("", response_model=WorkOrderOut, status_code=status.HTTP_201_CREATED)
def create_work_order(body: WorkOrderCreateIn, db: Db, _: Annotated[Operator, Depends(require_role("PLANNER"))]):
    return services.create_work_order(db, body)


@router.post("/{work_order_id}/start", response_model=WorkOrderOut)
def start_work(work_order_id: int, db: Db, user: Annotated[Operator, Depends(require_role("OPERATOR"))]):
    wo = db.get(WorkOrder, work_order_id)
    if wo is None:
        raise DomainError("작업지시를 찾을 수 없습니다.", 404)
    if user.machine_id != wo.machine_id:
        raise DomainError("배정된 설비의 작업만 시작할 수 있습니다.")
    wo = services.start_work(db, work_order_id, user.id)
    bridge.sync_machine(db, wo.machine_id)
    return wo


@router.post("/{work_order_id}/cancel", response_model=WorkOrderOut)
def cancel_work_order(
    work_order_id: int,
    body: CancelWorkOrderIn,
    db: Db,
    _: Annotated[Operator, Depends(require_role("PLANNER"))],
):
    return services.cancel_work_order(db, work_order_id, body.reason)
