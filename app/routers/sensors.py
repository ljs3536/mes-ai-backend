from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Machine, MachineSensor
from ..schemas import MachineSensorIn, MachineSensorOut
from ..services import DomainError

# 설비와 PIEZO 센서의 연결. 수집 주기, 샘플레이트, 샘플 수, 파형 프리셋을 설비별로 저장한다.
router = APIRouter(prefix="/sensors", tags=["sensors"])
Db = Annotated[Session, Depends(get_db)]

ALLOWED_N = {256, 512, 1024, 2048, 4096, 8192}


def _out(sensor: MachineSensor, machine: Machine) -> MachineSensorOut:
    return MachineSensorOut(
        id=sensor.id,
        machine_code=machine.code,
        code=sensor.code,
        name=sensor.name,
        sensor_type=sensor.sensor_type,
        mount=sensor.mount,
        unit=sensor.unit,
        sample_rate=sensor.sample_rate,
        n_samples=sensor.n_samples,
        interval_s=sensor.interval_s,
        preset=sensor.preset,
        severity=sensor.severity,
        enabled=sensor.enabled,
    )


def _check(data: MachineSensorIn) -> None:
    if data.n_samples not in ALLOWED_N:
        raise DomainError(f"샘플 개수는 {sorted(ALLOWED_N)} 중 하나여야 합니다.", 422)
    if data.sensor_type != "PIEZO":
        raise DomainError("현재 부착 센서 유형은 PIEZO만 지원합니다.", 422)


@router.get("", response_model=list[MachineSensorOut])
def list_sensors(db: Db, machine: Annotated[str | None, Query()] = None):
    stmt = select(MachineSensor, Machine).join(Machine).order_by(Machine.code, MachineSensor.code)
    if machine:
        stmt = stmt.where(Machine.code == machine)
    return [_out(sensor, machine_row) for sensor, machine_row in db.execute(stmt)]


@router.post("", response_model=MachineSensorOut, status_code=201)
def create_sensor(data: MachineSensorIn, db: Db, machine: Annotated[str, Query()]):
    _check(data)
    row = db.scalar(select(Machine).where(Machine.code == machine))
    if row is None:
        raise DomainError("설비를 찾을 수 없습니다.", 404)
    taken = db.scalar(
        select(MachineSensor.id).where(MachineSensor.machine_id == row.id, MachineSensor.code == data.code)
    )
    if taken is not None:
        raise DomainError("이 설비에 같은 센서 코드가 있습니다.", 409)
    sensor = MachineSensor(machine_id=row.id, **data.model_dump())
    db.add(sensor)
    db.commit()
    db.refresh(sensor)
    return _out(sensor, row)


@router.put("/{sensor_id}", response_model=MachineSensorOut)
def update_sensor(sensor_id: int, data: MachineSensorIn, db: Db):
    _check(data)
    sensor = db.get(MachineSensor, sensor_id)
    if sensor is None:
        raise DomainError("센서를 찾을 수 없습니다.", 404)
    taken = db.scalar(
        select(MachineSensor.id).where(
            MachineSensor.machine_id == sensor.machine_id,
            MachineSensor.code == data.code,
            MachineSensor.id != sensor.id,
        )
    )
    if taken is not None:
        raise DomainError("이 설비에 같은 센서 코드가 있습니다.", 409)
    for key, value in data.model_dump().items():
        setattr(sensor, key, value)
    db.commit()
    db.refresh(sensor)
    machine = db.get(Machine, sensor.machine_id)
    return _out(sensor, machine)


@router.delete("/{sensor_id}", status_code=204)
def delete_sensor(sensor_id: int, db: Db):
    sensor = db.get(MachineSensor, sensor_id)
    if sensor is None:
        raise DomainError("센서를 찾을 수 없습니다.", 404)
    db.delete(sensor)
    db.commit()
