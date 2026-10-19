from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import queries
from ..auth import require_admin
from ..db import get_db
from ..models import Operator
from ..schemas import DashboardOut, OperatorOut

# 대시보드와 사원 목록은 관리자가 본다.
router = APIRouter(tags=["overview"])
Db = Annotated[Session, Depends(get_db)]
Admin = Annotated[Operator, Depends(require_admin)]


@router.get("/dashboard", response_model=DashboardOut)
def dashboard(db: Db, _: Admin):
    return queries.dashboard(db)


@router.get("/operators", response_model=list[OperatorOut])
def operators(db: Db, _: Admin):
    return queries.list_operators(db)
