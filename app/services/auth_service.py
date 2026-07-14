"""Auth business logic: login, logout, refresh, session validation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.session import AuthSession
from app.models.user import User, UserRole
from app.security.jwt import TokenError, create_access_token, create_refresh_token, decode_token
from app.security.passwords import hash_password, verify_password
from app.security.tokens import hash_token


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def authenticate_user(db: Session, email: str, password: str) -> User:
    user = db.query(User).filter(User.email == email.lower().strip()).first()
    if user is None or not verify_password(password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated",
        )
    return user


def create_session_tokens(
    db: Session,
    user: User,
    *,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> dict:
    settings = get_settings()
    session = AuthSession(
        user_id=user.id,
        refresh_token_hash="pending",
        expires_at=_utcnow() + timedelta(days=settings.refresh_token_expire_days),
        user_agent=user_agent,
        ip_address=ip_address,
    )
    db.add(session)
    db.flush()

    access = create_access_token(
        subject=user.id,
        role=user.role.value,
        session_id=session.id,
    )
    refresh = create_refresh_token(subject=user.id, session_id=session.id)
    session.refresh_token_hash = hash_token(refresh)

    user.last_login_at = _utcnow()
    db.commit()
    db.refresh(user)
    db.refresh(session)

    return {
        "access_token": access,
        "refresh_token": refresh,
        "token_type": "bearer",
        "expires_in": settings.access_token_expire_minutes * 60,
        "user": user,
    }


def login(
    db: Session,
    email: str,
    password: str,
    *,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> dict:
    user = authenticate_user(db, email, password)
    return create_session_tokens(
        db, user, user_agent=user_agent, ip_address=ip_address
    )


def logout(db: Session, refresh_token: str) -> None:
    try:
        payload = decode_token(refresh_token)
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc
    if payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )
    session = (
        db.query(AuthSession)
        .filter(AuthSession.id == payload.get("sid"))
        .first()
    )
    if session is None:
        return
    if session.refresh_token_hash != hash_token(refresh_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )
    session.revoked_at = _utcnow()
    db.commit()


def refresh_tokens(
    db: Session,
    refresh_token: str,
    *,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> dict:
    try:
        payload = decode_token(refresh_token)
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc

    if payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )

    session = (
        db.query(AuthSession)
        .filter(AuthSession.id == payload.get("sid"))
        .first()
    )
    if (
        session is None
        or not session.is_valid
        or session.refresh_token_hash != hash_token(refresh_token)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session invalid or expired",
        )

    user = db.query(User).filter(User.id == session.user_id).first()
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated",
        )

    session.revoked_at = _utcnow()
    return create_session_tokens(
        db, user, user_agent=user_agent, ip_address=ip_address
    )


def get_valid_session(db: Session, session_id: str) -> AuthSession:
    session = db.query(AuthSession).filter(AuthSession.id == session_id).first()
    if session is None or not session.is_valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session invalid or expired",
        )
    return session


def seed_admin_if_needed(db: Session) -> None:
    """Create the bootstrap admin once if SEED_ADMIN_EMAIL is not in the DB."""
    settings = get_settings()
    email = settings.seed_admin_email.lower().strip()
    existing = db.query(User).filter(User.email == email).first()
    if existing:
        return
    admin = User(
        email=email,
        full_name=settings.seed_admin_name,
        hashed_password=hash_password(settings.seed_admin_password),
        role=UserRole.admin,
        is_active=True,
    )
    db.add(admin)
    db.commit()
