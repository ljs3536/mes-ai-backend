from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import queries
from ..auth import require_user
from ..db import get_db
from ..models import Operator
from ..schemas import DashboardOut, OperatorOut

# 대시보드 수량과 작업자 목록.
router = APIRouter(tags=["overview"])
Db = Annotated[Session, Depends(get_db)]
User = Annotated[Operator, Depends(require_user)]


@router.get("/dashboard", response_model=DashboardOut)
def dashboard(db: Db, _: User):
    return queries.dashboard(db)


@router.get("/operators", response_model=list[OperatorOut])
def operators(db: Db, _: User):
    return queries.list_operators(db)
