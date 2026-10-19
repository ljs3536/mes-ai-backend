"""품목별 검사 기준. 관리자가 등록하고, 품질 검사 화면이 그 기준을 읽는다."""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from ..auth import require_admin, require_role
from ..db import get_db
from ..models import Operator
from ..schemas import InspectionSpecIn, InspectionSpecOut
from ..services import create_inspection_spec, delete_inspection_spec, list_inspection_specs

router = APIRouter(prefix="/inspection-specs", tags=["inspection-specs"])
Db = Annotated[Session, Depends(get_db)]


@router.get("", response_model=list[InspectionSpecOut])
def specs(db: Db, _: Annotated[Operator, Depends(require_role("ADMIN", "QUALITY"))]):
    return list_inspection_specs(db)


@router.post("", response_model=InspectionSpecOut, status_code=status.HTTP_201_CREATED)
def add_spec(body: InspectionSpecIn, db: Db, _: Annotated[Operator, Depends(require_admin)]):
    return create_inspection_spec(db, body)


@router.delete("/{spec_id}")
def remove_spec(spec_id: int, db: Db, _: Annotated[Operator, Depends(require_admin)]):
    delete_inspection_spec(db, spec_id)
    return {"name": "deleted"}
