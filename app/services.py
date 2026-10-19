"""MES 트랜잭션 로직. 라우터는 입출력만 담당하고 상태 전이는 여기서 처리한다.

설비 정지는 가공을 잠시 멈추고, 재개는 같은 작업을 이어서 가공한다.
품질 보류는 가공완료 LOT의 불합격만 해당한다.
작업 시작 때 지시 수량만 가공중으로 가고, 남은 원자재는 새 LOT로 남는다.
"""

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .domain import Disposition, InspectionResult, LotStatus, Location, MachineStatus, WorkOrderStatus
from .models import Alert, Inspection, Lot, Machine, Operator, Shipment, TraceEvent, WorkOrder
from .schemas import InspectionIn, ReceiveMaterialIn, WorkOrderCreateIn
from .serials import next_serial


class DomainError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _get(db: Session, model, id_: int, label: str):
    obj = db.get(model, id_)
    if obj is None:
        raise DomainError(f"{label}을(를) 찾을 수 없습니다.", 404)
    return obj


def _trace(db: Session, lot: Lot, type_: str, message: str) -> None:
    db.add(TraceEvent(lot_id=lot.id, type=type_, message=message))


def active_work_order(db: Session, machine_id: int) -> WorkOrder | None:
    return db.scalar(
        select(WorkOrder).where(
            WorkOrder.machine_id == machine_id,
            WorkOrder.status == WorkOrderStatus.IN_PROGRESS,
        )
    )


def paused_work_order(db: Session, machine_id: int) -> WorkOrder | None:
    return db.scalar(
        select(WorkOrder).where(
            WorkOrder.machine_id == machine_id,
            WorkOrder.status == WorkOrderStatus.HOLD,
        )
    )


def _planned_quantity(db: Session, lot_id: int) -> int:
    total = db.scalar(
        select(func.coalesce(func.sum(WorkOrder.quantity), 0)).where(
            WorkOrder.lot_id == lot_id,
            WorkOrder.status == WorkOrderStatus.PLANNED,
        )
    )
    return int(total or 0)


def receive_material(db: Session, data: ReceiveMaterialIn) -> Lot:
    lot = Lot(
        lot_no=next_serial(db, Lot.lot_no, "RAW"),
        material_name=data.material_name.strip(),
        quantity=data.quantity,
        status=LotStatus.RAW,
        location=Location.RAW_WAREHOUSE,
    )
    db.add(lot)
    db.flush()
    _trace(db, lot, "RECEIVE", f"{lot.material_name} {lot.quantity}ea 입고, LOT {lot.lot_no} 발행")
    db.commit()
    return lot


def create_work_order(db: Session, data: WorkOrderCreateIn) -> WorkOrder:
    lot = _get(db, Lot, data.lot_id, "LOT")
    machine = _get(db, Machine, data.machine_id, "설비")
    if lot.status != LotStatus.RAW:
        raise DomainError("원자재(RAW) LOT만 작업지시에 연결할 수 있습니다.")
    remaining = lot.quantity - _planned_quantity(db, lot.id)
    if data.quantity > remaining:
        raise DomainError("지시 수량이 남은 원자재보다 많습니다.")

    wo = WorkOrder(
        wo_no=next_serial(db, WorkOrder.wo_no, "WO"),
        product_name=data.product_name.strip(),
        quantity=data.quantity,
        status=WorkOrderStatus.PLANNED,
        machine_id=machine.id,
        lot_id=lot.id,
    )
    db.add(wo)
    _trace(db, lot, "WORK_ORDER", f"작업지시 {wo.wo_no} 발행: {machine.name}에서 {wo.product_name} {wo.quantity}ea")
    db.commit()
    return wo


def cancel_work_order(db: Session, work_order_id: int, reason: str) -> WorkOrder:
    """시작 전 작업지시만 취소한다. 이력 추적을 위해 행은 지우지 않고 번호도 재사용하지 않는다."""
    wo = _get(db, WorkOrder, work_order_id, "작업지시")
    if wo.status != WorkOrderStatus.PLANNED:
        raise DomainError("시작 전(PLANNED) 작업지시만 취소할 수 있습니다.")

    wo.status = WorkOrderStatus.CANCELLED
    _trace(db, wo.lot, "CANCEL", f"작업지시 {wo.wo_no} 취소 · 사유: {reason.strip()}")
    db.commit()
    return wo


