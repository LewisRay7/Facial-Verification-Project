from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.config import settings
from backend.database import get_db

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    return {"ok": True, "service": "ExamVerify Cloud API"}


@router.get("/health/ready")
def readiness(db: Annotated[Session, Depends(get_db)]) -> dict:
    db.execute(text("SELECT 1"))
    return {
        "ok": True,
        "service": "ExamVerify Cloud API",
        "database": "ready",
        "environment": settings.environment,
        "email_provider_configured": bool(
            settings.resend_api_key
            or (settings.smtp_host and settings.smtp_user and settings.smtp_password)
        ),
        "data_encryption_configured": bool(settings.data_encryption_key),
    }
