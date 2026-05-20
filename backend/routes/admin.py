from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.auth.security import current_user, hash_password, require_roles, user_payload
from backend.database import get_db
from backend.logs.audit import log_event
from backend.models.schemas import AdminAccessRequestCreate, AdminDecisionRequest, ApiMessage
from backend.models.tables import AdminRequest, User

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/access-requests", response_model=ApiMessage)
def create_access_request(payload: AdminAccessRequestCreate, db: Annotated[Session, Depends(get_db)]) -> ApiMessage:
    exists = db.query(User).filter((User.username == payload.username.lower()) | (User.email == payload.email)).first()
    if exists:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Account already exists")
    request = AdminRequest(
        full_name=payload.full_name.strip(),
        email=str(payload.email).lower(),
        username=payload.username.strip().lower(),
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


def _request_to_dict(row: AdminRequest) -> dict:
    return {
        "id": row.id,
        "full_name": row.full_name,
        "email": row.email,
        "username": row.username,
        "requested_role": row.requested_role,
        "status": row.status,
        "note": row.note,
        "created_at": row.created_at.isoformat(),
        "decided_at": row.decided_at.isoformat() if row.decided_at else None,
        "decided_by": row.decided_by,
    }
