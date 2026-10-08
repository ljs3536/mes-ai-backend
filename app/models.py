from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Operator(Base):
    __tablename__ = "operators"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee_no: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(64))
    role: Mapped[str] = mapped_column(String(16))


class Machine(Base):
    __tablename__ = "machines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(64))
    type: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), index=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_telemetry: Mapped[list[dict] | None] = mapped_column(JSON)

    work_orders: Mapped[list["WorkOrder"]] = relationship(back_populates="machine")
    alerts: Mapped[list["Alert"]] = relationship(back_populates="machine")


class Lot(TimestampMixin, Base):
    __tablename__ = "lots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lot_no: Mapped[str] = mapped_column(String(32), unique=True)
    material_name: Mapped[str] = mapped_column(String(128))
    quantity: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), index=True)
    location: Mapped[str] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    work_orders: Mapped[list["WorkOrder"]] = relationship(back_populates="lot")
    inspections: Mapped[list["Inspection"]] = relationship(
        back_populates="lot", order_by="Inspection.id.desc()"
    )
    shipments: Mapped[list["Shipment"]] = relationship(
        back_populates="lot", order_by="Shipment.id.desc()"
    )
    events: Mapped[list["TraceEvent"]] = relationship(
        back_populates="lot", order_by="TraceEvent.id"
    )


class WorkOrder(TimestampMixin, Base):
    __tablename__ = "work_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    wo_no: Mapped[str] = mapped_column(String(32), unique=True)
    product_name: Mapped[str] = mapped_column(String(128))
    quantity: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), index=True)
    machine_id: Mapped[int] = mapped_column(ForeignKey("machines.id"))
    lot_id: Mapped[int] = mapped_column(ForeignKey("lots.id"))
    operator_id: Mapped[int | None] = mapped_column(ForeignKey("operators.id"))
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    produced_qty: Mapped[int] = mapped_column(Integer, default=0)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)

    machine: Mapped[Machine] = relationship(back_populates="work_orders")
    lot: Mapped[Lot] = relationship(back_populates="work_orders")
    operator: Mapped[Operator | None] = relationship()


class Inspection(TimestampMixin, Base):
    __tablename__ = "inspections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lot_id: Mapped[int] = mapped_column(ForeignKey("lots.id"))
    result: Mapped[str] = mapped_column(String(16))
    note: Mapped[str | None] = mapped_column(String(255))

    lot: Mapped[Lot] = relationship(back_populates="inspections")


class Shipment(TimestampMixin, Base):
    __tablename__ = "shipments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ship_no: Mapped[str] = mapped_column(String(32), unique=True)
    lot_id: Mapped[int] = mapped_column(ForeignKey("lots.id"))
    quantity: Mapped[int] = mapped_column(Integer)

    lot: Mapped[Lot] = relationship(back_populates="shipments")


class TraceEvent(TimestampMixin, Base):
    __tablename__ = "trace_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lot_id: Mapped[int] = mapped_column(ForeignKey("lots.id"), index=True)
    type: Mapped[str] = mapped_column(String(32))
    message: Mapped[str] = mapped_column(Text)

    lot: Mapped[Lot] = relationship(back_populates="events")


class SensorReading(Base):
    """설비 센서 원시값 (long format). 3단계에서 시계열 DB로 이관 예정."""

    __tablename__ = "sensor_readings"
    __table_args__ = (Index("ix_sensor_readings_machine_time", "machine_id", "recorded_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    machine_id: Mapped[int] = mapped_column(ForeignKey("machines.id"))
    work_order_id: Mapped[int | None] = mapped_column(ForeignKey("work_orders.id"))
    sensor_code: Mapped[str] = mapped_column(String(32))
    value: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(16))
    recorded_at: Mapped[datetime] = mapped_column(DateTime)


class Alert(TimestampMixin, Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    machine_id: Mapped[int | None] = mapped_column(ForeignKey("machines.id"))
    severity: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(255))
    message: Mapped[str] = mapped_column(Text)
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)

    machine: Mapped[Machine | None] = relationship(back_populates="alerts")
