from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import InstrumentedAttribute

from .config import get_settings


def today_stamp() -> str:
    return datetime.now(ZoneInfo(get_settings().timezone)).strftime("%Y%m%d")


def next_serial(db: Session, column: InstrumentedAttribute[str], prefix: str) -> str:
    """Issue the next `PREFIX-YYYYMMDD-NNN` number for today."""
    head = f"{prefix}-{today_stamp()}-"
    existing = db.scalars(select(column).where(column.like(f"{head}%"))).all()
    last = max((int(v[len(head):]) for v in existing if v[len(head):].isdigit()), default=0)
    return f"{head}{last + 1:03d}"
