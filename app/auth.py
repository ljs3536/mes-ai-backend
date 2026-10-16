"""사원 비밀번호와 로그인 토큰. 관리자만 이력 조회와 센서 변경을 한다."""

import hashlib
import hmac
import secrets
import time
from typing import Annotated

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .models import Operator

TOKEN_TTL_SECONDS = 12 * 60 * 60
ADMIN = "ADMIN"
OPERATOR = "OPERATOR"


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000).hex()
    return f"pbkdf2_sha256$200000${salt}${digest}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        scheme, rounds, salt, digest = stored.split("$", 3)
    except ValueError:
        return False
    if scheme != "pbkdf2_sha256":
        return False
    check = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(rounds)).hex()
    return hmac.compare_digest(check, digest)


def issue_token(operator_id: int) -> str:
    exp = int(time.time()) + TOKEN_TTL_SECONDS
    body = f"{operator_id}.{exp}"
    sig = hmac.new(get_settings().auth_secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def read_token(token: str, db: Session) -> Operator:
    try:
        operator_id, exp, sig = token.split(".", 2)
        body = f"{operator_id}.{exp}"
    except ValueError:
        raise HTTPException(401, "로그인이 필요합니다.") from None
    expected = hmac.new(get_settings().auth_secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig) or int(exp) < time.time():
        raise HTTPException(401, "로그인이 필요합니다.")
    operator = db.get(Operator, int(operator_id))
    if operator is None:
        raise HTTPException(401, "로그인이 필요합니다.")
    return operator


def require_user(
    db: Annotated[Session, Depends(get_db)],
    authorization: Annotated[str | None, Header()] = None,
) -> Operator:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "로그인이 필요합니다.")
    return read_token(authorization.removeprefix("Bearer ").strip(), db)


def require_admin(user: Annotated[Operator, Depends(require_user)]) -> Operator:
    if user.role != ADMIN:
        raise HTTPException(403, "관리자만 접근할 수 있습니다.")
    return user


def default_password(role: str) -> str:
    return "admin1234" if role == ADMIN else "work1234"


def ensure_operator_auth(db: Session) -> None:
    columns = db.execute(text("SHOW COLUMNS FROM operators LIKE 'password_hash'")).first()
    if columns is None:
        db.execute(text("ALTER TABLE operators ADD COLUMN password_hash VARCHAR(255) NULL"))
        db.commit()
    pending = list(db.scalars(select(Operator).where(Operator.password_hash.is_(None))))
    for operator in pending:
        operator.password_hash = hash_password(default_password(operator.role))
    if pending:
        db.commit()
