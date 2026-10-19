"""사원 등록과 직무 배정. 관리자만 호출한다."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import OPERATOR, hash_password, require_admin
from ..db import get_db
from ..models import Machine, Operator
from ..schemas import OperatorCreateIn, OperatorOut, OperatorUpdateIn
from ..services import DomainError

router = APIRouter(prefix="/operators", tags=["operators"])
Db = Annotated[Session, Depends(get_db)]
Admin = Annotated[Operator, Depends(require_admin)]


def _assign_role(db: Session, operator: Operator, role: str, machine_id: int | None) -> None:
    """직무를 정한다. 작업자만 설비 하나에 연결하고, 그 설비는 한 명만 맡는다."""
    if role == OPERATOR:
        if machine_id is None:
            raise DomainError("작업자는 담당 설비를 지정해야 합니다.")
        machine = db.get(Machine, machine_id)
        if machine is None:
            raise DomainError("설비를 찾을 수 없습니다.", 404)
        other = db.scalar(
            select(Operator).where(Operator.machine_id == machine.id, Operator.id != operator.id)
        )
        if other is not None:
            raise DomainError(f"{machine.name}은(는) {other.name}에게 배정되어 있습니다.", 409)
        operator.machine_id = machine.id
    else:
        operator.machine_id = None
    operator.role = role


@router.post("", response_model=OperatorOut, status_code=201)
def create_operator(body: OperatorCreateIn, db: Db, _: Admin):
    taken = db.scalar(select(Operator.id).where(Operator.employee_no == body.employee_no))
    if taken is not None:
        raise DomainError("같은 사원번호가 있습니다.", 409)
    operator = Operator(
        employee_no=body.employee_no,
        name=body.name,
        password_hash=hash_password(body.password),
    )
    db.add(operator)
    db.flush()
    _assign_role(db, operator, body.role, body.machine_id)
    db.commit()
    db.refresh(operator)
    return operator


@router.patch("/{operator_id}", response_model=OperatorOut)
def update_operator(operator_id: int, body: OperatorUpdateIn, db: Db, actor: Admin):
    operator = db.get(Operator, operator_id)
    if operator is None:
        raise DomainError("사원을 찾을 수 없습니다.", 404)
    if actor.id == operator.id and body.role != "ADMIN":
        raise DomainError("로그인 중인 관리자 직무는 여기서 바꿀 수 없습니다.", 409)
    operator.name = body.name
    _assign_role(db, operator, body.role, body.machine_id)
    if body.password:
        if len(body.password) < 4:
            raise DomainError("비밀번호는 4자 이상입니다.", 422)
        operator.password_hash = hash_password(body.password)
    db.commit()
    db.refresh(operator)
    return operator
