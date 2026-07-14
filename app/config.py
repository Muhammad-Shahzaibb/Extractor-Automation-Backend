"""Application settings loaded from environment variables."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    cors_origins: str = Field(
        default="http://localhost:3000,http://localhost:5173",
        alias="CORS_ORIGINS",
    )
    storage_root: Path = Field(
        default=BASE_DIR / "storage",
        alias="STORAGE_ROOT",
    )
    max_upload_mb: int = Field(default=25, alias="MAX_UPLOAD_MB")

    database_url: str = Field(
        default="postgresql+psycopg://postgres:postgres@localhost:5432/binaof_extractor",
        alias="DATABASE_URL",
    )

    jwt_secret_key: str = Field(
        default="change-me-jwt-secret-use-a-long-random-string",
        alias="JWT_SECRET_KEY",
    )
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    access_token_expire_minutes: int = Field(
        default=30,
        alias="ACCESS_TOKEN_EXPIRE_MINUTES",
    )
    refresh_token_expire_days: int = Field(
        default=7,
        alias="REFRESH_TOKEN_EXPIRE_DAYS",
    )

    # Bootstrap admin — created once on startup if this email is missing
    seed_admin_email: str = Field(
        default="Admin@qbsco.net",
        alias="SEED_ADMIN_EMAIL",
    )
    seed_admin_password: str = Field(
        default="Admin@123",
        alias="SEED_ADMIN_PASSWORD",
    )
    seed_admin_name: str = Field(default="QBS Admin", alias="SEED_ADMIN_NAME")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def uploads_root(self) -> Path:
        return self.storage_root / "uploads"

    @property
    def outputs_root(self) -> Path:
        return self.storage_root / "outputs"


@lru_cache
def get_settings() -> Settings:
    return Settings()
