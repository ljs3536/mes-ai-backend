from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import queries
from ..db import get_db
from ..schemas import DashboardOut, OperatorOut

router = APIRouter(tags=["overview"])
Db = Annotated[Session, Depends(get_db)]


@router.get("/dashboard", response_model=DashboardOut)
def dashboard(db: Db):
    return queries.dashboard(db)


@router.get("/operators", response_model=list[OperatorOut])
def operators(db: Db):
    return queries.list_operators(db)
