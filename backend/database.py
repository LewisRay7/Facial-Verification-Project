from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from backend.config import settings


def _sqlalchemy_database_url(database_url: str) -> str:
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    if database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql+psycopg://", 1)
    return database_url


database_url = _sqlalchemy_database_url(settings.database_url)
connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
engine = create_engine(database_url, pool_pre_ping=True, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from backend.models.tables import Base as ModelsBase
    from backend.auth.security import hash_password
    from backend.models.tables import User

    ModelsBase.metadata.create_all(bind=engine)
    _ensure_access_request_columns()
    with SessionLocal() as db:
        existing = db.query(User).filter(User.username == settings.super_admin_username).first()
        if existing is None:
            db.add(
                User(
                    username=settings.super_admin_username,
                    full_name="System Administrator",
                    email=settings.super_admin_email,
                    role="Super Admin",
                    account_status="approved",
                    password_hash=hash_password(settings.super_admin_password),
                    active=True,
                )
            )
            db.commit()


def _ensure_access_request_columns() -> None:
    inspector = inspect(engine)
    user_columns = {column["name"] for column in inspector.get_columns("users")}
    request_columns = {
        column["name"] for column in inspector.get_columns("admin_requests")
    }
    statements: list[str] = []
    if "account_status" not in user_columns:
        statements.append(
            "ALTER TABLE users ADD COLUMN account_status VARCHAR(30) NOT NULL DEFAULT 'approved'"
        )
    if "phone_number" not in request_columns:
        statements.append(
            "ALTER TABLE admin_requests ADD COLUMN phone_number VARCHAR(40) NOT NULL DEFAULT ''"
        )
    if "department" not in request_columns:
        statements.append(
            "ALTER TABLE admin_requests ADD COLUMN department VARCHAR(160) NOT NULL DEFAULT ''"
        )
    if statements:
        with engine.begin() as connection:
            for statement in statements:
                connection.execute(text(statement))
