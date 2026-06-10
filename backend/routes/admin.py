from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.auth.security import current_user, hash_password, require_roles, user_payload
from backend.database import get_db
from backend.logs.audit import log_event
from backend.models.schemas import (
    AdminAccessRequestCreate,
    AdminDecisionRequest,
    ApiMessage,
    UserPasswordResetRequest,
)
from backend.models.tables import AdminRequest, User

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/access-requests", response_model=ApiMessage)
def create_access_request(payload: AdminAccessRequestCreate, db: Annotated[Session, Depends(get_db)]) -> ApiMessage:
    username = payload.username.strip().lower()
    email = str(payload.email).lower()
    exists = db.query(User).filter((User.username == username) | (User.email == email)).first()
    if exists:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Account already exists")
    pending = (
        db.query(AdminRequest)
        .filter(
            (AdminRequest.username == username) | (AdminRequest.email == email),
            AdminRequest.status == "pending",
        )
        .first()
    )
    if pending:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An access request is already pending")
    request = AdminRequest(
        full_name=payload.full_name.strip(),
        email=email,
        username=username,
        phone_number=payload.phone_number.strip(),
        department=payload.department.strip(),
        requested_role=payload.requested_role,
        note=payload.note,
    )
    db.add(request)
    log_event(db, actor_username=request.username, action="ADMIN_REQUEST_CREATED", target=request.email)
    db.commit()
    return ApiMessage(message="Access request submitted for Super Admin review.")


@router.get("/access-requests")
def list_access_requests(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_roles("Super Admin"))],
) -> dict:
    rows = db.query(AdminRequest).order_by(AdminRequest.created_at.desc()).all()
    return {"ok": True, "requests": [_request_to_dict(row) for row in rows]}


@router.post("/access-requests/{request_id}/decision", response_model=ApiMessage)
def decide_access_request(
    request_id: int,
    payload: AdminDecisionRequest,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(require_roles("Super Admin"))],
) -> ApiMessage:
    request = db.query(AdminRequest).filter(AdminRequest.id == request_id).first()
    if request is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")
    if request.status != "pending":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Request already decided")
    request.status = payload.status
    request.decided_by = actor.username
    request.decided_at = datetime.utcnow()
    if payload.status == "approved":
        temporary_password = payload.temporary_password or "ChangeMe@12345"
        db.add(
            User(
                username=request.username,
                full_name=request.full_name,
                email=request.email,
                role=request.requested_role,
                account_status="approved",
                password_hash=hash_password(temporary_password),
                active=True,
            )
        )
    log_event(db, actor_username=actor.username, action=f"ADMIN_REQUEST_{payload.status.upper()}", target=request.email)
    db.commit()
    return ApiMessage(message=f"Access request {payload.status}.")


@router.get("/users/me")
def me(user: Annotated[User, Depends(current_user)]) -> dict:
    return {"ok": True, "user": user_payload(user)}


@router.get("/users")
def list_users(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_roles("Super Admin", "Admin"))],
) -> dict:
    rows = db.query(User).filter(User.active.is_(True)).order_by(User.full_name).all()
    return {"ok": True, "users": [user_payload(row) for row in rows]}


@router.post("/users/reset-password", response_model=ApiMessage)
def reset_user_password(
    payload: UserPasswordResetRequest,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(require_roles("Super Admin"))],
) -> ApiMessage:
    username = payload.username.strip().lower()
    user = db.query(User).filter(User.username == username).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if user.role == "Super Admin":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Use the deployment recovery process for Super Admin credentials",
        )
    user.password_hash = hash_password(payload.temporary_password)
    user.failed_attempts = 0
    user.locked_until = None
    user.pending_otp_hash = None
    user.pending_otp_expires_at = None
    log_event(
        db,
        actor_username=actor.username,
        action="USER_PASSWORD_RESET",
        target=user.username,
    )
    db.commit()
    return ApiMessage(message=f"Temporary password reset for {user.full_name}.")


def _request_to_dict(row: AdminRequest) -> dict:
    return {
        "id": row.id,
        "full_name": row.full_name,
        "email": row.email,
        "username": row.username,
        "phone_number": row.phone_number,
        "department": row.department,
        "requested_role": row.requested_role,
        "status": row.status,
        "note": row.note,
        "created_at": row.created_at.isoformat(),
        "decided_at": row.decided_at.isoformat() if row.decided_at else None,
        "decided_by": row.decided_by,
    }
