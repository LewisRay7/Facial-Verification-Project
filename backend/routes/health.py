from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.config import settings
from backend.database import get_db
from backend.otp.email import email_delivery_status

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    return {"ok": True, "service": "ExamVerify Cloud API"}


@router.get("/health/ready")
def readiness(db: Annotated[Session, Depends(get_db)]) -> dict:
    db.execute(text("SELECT 1"))
    email_status = email_delivery_status()
    return {
        "ok": True,
        "service": "ExamVerify Cloud API",
        "database": "ready",
        "database_mode": settings.database_mode,
        "environment": settings.environment,
        "email_provider_configured": email_status["configured"],
        "email_arbitrary_recipient_ready": email_status[
            "arbitrary_recipient_sender_configured"
        ],
        "email_resend_test_sender": email_status["resend_test_sender"],
        "email_smtp_fallback_configured": email_status["smtp_fallback_configured"],
        "data_encryption_configured": bool(settings.data_encryption_key),
    }
