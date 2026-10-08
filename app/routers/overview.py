from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import queries
from ..db import get_db
from ..schemas import DashboardOut, OperatorOut

# 대시보드 수량과 작업자 목록.
router = APIRouter(tags=["overview"])
Db = Annotated[Session, Depends(get_db)]


@router.get("/dashboard", response_model=DashboardOut)
def dashboard(db: Db):
    return queries.dashboard(db)


@router.get("/operators", response_model=list[OperatorOut])
def operators(db: Db):
    return queries.list_operators(db)
