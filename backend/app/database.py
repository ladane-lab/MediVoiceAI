"""SQLAlchemy database engine, session factory, and base model configuration."""

from pathlib import Path
from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import BACKEND_DIR, get_settings


def resolve_database_url(raw_url: str) -> str:
    """Resolve relative SQLite URLs inside the backend directory."""
    if raw_url.startswith("sqlite:///./"):
        relative_path = raw_url.removeprefix("sqlite:///./")
        db_path = (BACKEND_DIR / relative_path).resolve()
        return f"sqlite:///{db_path.as_posix()}"
    return raw_url


settings = get_settings()
DATABASE_URL = resolve_database_url(settings.database_url)

connect_args = {"check_same_thread": False, "timeout": 15} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    echo=False,
)


if DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
        """Ensure SQLite enforces foreign keys and waits briefly on lock contention."""
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy ORM models."""


def get_db():
    """Yield a database session per request and close it cleanly."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
