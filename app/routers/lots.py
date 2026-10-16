from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from .. import queries, services
from ..auth import require_admin, require_user
from ..db import get_db
from ..models import Operator
from ..mqtt_bridge import bridge
from ..schemas import InspectionIn, LotOut, LotSummaryOut, LotTraceOut, ReceiveMaterialIn, ShipmentOut

# 자재 LOT 입고, 품질 판정, 출하, LOT 이력 조회.
router = APIRouter(prefix="/lots", tags=["lots"])
Db = Annotated[Session, Depends(get_db)]
User = Annotated[Operator, Depends(require_user)]
Admin = Annotated[Operator, Depends(require_admin)]


@router.get("", response_model=list[LotSummaryOut])
def list_lots(db: Db, _: User, status_: Annotated[list[str] | None, Query(alias="status")] = None):
    return queries.list_lots(db, status_)


@router.post("", response_model=LotOut, status_code=status.HTTP_201_CREATED)
def receive_material(body: ReceiveMaterialIn, db: Db, _: User):
    return services.receive_material(db, body)


@router.get("/{lot_no}/trace", response_model=LotTraceOut)
def trace(lot_no: str, db: Db, _: Admin):
    lot = queries.get_trace(db, lot_no)
    if lot is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "해당 LOT를 찾을 수 없습니다.")
    return lot


@router.post("/{lot_id}/inspections", response_model=LotOut)
def inspect(lot_id: int, body: InspectionIn, db: Db, _: User):
    lot = services.inspect_lot(db, lot_id, body)
    bridge.sync_all(db)
    return lot


@router.post("/{lot_id}/ship", response_model=ShipmentOut, status_code=status.HTTP_201_CREATED)
def ship(lot_id: int, db: Db, _: User):
    return services.ship_lot(db, lot_id)
