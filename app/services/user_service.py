"""User management (admin)."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.session import AuthSession
from app.models.user import User, UserRole
from app.security.passwords import hash_password


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def list_users(db: Session) -> list[User]:
    return db.query(User).order_by(User.created_at.desc()).all()


def get_user(db: Session, user_id: str) -> User:
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


def create_user(
    db: Session,
    *,
    email: str,
    password: str,
    full_name: str = "",
    role: UserRole = UserRole.user,
    is_active: bool = True,
) -> User:
    email_n = email.lower().strip()
    if db.query(User).filter(User.email == email_n).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )
    user = User(
        email=email_n,
        full_name=full_name.strip(),
        hashed_password=hash_password(password),
        role=role,
        is_active=is_active,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def update_user(
    db: Session,
    user: User,
    *,
    email: str | None = None,
    full_name: str | None = None,
    role: UserRole | None = None,
) -> User:
    if email is not None:
        email_n = email.lower().strip()
        clash = (
            db.query(User)
            .filter(User.email == email_n, User.id != user.id)
            .first()
        )
        if clash:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Email already registered",
            )
        user.email = email_n
    if full_name is not None:
        user.full_name = full_name.strip()
    if role is not None:
        user.role = role
    user.updated_at = _utcnow()
    db.commit()
    db.refresh(user)
    return user


def delete_user(db: Session, user: User, *, actor_id: str) -> None:
    if user.id == actor_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete your own account",
        )
    db.delete(user)
    db.commit()


def set_active(db: Session, user: User, active: bool, *, actor_id: str) -> User:
    if user.id == actor_id and not active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot deactivate your own account",
        )
    user.is_active = active
    user.updated_at = _utcnow()
    if not active:
        # Revoke all sessions
        now = _utcnow()
        sessions = (
            db.query(AuthSession)
            .filter(
                AuthSession.user_id == user.id,
                AuthSession.revoked_at.is_(None),
            )
            .all()
        )
        for s in sessions:
            s.revoked_at = now
    db.commit()
    db.refresh(user)
    return user


def reset_password(db: Session, user: User, new_password: str) -> User:
    user.hashed_password = hash_password(new_password)
    user.updated_at = _utcnow()
    now = _utcnow()
    sessions = (
        db.query(AuthSession)
        .filter(
            AuthSession.user_id == user.id,
            AuthSession.revoked_at.is_(None),
        )
        .all()
    )
    for s in sessions:
        s.revoked_at = now
    db.commit()
    db.refresh(user)
    return user
