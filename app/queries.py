from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from .config import get_settings
from .domain import LotStatus, MachineStatus, WorkOrderStatus
from .models import Alert, Lot, Machine, Operator, SensorReading, WorkOrder
from .schemas import (
    AlertOut,
    DashboardCounts,
    DashboardOut,
    LotOut,
    LotSummaryOut,
    MachineDetailOut,
    MachineOut,
    WorkOrderOut,
)

_wo_load = (selectinload(WorkOrder.machine), selectinload(WorkOrder.lot), selectinload(WorkOrder.operator))


def list_operators(db: Session) -> list[Operator]:
    return list(db.scalars(select(Operator).order_by(Operator.name)))


def list_lots(db: Session, statuses: list[str] | None = None) -> list[LotSummaryOut]:
    stmt = (
        select(Lot)
        .options(selectinload(Lot.inspections), selectinload(Lot.shipments))
        .order_by(Lot.updated_at.desc(), Lot.id.desc())
    )
    if statuses:
        stmt = stmt.where(Lot.status.in_(statuses))
    return [
        LotSummaryOut.model_validate(lot).model_copy(
            update={
                "latest_inspection": lot.inspections[0] if lot.inspections else None,
                "latest_shipment": lot.shipments[0] if lot.shipments else None,
            }
        )
        for lot in db.scalars(stmt)
    ]


def get_trace(db: Session, lot_no: str) -> Lot | None:
    return db.scalar(
        select(Lot)
        .where(Lot.lot_no == lot_no)
        .options(
            selectinload(Lot.work_orders).options(*_wo_load),
            selectinload(Lot.inspections),
            selectinload(Lot.shipments),
            selectinload(Lot.events),
        )
    )


def list_work_orders(db: Session, statuses: list[str] | None = None) -> list[WorkOrder]:
    stmt = select(WorkOrder).options(*_wo_load).order_by(WorkOrder.id.desc())
    if statuses:
        stmt = stmt.where(WorkOrder.status.in_(statuses))
    return list(db.scalars(stmt))


def list_machines(db: Session) -> list[MachineDetailOut]:
    machines = db.scalars(select(Machine).options(selectinload(Machine.alerts)).order_by(Machine.name)).all()
    active = {
        wo.machine_id: wo
        for wo in reversed(list_work_orders(db, [WorkOrderStatus.IN_PROGRESS, WorkOrderStatus.HOLD]))
        if wo.machine.status != MachineStatus.IDLE
    }
    offline_after = timedelta(seconds=get_settings().machine_offline_after_seconds)
    now = datetime.now()
    return [
        MachineDetailOut(
            **MachineOut.model_validate(m).model_dump(),
            active_work_order=WorkOrderOut.model_validate(active[m.id]) if m.id in active else None,
            open_alerts=[AlertOut.model_validate(a) for a in sorted(m.alerts, key=lambda a: -a.id) if not a.acknowledged],
            online=m.last_seen_at is not None and now - m.last_seen_at < offline_after,
            last_seen_at=m.last_seen_at,
            sensors=m.last_telemetry or [],
        )
        for m in machines
    ]


def recent_readings(db: Session, machine_id: int, minutes: int) -> list[SensorReading]:
    since = datetime.now() - timedelta(minutes=minutes)
    return list(
        db.scalars(
            select(SensorReading)
            .where(SensorReading.machine_id == machine_id, SensorReading.recorded_at >= since)
            .order_by(SensorReading.recorded_at, SensorReading.id)
        )
    )


def dashboard(db: Session) -> DashboardOut:
    by_status = dict(db.execute(select(Lot.status, func.count()).group_by(Lot.status)).all())
    machines = db.scalars(select(Machine).order_by(Machine.name)).all()
    alerts = db.scalars(select(Alert).where(Alert.acknowledged.is_(False)).order_by(Alert.id.desc())).all()
    recent = db.scalars(select(Lot).order_by(Lot.updated_at.desc(), Lot.id.desc()).limit(8)).all()
    return DashboardOut(
        counts=DashboardCounts(
            raw=by_status.get(LotStatus.RAW, 0),
            wip=by_status.get(LotStatus.WIP, 0),
            processed=by_status.get(LotStatus.PROCESSED, 0),
            hold=by_status.get(LotStatus.HOLD, 0),
            stock=by_status.get(LotStatus.IN_STOCK, 0),
            shipped=by_status.get(LotStatus.SHIPPED, 0),
            running=sum(m.status == MachineStatus.RUN for m in machines),
        ),
        machines=[MachineOut.model_validate(m) for m in machines],
        alerts=[AlertOut.model_validate(a) for a in alerts],
        recent_lots=[LotOut.model_validate(lot) for lot in recent],
    )
