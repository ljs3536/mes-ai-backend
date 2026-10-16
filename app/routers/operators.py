"""사원 등록과 권한 변경. 관리자만 호출한다."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import hash_password, require_admin
from ..db import get_db
from ..models import Operator
from ..schemas import OperatorCreateIn, OperatorOut, OperatorUpdateIn
from ..services import DomainError

router = APIRouter(prefix="/operators", tags=["operators"])
Db = Annotated[Session, Depends(get_db)]
Admin = Annotated[Operator, Depends(require_admin)]


@router.post("", response_model=OperatorOut, status_code=201)
def create_operator(body: OperatorCreateIn, db: Db, _: Admin):
    taken = db.scalar(select(Operator.id).where(Operator.employee_no == body.employee_no))
    if taken is not None:
        raise DomainError("같은 사원번호가 있습니다.", 409)
    operator = Operator(
        employee_no=body.employee_no,
        name=body.name,
        role=body.role,
        password_hash=hash_password(body.password),
    )
    db.add(operator)
    db.commit()
    db.refresh(operator)
    return operator


@router.patch("/{operator_id}", response_model=OperatorOut)
def update_operator(operator_id: int, body: OperatorUpdateIn, db: Db, actor: Admin):
    operator = db.get(Operator, operator_id)
    if operator is None:
        raise DomainError("사원을 찾을 수 없습니다.", 404)
    if actor.id == operator.id and body.role != "ADMIN":
        raise DomainError("로그인 중인 관리자 권한은 여기서 내릴 수 없습니다.", 409)
    operator.name = body.name
    operator.role = body.role
    if body.password:
        if len(body.password) < 4:
            raise DomainError("비밀번호는 4자 이상입니다.", 422)
        operator.password_hash = hash_password(body.password)
    db.commit()
    db.refresh(operator)
    return operator
