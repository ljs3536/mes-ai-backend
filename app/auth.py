"""사원 비밀번호와 로그인 토큰. 화면과 API는 직무로 나눈다."""

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
PUBLIC_AUTH_SECRET = "mes-local-session"
ADMIN = "ADMIN"
MATERIAL = "MATERIAL"
PLANNER = "PLANNER"
OPERATOR = "OPERATOR"
QUALITY = "QUALITY"
ROLES = (ADMIN, MATERIAL, PLANNER, OPERATOR, QUALITY)


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


def token_matches(provided: str | None, expected: str) -> bool:
    if not expected or not provided:
        return False
    return hmac.compare_digest(
        hashlib.sha256(provided.encode()).digest(),
        hashlib.sha256(expected.encode()).digest(),
    )


def require_internal(x_internal_token: Annotated[str | None, Header()] = None) -> None:
    """분석 서비스가 설비 보류를 호출할 때 쓰는 내부 토큰만 통과한다."""
    if not token_matches(x_internal_token, get_settings().internal_token):
        raise HTTPException(401, "내부 호출 인증이 필요합니다.")


def require_admin_or_internal(
    db: Annotated[Session, Depends(get_db)],
    authorization: Annotated[str | None, Header()] = None,
    x_internal_token: Annotated[str | None, Header()] = None,
) -> None:
    """관리자 세션 또는 에뮬레이터 내부 토큰만 센서 목록을 본다."""
    if token_matches(x_internal_token, get_settings().internal_token):
        return
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "로그인이 필요합니다.")
    user = read_token(authorization.removeprefix("Bearer ").strip(), db)
    if user.role != ADMIN:
        raise HTTPException(403, "관리자만 접근할 수 있습니다.")


def ensure_auth_secret() -> None:
    secret = get_settings().auth_secret
    if secret == PUBLIC_AUTH_SECRET or len(secret) < 16:
        raise RuntimeError("AUTH_SECRET을 16자 이상의 비공개 값으로 설정하세요.")


def require_role(*roles: str):
    """지정한 직무만 이 의존성을 통과한다."""

    def dependency(user: Annotated[Operator, Depends(require_user)]) -> Operator:
        if user.role not in roles:
            raise HTTPException(403, "이 직무로는 할 수 없습니다.")
        return user

    return dependency


def default_password(role: str) -> str:
    return {
        ADMIN: "admin1234",
        MATERIAL: "mat1234",
        PLANNER: "plan1234",
        OPERATOR: "work1234",
        QUALITY: "qual1234",
    }.get(role, "work1234")


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
