"""로그인. 화면 서버가 토큰을 받아 브라우저 쿠키로 보관한다."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import issue_token, require_user, verify_password
from ..db import get_db
from ..models import Operator
from ..schemas import LoginIn, LoginOut, OperatorOut

router = APIRouter(prefix="/auth", tags=["auth"])
Db = Annotated[Session, Depends(get_db)]


@router.post("/login", response_model=LoginOut)
def login(body: LoginIn, db: Db):
    operator = db.scalar(select(Operator).where(Operator.employee_no == body.employee_no))
    if operator is None or not verify_password(body.password, operator.password_hash):
        raise HTTPException(401, "사원번호 또는 비밀번호가 맞지 않습니다.")
    return LoginOut(token=issue_token(operator.id), operator=OperatorOut.model_validate(operator))


@router.get("/me", response_model=OperatorOut)
def me(user: Annotated[Operator, Depends(require_user)]):
    return user
