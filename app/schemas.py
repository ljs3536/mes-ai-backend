from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class Schema(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)


class OperatorOut(Schema):
    id: int
    employee_no: str
    name: str
    role: str


class MachineOut(Schema):
    id: int
    code: str
    name: str
    type: str
    status: str


class AlertOut(Schema):
    id: int
    machine_id: int | None
    severity: str
    title: str
    message: str
    created_at: datetime


class LotOut(Schema):
    id: int
    lot_no: str
    material_name: str
    quantity: int
    status: str
    location: str
    created_at: datetime
    updated_at: datetime


class InspectionOut(Schema):
    id: int
    result: str
    note: str | None
    created_at: datetime


class ShipmentOut(Schema):
    id: int
    ship_no: str
    quantity: int
    created_at: datetime


class TraceEventOut(Schema):
    id: int
    type: str
    message: str
    created_at: datetime


class WorkOrderOut(Schema):
    id: int
    wo_no: str
    product_name: str
    quantity: int
    status: str
    started_at: datetime | None
    created_at: datetime
    machine: MachineOut
    lot: LotOut
    operator: OperatorOut | None


class LotSummaryOut(LotOut):
    latest_inspection: InspectionOut | None = None
    latest_shipment: ShipmentOut | None = None


class LotTraceOut(LotOut):
    work_orders: list[WorkOrderOut]
    inspections: list[InspectionOut]
    shipments: list[ShipmentOut]
    events: list[TraceEventOut]


class MachineDetailOut(MachineOut):
    active_work_order: WorkOrderOut | None
    open_alerts: list[AlertOut]


class DashboardCounts(Schema):
    raw: int
    wip: int
    hold: int
    stock: int
    shipped: int
    running: int


class DashboardOut(Schema):
    counts: DashboardCounts
    machines: list[MachineOut]
    alerts: list[AlertOut]
    recent_lots: list[LotOut]


class ReceiveMaterialIn(Schema):
    material_name: str = Field(min_length=1, max_length=128)
    quantity: int = Field(gt=0)


class WorkOrderCreateIn(Schema):
    lot_id: int
    machine_id: int
    product_name: str = Field(min_length=1, max_length=128)
    quantity: int = Field(gt=0)


class StartWorkIn(Schema):
    operator_id: int


class InspectionIn(Schema):
    result: Literal["PASS", "FAIL"]
    note: str | None = Field(default=None, max_length=255)