def start_work(db: Session, work_order_id: int, operator_id: int) -> WorkOrder:
    wo = _get(db, WorkOrder, work_order_id, "작업지시")
    operator = _get(db, Operator, operator_id, "작업자")
    if wo.status != WorkOrderStatus.PLANNED:
        raise DomainError("대기 중인 작업지시만 시작할 수 있습니다.")
    if wo.machine.status in (MachineStatus.RUN, MachineStatus.STOP):
        raise DomainError(f"{wo.machine.name}이(가) {wo.machine.status} 상태라 시작할 수 없습니다.")
    if wo.lot.status != LotStatus.RAW:
        raise DomainError("LOT가 원자재(RAW) 상태가 아닙니다.")
    if wo.quantity > wo.lot.quantity:
        raise DomainError("지시 수량이 LOT 재고보다 많습니다.")

    lot = wo.lot
    others = list(
        db.scalars(
            select(WorkOrder).where(
                WorkOrder.lot_id == lot.id,
                WorkOrder.status == WorkOrderStatus.PLANNED,
                WorkOrder.id != wo.id,
            )
        )
    )
    remainder = lot.quantity - wo.quantity
    if remainder < sum(other.quantity for other in others):
        raise DomainError("남은 원자재보다 대기 중인 지시가 많습니다.")
    if remainder > 0:
        child = Lot(
            lot_no=next_serial(db, Lot.lot_no, "RAW"),
            material_name=lot.material_name,
            quantity=remainder,
            status=LotStatus.RAW,
            location=Location.RAW_WAREHOUSE,
        )
        db.add(child)
        db.flush()
        for other in others:
            other.lot = child
        _trace(db, lot, "SPLIT", f"{remainder}ea를 {child.lot_no}로 분할하고 {wo.quantity}ea를 가공")
        _trace(db, child, "SPLIT", f"{lot.lot_no}에서 분할된 원자재 {remainder}ea")
        lot.quantity = wo.quantity

    wo.status = WorkOrderStatus.IN_PROGRESS
    wo.operator_id = operator.id
    wo.started_at = datetime.now()
    lot.status = LotStatus.WIP
    lot.location = wo.machine.name
    wo.machine.status = MachineStatus.RUN
    _trace(db, lot, "START", f"{operator.name}, {wo.machine.name}에서 작업 시작 · LOT {lot.lot_no} {lot.quantity}ea WIP")
    db.commit()
    return wo


def hold_machine(db: Session, machine_id: int, reason: str = "수동 정지") -> Machine:
    """설비를 멈추고 작업지시를 일시정지한다. LOT는 가공중을 유지한다. AI 이상감지도 이 함수를 호출한다."""
    machine = _get(db, Machine, machine_id, "설비")
    wo = active_work_order(db, machine_id)
    if wo is None:
        raise DomainError("가동 중인 작업이 없습니다.")

    machine.status = MachineStatus.STOP
    wo.status = WorkOrderStatus.HOLD
    db.add(
        Alert(
            machine_id=machine.id,
            severity="CRITICAL",
            title=f"{machine.name} {reason}",
            message=f"작업지시 {wo.wo_no}를 일시정지했습니다. LOT {wo.lot.lot_no}는 가공중입니다.",
        )
    )
    _trace(db, wo.lot, "STOP", f"{machine.name} {reason} · {wo.wo_no} 일시정지 · LOT {wo.lot.lot_no}는 가공중")
    db.commit()
    return machine


