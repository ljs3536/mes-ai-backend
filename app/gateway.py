"""설비(에뮬레이터) ↔ MES 연동. 3단계에서 IoT-Ingestion 서비스로 분리할 경계."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .domain import LotStatus, Location, MachineStatus, WorkOrderStatus
from .models import Machine, SensorReading, TraceEvent, WorkOrder
from .schemas import HeartbeatIn, HeartbeatOut, JobCompleteIn, JobOut
from .services import DomainError, active_work_order


def _machine(db: Session, code: str) -> Machine:
    machine = db.scalar(select(Machine).where(Machine.code == code))
    if machine is None:
        raise DomainError(f"등록되지 않은 설비 코드입니다: {code}", 404)
    return machine


def _job(wo: WorkOrder) -> JobOut:
    return JobOut(
        work_order_id=wo.id,
        wo_no=wo.wo_no,
        product_name=wo.product_name,
        quantity=wo.quantity,
        produced_qty=wo.produced_qty,
        lot_no=wo.lot.lot_no,
    )


def heartbeat(db: Session, code: str, body: HeartbeatIn) -> HeartbeatOut:
    """센서값/진행수량을 받고, 설비가 지금 수행해야 할 작업을 돌려준다."""
    machine = _machine(db, code)
    now = datetime.now()
    machine.last_seen_at = now
    wo = active_work_order(db, machine.id)

    if body.sensors:
        machine.last_telemetry = [s.model_dump() for s in body.sensors]
        db.add_all(
            SensorReading(
                machine_id=machine.id,
                work_order_id=wo.id if wo else None,
                sensor_code=s.code,
                value=s.value,
                unit=s.unit,
                recorded_at=now,
            )
            for s in body.sensors
        )

    if wo and body.work_order_id == wo.id and body.produced_qty is not None:
        wo.produced_qty = min(max(wo.produced_qty, body.produced_qty), wo.quantity)

    db.commit()
    running = wo is not None and machine.status == MachineStatus.RUN
    return HeartbeatOut(machine_status=machine.status, job=_job(wo) if running else None)


def complete_job(db: Session, code: str, body: JobCompleteIn) -> WorkOrder:
    machine = _machine(db, code)
    wo = db.get(WorkOrder, body.work_order_id)
    if wo is None or wo.machine_id != machine.id:
        raise DomainError("이 설비에 할당된 작업지시가 아닙니다.", 404)
    if wo.status == WorkOrderStatus.COMPLETED:
        return wo
    if wo.status != WorkOrderStatus.IN_PROGRESS:
        raise DomainError(f"진행 중인 작업이 아닙니다 ({wo.status}).", 409)

    wo.produced_qty = min(body.produced_qty, wo.quantity)
    wo.status = WorkOrderStatus.COMPLETED
    wo.completed_at = datetime.now()
    wo.lot.status = LotStatus.PROCESSED
    wo.lot.location = Location.INSPECTION_WAIT
    machine.status = MachineStatus.IDLE
    db.add(
        TraceEvent(
            lot_id=wo.lot_id,
            type="COMPLETE",
            message=f"{machine.name} 가공 완료 {wo.produced_qty}/{wo.quantity}ea · 품질검사 대기",
        )
    )
    db.commit()
    return wo
