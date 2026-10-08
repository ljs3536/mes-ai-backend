"""데모 시나리오 데이터. 운영자 테이블이 비어 있을 때만 들어간다."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from .domain import InspectionResult, LotStatus, Location, MachineStatus, WorkOrderStatus
from .models import Alert, Inspection, Lot, Machine, MachineSensor, Operator, Shipment, TraceEvent, WorkOrder


def seed_if_empty(db: Session) -> bool:
    if db.scalar(select(Operator.id).limit(1)) is not None:
        return False

    db.add_all(
        [
            Operator(employee_no="ADMIN-001", name="김관리", role="ADMIN"),
            Operator(employee_no="OP-001", name="이민준", role="OPERATOR"),
            Operator(employee_no="OP-002", name="박서연", role="OPERATOR"),
        ]
    )
    machine_a = Machine(code="MACHINE_A", name="Machine A", type="CNC", status=MachineStatus.IDLE)
    machine_b = Machine(code="MACHINE_B", name="Machine B", type="CNC", status=MachineStatus.IDLE)
    db.add_all([machine_a, machine_b])

    def lot(lot_no, name, qty, status, location, events):
        row = Lot(lot_no=lot_no, material_name=name, quantity=qty, status=status, location=location)
        row.events = [TraceEvent(type=t, message=m) for t, m in events]
        db.add(row)
        return row

    raw = lot(
        "RAW-20260728-001", "특수 강재", 200, LotStatus.RAW, Location.RAW_WAREHOUSE,
        [
            ("RECEIVE", "특수 강재 200ea 입고, LOT RAW-20260728-001 발행"),
            ("WORK_ORDER", "작업지시 WO-20260728-001 발행: Machine A에서 A-제품 100ea"),
        ],
    )
    hold = lot(
        "RAW-20261001-014", "정밀 배관", 40, LotStatus.HOLD, Location.QUALITY_HOLD,
        [
            ("RECEIVE", "정밀 배관 40ea 입고"),
            ("START", "Machine B 가공 시작"),
            ("HOLD", "치수 편차로 검사대기(HOLD)"),
        ],
    )
    stock = lot(
        "RAW-20260918-007", "센서 하우징", 50, LotStatus.IN_STOCK, Location.FINISHED_WAREHOUSE,
        [
            ("RECEIVE", "센서 하우징 원자재 50ea 입고"),
            ("START", "Machine A 가공"),
            ("QUALITY", "품질 합격, 완제품 창고 이동"),
        ],
    )
    shipped = lot(
        "RAW-20260902-003", "고압 밸브", 30, LotStatus.SHIPPED, Location.SHIPPED,
        [
            ("RECEIVE", "고압 밸브 원자재 30ea 입고"),
            ("SHIP", "출하지시 SHP-20260920-001 처리"),
        ],
    )
    db.flush()

    db.add_all(
        [
            WorkOrder(
                wo_no="WO-20260728-001", product_name="A-제품", quantity=100,
                status=WorkOrderStatus.PLANNED, machine_id=machine_a.id, lot_id=raw.id,
            ),
            Inspection(lot_id=hold.id, result=InspectionResult.PENDING, note="외관 재검 필요"),
            Inspection(lot_id=stock.id, result=InspectionResult.PASS, note="치수/외관 합격"),
            Shipment(ship_no="SHP-20260920-001", lot_id=shipped.id, quantity=30),
            Alert(
                machine_id=machine_a.id, severity="INFO", title="2단계 연동 예정",
                message="센서 에뮬레이터(진동/온도/RPM)와 AI 이상감지는 2단계에서 Machine A에 연결합니다.",
            ),
        ]
    )
    db.commit()
    return True


SENSOR_DEFAULTS = (
    ("MACHINE_A", "PIEZO_FRONT", "스핀들 전면 베어링", "PIEZO", "스핀들 전면 반경", "g", 2560, 1024, 3600, "normal", 0.2),
    ("MACHINE_A", "PIEZO_REAR", "스핀들 후면 베어링", "PIEZO", "스핀들 후면 반경", "g", 2560, 1024, 3600, "normal", 0.15),
    ("MACHINE_B", "PIEZO_FRONT", "스핀들 전면 베어링", "PIEZO", "스핀들 전면 반경", "g", 2560, 1024, 3600, "bearing_outer", 0.7),
)


def ensure_machine_sensors(db: Session) -> None:
    """설비가 있는데 부착 센서가 없으면 PIEZO 기본 구성을 넣는다. 이미 있으면 건드리지 않는다."""
    machines = {m.code: m for m in db.scalars(select(Machine))}
    existing = {
        (row.machine_id, row.code)
        for row in db.scalars(select(MachineSensor))
    }
    added = False
    for machine_code, code, name, sensor_type, mount, unit, rate, n, interval, preset, severity in SENSOR_DEFAULTS:
        machine = machines.get(machine_code)
        if machine is None or (machine.id, code) in existing:
            continue
        db.add(
            MachineSensor(
                machine_id=machine.id,
                code=code,
                name=name,
                sensor_type=sensor_type,
                mount=mount,
                unit=unit,
                sample_rate=rate,
                n_samples=n,
                interval_s=interval,
                preset=preset,
                severity=severity,
                enabled=True,
            )
        )
        added = True
    if added:
        db.commit()