def resume_machine(db: Session, machine_id: int) -> Machine:
    """정지된 설비의 일시정지 작업을 생산 수량 다음부터 다시 가공한다."""
    machine = _get(db, Machine, machine_id, "설비")
    if machine.status != MachineStatus.STOP:
        raise DomainError("정지(STOP) 상태 설비만 재개할 수 있습니다.")
    wo = paused_work_order(db, machine_id)
    if wo is None:
        raise DomainError("일시정지된 작업이 없습니다.")

    machine.status = MachineStatus.RUN
    wo.status = WorkOrderStatus.IN_PROGRESS
    for alert in machine.alerts:
        alert.acknowledged = True
    _trace(db, wo.lot, "RESUME", f"{machine.name} 재개 · {wo.wo_no} {wo.produced_qty}ea 다음부터 가공")
    db.commit()
    return machine


def inspect_lot(db: Session, lot_id: int, data: InspectionIn) -> Lot:
    """가공완료 수량을 합격과 불량으로 나눈다. 불량은 재가공 LOT가 되거나 폐기된다."""
    lot = _get(db, Lot, lot_id, "LOT")
    if lot.status != LotStatus.PROCESSED:
        raise DomainError("가공완료(PROCESSED) LOT만 품질 판정할 수 있습니다.")
    if data.good_qty + data.defect_qty != lot.quantity:
        raise DomainError(f"합격과 불량 수량의 합이 생산 수량 {lot.quantity}ea와 같아야 합니다.")
    if data.defect_qty == 0:
        if data.disposition:
            raise DomainError("불량이 없으면 처리를 고르지 않습니다.")
        result = InspectionResult.PASS
        disposition = None
    else:
        if data.disposition not in (Disposition.REWORK, Disposition.SCRAP):
            raise DomainError("불량 수량이 있으면 재가공 또는 폐기를 고릅니다.")
        result = InspectionResult.FAIL
        disposition = data.disposition

    db.add(
        Inspection(
            lot_id=lot.id,
            result=result,
            good_qty=data.good_qty,
            defect_qty=data.defect_qty,
            disposition=disposition,
            note=(data.note or "").strip() or None,
        )
    )
    if data.defect_qty == 0:
        lot.status = LotStatus.IN_STOCK
        lot.location = Location.FINISHED_WAREHOUSE
        message = f"품질 합격 {data.good_qty}ea"
    elif disposition == Disposition.SCRAP and data.good_qty == 0:
        lot.status = LotStatus.SCRAPPED
        lot.location = Location.SCRAP
        message = f"전량 폐기 {data.defect_qty}ea"
    elif disposition == Disposition.SCRAP:
        lot.quantity = data.good_qty
        lot.status = LotStatus.IN_STOCK
        lot.location = Location.FINISHED_WAREHOUSE
        message = f"합격 {data.good_qty}ea 완제품, 폐기 {data.defect_qty}ea"
    elif data.good_qty == 0:
        lot.status = LotStatus.RAW
        lot.location = Location.REWORK
        message = f"전량 재가공 {data.defect_qty}ea"
    else:
        child = Lot(
            lot_no=next_serial(db, Lot.lot_no, "RAW"),
            material_name=lot.material_name,
            quantity=data.defect_qty,
            status=LotStatus.RAW,
            location=Location.REWORK,
        )
        db.add(child)
        db.flush()
        lot.quantity = data.good_qty
        lot.status = LotStatus.IN_STOCK
        lot.location = Location.FINISHED_WAREHOUSE
        _trace(db, child, "REWORK", f"{lot.lot_no} 검사에서 재가공으로 나뉜 {data.defect_qty}ea")
        message = f"합격 {data.good_qty}ea 완제품, 재가공 {data.defect_qty}ea는 {child.lot_no}"
    _trace(db, lot, "QUALITY", message)
    db.commit()
    return lot


def ship_lot(db: Session, lot_id: int) -> Shipment:
    lot = _get(db, Lot, lot_id, "LOT")
    if lot.status != LotStatus.IN_STOCK:
        raise DomainError("완제품(IN_STOCK) LOT만 출하할 수 있습니다.")

    shipment = Shipment(ship_no=next_serial(db, Shipment.ship_no, "SHP"), lot_id=lot.id, quantity=lot.quantity)
    db.add(shipment)
    lot.status = LotStatus.SHIPPED
    lot.location = Location.SHIPPED
    _trace(db, lot, "SHIP", f"출하 {shipment.ship_no} {shipment.quantity}ea")
    db.commit()
    return shipment
