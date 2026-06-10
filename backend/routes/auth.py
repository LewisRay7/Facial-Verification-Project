from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.auth.security import (
    create_access_token,
    generate_otp,
    hash_otp,
    user_payload,
    verify_password,
)
from backend.config import settings
from backend.database import get_db
from backend.logs.audit import log_event
from backend.models.schemas import LoginRequest, OtpVerifyRequest, TokenResponse
from backend.models.tables import AdminRequest, User
from backend.otp.email import send_otp_email

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login")
def login(payload: LoginRequest, db: Annotated[Session, Depends(get_db)]) -> dict:
    username = payload.username.strip().lower()
    user = (
        db.query(User)
        .filter(or_(User.username == username, User.email == username))
        .first()
    )
    now = datetime.utcnow()
    if user is None:
        request = (
            db.query(AdminRequest)
            .filter(or_(AdminRequest.username == username, AdminRequest.email == username))
            .order_by(AdminRequest.created_at.desc())
            .first()
        )
        if request is not None and request.status == "pending":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your access request is still under review.",
            )
        if request is not None and request.status == "rejected":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your access request was not approved. Contact the system administrator.",
            )
        log_event(db, actor_username=username, action="LOGIN_FAILED", metadata={"reason": "unknown_user"})
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not user.active or user.account_status == "disabled":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account is disabled. Contact the system administrator.",
        )
    if user.account_status != "approved":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your access request is still under review.",
        )
    if payload.requested_role == "Admin" and user.role not in {"Super Admin", "Admin"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This account is not approved for Admin access.")
    if payload.requested_role == "Invigilator" and user.role != "Invigilator":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This account is not approved for Invigilator access.")
    if user.locked_until and user.locked_until > now:
        log_event(db, actor_username=username, action="LOGIN_LOCKED")
        db.commit()
        raise HTTPException(status_code=status.HTTP_423_LOCKED, detail="Account temporarily locked")
    if not verify_password(payload.password, user.password_hash):
        user.failed_attempts += 1
        if user.failed_attempts >= settings.lockout_failures:
            user.locked_until = now + timedelta(minutes=settings.lockout_minutes)
            user.failed_attempts = 0
        log_event(db, actor_username=username, action="LOGIN_FAILED", metadata={"reason": "bad_password"})
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    code = generate_otp()
    user.pending_otp_hash = hash_otp(code)
    user.pending_otp_expires_at = now + timedelta(seconds=settings.otp_ttl_seconds)
    user.failed_attempts = 0
    user.locked_until = None
    email_sent = send_otp_email(user.email, code)
    log_event(db, actor_username=user.username, action="OTP_ISSUED", target=user.email, metadata={"sent": email_sent})
    db.commit()
    if not email_sent and settings.is_production:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Your password was accepted, but the verification email could "
                "not be delivered. Contact the system administrator."
            ),
        )
    response = {"ok": True, "message": "Verification code sent.", "email_sent": email_sent}
    if not email_sent and not settings.is_production:
        response["developer_code"] = code
    return response


@router.post("/verify-otp", response_model=TokenResponse)
def verify_otp(payload: OtpVerifyRequest, db: Annotated[Session, Depends(get_db)]) -> TokenResponse:
    username = payload.username.strip().lower()
    user = (
        db.query(User)
        .filter(
            or_(User.username == username, User.email == username),
            User.active.is_(True),
            User.account_status == "approved",
        )
        .first()
    )
    now = datetime.utcnow()
    if (
        user is None
        or user.pending_otp_hash != hash_otp(payload.otp)
        or user.pending_otp_expires_at is None
        or user.pending_otp_expires_at < now
    ):
        log_event(db, actor_username=username, action="OTP_FAILED")
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired code")
    user.pending_otp_hash = None
    user.pending_otp_expires_at = None
    token = create_access_token(user)
    log_event(db, actor_username=user.username, action="LOGIN_SUCCESS")
    db.commit()
    return TokenResponse(
        access_token=token,
        expires_in=settings.jwt_minutes * 60,
        user=user_payload(user),
    )
