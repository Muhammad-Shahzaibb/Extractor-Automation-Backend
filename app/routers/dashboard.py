"""User and admin dashboard endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user, require_admin
from app.models.run import ExtractionRun
from app.models.user import User
from app.schemas import AdminDashboardResponse, UserActivityItem, UserDashboardResponse

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])


def _stats_for_runs(rows: list[ExtractionRun]) -> dict:
    total_runs = len(rows)
    files_processed = sum(r.files_total or 0 for r in rows)
    files_ok = sum(r.files_ok or 0 for r in rows)
    files_failed = sum(r.files_failed or 0 for r in rows)
    successful = sum(1 for r in rows if r.status == "completed")
    unsuccessful = sum(1 for r in rows if r.status == "failed")
    excel_downloads = sum(1 for r in rows if r.excel_generated)
    last_run = max((r.created_at for r in rows), default=None) if rows else None
    return {
        "total_runs": total_runs,
        "files_processed": files_processed,
        "files_ok": files_ok,
        "files_failed": files_failed,
        "successful_runs": successful,
        "unsuccessful_runs": unsuccessful,
        "excel_downloads": excel_downloads,
        "last_run": last_run,
    }


@router.get("/user", response_model=UserDashboardResponse)
def user_dashboard(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = db.query(ExtractionRun).filter(ExtractionRun.user_id == user.id).all()
    s = _stats_for_runs(rows)
    return UserDashboardResponse(**s)


@router.get("/admin", response_model=AdminDashboardResponse)
def admin_dashboard(
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    all_runs = db.query(ExtractionRun).all()
    s = _stats_for_runs(all_runs)

    total_users = db.query(func.count(User.id)).scalar() or 0
    active_users = (
        db.query(func.count(User.id)).filter(User.is_active.is_(True)).scalar() or 0
    )

    users = (
        db.query(User)
        .order_by(User.last_login_at.is_(None), User.last_login_at.desc())
        .all()
    )
    activity: list[UserActivityItem] = []
    for u in users:
        u_rows = [r for r in all_runs if r.user_id == u.id]
        us = _stats_for_runs(u_rows)
        activity.append(
            UserActivityItem(
                user_id=u.id,
                email=u.email,
                full_name=u.full_name,
                role=u.role.value,
                is_active=u.is_active,
                last_login_at=u.last_login_at,
                total_runs=us["total_runs"],
                files_processed=us["files_processed"],
                successful_runs=us["successful_runs"],
                unsuccessful_runs=us["unsuccessful_runs"],
                excel_downloads=us["excel_downloads"],
                last_run_at=us["last_run"],
            )
        )

    return AdminDashboardResponse(
        total_users=total_users,
        active_users=active_users,
        total_runs=s["total_runs"],
        excel_runs=s["excel_downloads"],
        successful_runs=s["successful_runs"],
        unsuccessful_runs=s["unsuccessful_runs"],
        files_processed=s["files_processed"],
        users=activity,
    )
