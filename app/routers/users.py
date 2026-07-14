"""Admin user management endpoints."""

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_admin
from app.models.user import User, UserRole
from app.schemas import (
    ActiveStatusRequest,
    MessageResponse,
    ResetPasswordRequest,
    UserCreateRequest,
    UserOut,
    UserUpdateRequest,
)
from app.services import user_service

router = APIRouter(
    prefix="/api/v1/users",
    tags=["users"],
    dependencies=[Depends(require_admin)],
)


@router.get("", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db)):
    return [UserOut.model_validate(u) for u in user_service.list_users(db)]


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(body: UserCreateRequest, db: Session = Depends(get_db)):
    user = user_service.create_user(
        db,
        email=body.email,
        password=body.password,
        full_name=body.full_name,
        role=UserRole(body.role.value),
        is_active=body.is_active,
    )
    return UserOut.model_validate(user)


@router.get("/{user_id}", response_model=UserOut)
def get_user(user_id: str, db: Session = Depends(get_db)):
    return UserOut.model_validate(user_service.get_user(db, user_id))


@router.patch("/{user_id}", response_model=UserOut)
def edit_user(user_id: str, body: UserUpdateRequest, db: Session = Depends(get_db)):
    user = user_service.get_user(db, user_id)
    updated = user_service.update_user(
        db,
        user,
        email=body.email,
        full_name=body.full_name,
        role=UserRole(body.role.value) if body.role is not None else None,
    )
    return UserOut.model_validate(updated)


@router.delete("/{user_id}", response_model=MessageResponse)
def delete_user(
    user_id: str,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    user = user_service.get_user(db, user_id)
    user_service.delete_user(db, user, actor_id=admin.id)
    return MessageResponse(detail="User deleted")


@router.post("/{user_id}/activate", response_model=UserOut)
def activate_user(
    user_id: str,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    user = user_service.get_user(db, user_id)
    updated = user_service.set_active(db, user, True, actor_id=admin.id)
    return UserOut.model_validate(updated)


@router.post("/{user_id}/deactivate", response_model=UserOut)
def deactivate_user(
    user_id: str,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    user = user_service.get_user(db, user_id)
    updated = user_service.set_active(db, user, False, actor_id=admin.id)
    return UserOut.model_validate(updated)


@router.patch("/{user_id}/active", response_model=UserOut)
def set_active_status(
    user_id: str,
    body: ActiveStatusRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    user = user_service.get_user(db, user_id)
    updated = user_service.set_active(db, user, body.is_active, actor_id=admin.id)
    return UserOut.model_validate(updated)


@router.post("/{user_id}/reset-password", response_model=MessageResponse)
def reset_password(
    user_id: str,
    body: ResetPasswordRequest,
    db: Session = Depends(get_db),
):
    user = user_service.get_user(db, user_id)
    user_service.reset_password(db, user, body.new_password)
    return MessageResponse(detail="Password reset; all sessions revoked")
