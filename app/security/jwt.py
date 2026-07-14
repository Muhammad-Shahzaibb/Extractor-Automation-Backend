"""JWT create / decode helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from jose import JWTError, jwt

from app.config import get_settings


class TokenError(Exception):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def create_access_token(
    *,
    subject: str,
    role: str,
    session_id: str,
    extra: dict[str, Any] | None = None,
) -> str:
    settings = get_settings()
    now = _utcnow()
    payload: dict[str, Any] = {
        "sub": subject,
        "role": role,
        "sid": session_id,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
        "jti": str(uuid4()),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(
        payload,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def create_refresh_token(*, subject: str, session_id: str) -> str:
    settings = get_settings()
    now = _utcnow()
    payload = {
        "sub": subject,
        "sid": session_id,
        "type": "refresh",
        "iat": now,
        "exp": now + timedelta(days=settings.refresh_token_expire_days),
        "jti": str(uuid4()),
    }
    return jwt.encode(
        payload,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def decode_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        return jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError as exc:
        raise TokenError("Invalid or expired token") from exc
