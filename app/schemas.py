"""Pydantic request/response models."""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, EmailStr, Field


class UserRoleOut(str, Enum):
    admin = "admin"
    user = "user"


# ---- Auth / users ----


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class UserOut(BaseModel):
    id: str
    email: EmailStr
    full_name: str
    role: UserRoleOut
    is_active: bool
    created_at: datetime
    updated_at: datetime
    last_login_at: datetime | None = None

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


class MessageResponse(BaseModel):
    detail: str


class UserCreateRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    full_name: str = ""
    role: UserRoleOut = UserRoleOut.user
    is_active: bool = True


class UserUpdateRequest(BaseModel):
    email: EmailStr | None = None
    full_name: str | None = None
    role: UserRoleOut | None = None


class ResetPasswordRequest(BaseModel):
    new_password: str = Field(min_length=8)


class ActiveStatusRequest(BaseModel):
    is_active: bool


# ---- Extract ----


class ParamValues(BaseModel):
    Min: str = ""
    Tar: str = ""
    Max: str = ""
    Unit: str = ""


class RecordOut(BaseModel):
    file: str
    SpecNo: str = ""
    Client: str = ""
    Quality: str = ""
    Grade: str = ""
    MatCode: str = ""
    Color: str = ""
    Ply: str = ""
    params: dict[str, ParamValues] = Field(default_factory=dict)


class ParseErrorOut(BaseModel):
    file: str
    message: str


class ParseResponse(BaseModel):
    run_id: str
    files_total: int
    files_ok: int
    files_failed: int
    columns: list[str]
    errors: list[ParseErrorOut]
    records: list[RecordOut]


class ExcelRequest(BaseModel):
    run_id: str
    selected_columns: list[str] = Field(min_length=1)
    filename: str = "Specifications_Combined.xlsx"


# ---- Dashboard ----


class UserDashboardResponse(BaseModel):
    total_runs: int
    files_processed: int
    files_ok: int
    files_failed: int
    successful_runs: int
    unsuccessful_runs: int
    excel_downloads: int
    last_run: datetime | None = None


class UserActivityItem(BaseModel):
    user_id: str
    email: str
    full_name: str
    role: str
    is_active: bool
    last_login_at: datetime | None = None
    total_runs: int = 0
    files_processed: int = 0
    successful_runs: int = 0
    unsuccessful_runs: int = 0
    excel_downloads: int = 0
    last_run_at: datetime | None = None


class AdminDashboardResponse(BaseModel):
    total_users: int
    active_users: int
    total_runs: int
    excel_runs: int
    successful_runs: int
    unsuccessful_runs: int
    files_processed: int
    users: list[UserActivityItem] = Field(default_factory=list)


class HealthResponse(BaseModel):
    status: str
    service: str
