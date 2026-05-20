from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from backend.config import settings


connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, pool_pre_ping=True, connect_args=connect_args)
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
    with SessionLocal() as db:
        existing = db.query(User).filter(User.username == settings.super_admin_username).first()
        if existing is None:
            db.add(
                User(
                    username=settings.super_admin_username,
                    full_name="System Administrator",
                    email=settings.super_admin_email,
                    role="Super Admin",
                    password_hash=hash_password(settings.super_admin_password),
                    active=True,
                )
            )
            db.commit()
