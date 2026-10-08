from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from .. import queries, services
from ..db import get_db
from ..mqtt_bridge import bridge
from ..schemas import InspectionIn, LotOut, LotSummaryOut, LotTraceOut, ReceiveMaterialIn, ShipmentOut

# 자재 LOT 입고, 품질 판정, 출하, LOT 이력 조회.
router = APIRouter(prefix="/lots", tags=["lots"])
Db = Annotated[Session, Depends(get_db)]


@router.get("", response_model=list[LotSummaryOut])
def list_lots(db: Db, status_: Annotated[list[str] | None, Query(alias="status")] = None):
    return queries.list_lots(db, status_)


@router.post("", response_model=LotOut, status_code=status.HTTP_201_CREATED)
def receive_material(body: ReceiveMaterialIn, db: Db):
    return services.receive_material(db, body)


@router.get("/{lot_no}/trace", response_model=LotTraceOut)
def trace(lot_no: str, db: Db):
    lot = queries.get_trace(db, lot_no)
    if lot is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "해당 LOT를 찾을 수 없습니다.")
    return lot


@router.post("/{lot_id}/inspections", response_model=LotOut)
def inspect(lot_id: int, body: InspectionIn, db: Db):
    lot = services.inspect_lot(db, lot_id, body)
    bridge.sync_all(db)
    return lot


@router.post("/{lot_id}/ship", response_model=ShipmentOut, status_code=status.HTTP_201_CREATED)
def ship(lot_id: int, db: Db):
    return services.ship_lot(db, lot_id)
