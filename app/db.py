"""SQLAlchemy engine and session factory (PostgreSQL)."""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


def _make_engine():
    settings = get_settings()
    url = settings.database_url
    if not url.startswith("postgresql"):
        raise RuntimeError(
            "DATABASE_URL must be a PostgreSQL URL "
            "(e.g. postgresql+psycopg://user:pass@localhost:5432/binaof)"
        )
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
    )


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create tables from ORM models if they do not already exist."""
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
