"""MES 트랜잭션 로직. 라우터는 입출력만 담당하고 상태 전이는 여기서 처리한다."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .domain import InspectionResult, LotStatus, Location, MachineStatus, WorkOrderStatus
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
    if data.quantity > lot.quantity:
        raise DomainError("지시 수량이 LOT 재고보다 많습니다.")

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
        raise DomainError("대기(PLANNED) 상태 작업지시만 취소할 수 있습니다. 진행 중이면 설비를 먼저 정지하세요.")

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

    wo.status = WorkOrderStatus.IN_PROGRESS
    wo.operator_id = operator.id
    wo.started_at = datetime.now()
    wo.lot.status = LotStatus.WIP
    wo.lot.location = wo.machine.name
    wo.machine.status = MachineStatus.RUN
    _trace(db, wo.lot, "START", f"{operator.name}, {wo.machine.name}에서 작업 시작 · LOT {wo.lot.lot_no} WIP 전환")
    db.commit()
    return wo


def hold_machine(db: Session, machine_id: int, reason: str = "수동 정지") -> Machine:
    """설비 STOP + 진행 LOT HOLD + 알림. 2단계 AI 이상감지도 이 함수를 호출한다."""
    machine = _get(db, Machine, machine_id, "설비")
    wo = active_work_order(db, machine_id)
    if wo is None:
        raise DomainError("가동 중인 작업이 없습니다.")

    machine.status = MachineStatus.STOP
    wo.status = WorkOrderStatus.HOLD
    wo.lot.status = LotStatus.HOLD
    wo.lot.location = Location.QUALITY_HOLD
    db.add(
        Alert(
            machine_id=machine.id,
            severity="CRITICAL",
            title=f"{machine.name} {reason}",
            message=f"작업 LOT {wo.lot.lot_no}를 검사대기(HOLD)로 전환했습니다.",
        )
    )
    _trace(db, wo.lot, "HOLD", f"{machine.name} {reason} · LOT {wo.lot.lot_no} HOLD")
    db.commit()
    return machine


def resume_machine(db: Session, machine_id: int) -> Machine:
    machine = _get(db, Machine, machine_id, "설비")
    if machine.status != MachineStatus.STOP:
        raise DomainError("정지(STOP) 상태 설비만 점검 완료 처리할 수 있습니다.")

    machine.status = MachineStatus.IDLE
    for alert in machine.alerts:
        alert.acknowledged = True
    db.commit()
    return machine


def inspect_lot(db: Session, lot_id: int, data: InspectionIn) -> Lot:
    lot = _get(db, Lot, lot_id, "LOT")
    if lot.status not in (LotStatus.WIP, LotStatus.PROCESSED, LotStatus.HOLD):
        raise DomainError("가공중/가공완료/검사대기 LOT만 품질 판정할 수 있습니다.")

    passed = data.result == InspectionResult.PASS
    db.add(Inspection(lot_id=lot.id, result=data.result, note=(data.note or "").strip() or None))
    lot.status = LotStatus.IN_STOCK if passed else LotStatus.HOLD
    lot.location = Location.FINISHED_WAREHOUSE if passed else Location.QUALITY_HOLD

    for wo in lot.work_orders:
        if wo.status not in (WorkOrderStatus.IN_PROGRESS, WorkOrderStatus.HOLD):
            continue
        wo.status = WorkOrderStatus.COMPLETED if passed else WorkOrderStatus.HOLD
        if passed:
            wo.machine.status = MachineStatus.IDLE
            for alert in wo.machine.alerts:
                alert.acknowledged = True
        else:
            wo.machine.status = MachineStatus.STOP

    _trace(
        db,
        lot,
        "QUALITY",
        "품질 합격, 완제품 창고 이동" if passed else "품질 불합격/보류, 검사대기(HOLD) 유지",
    )
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
    _trace(db, lot, "SHIP", f"출하지시 {shipment.ship_no} 처리, 이력 저장 완료")
    db.commit()
    return shipment
