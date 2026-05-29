from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.auth.security import require_roles
from backend.database import get_db
from backend.logs.audit import log_event
from backend.models.schemas import VerificationLogIn
from backend.models.tables import AuditLog, User, VerificationLog

router = APIRouter(prefix="/verification", tags=["verification"])


@router.post("/logs")
def create_verification_log(
    payload: VerificationLogIn,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(require_roles("Super Admin", "Admin", "Invigilator"))],
) -> dict:
    row = VerificationLog(
        student_id=payload.student_id,
        student_number_mask=payload.student_number_mask,
        full_name=payload.full_name,
        program=payload.program,
        status=payload.status,
        confidence=payload.confidence,
        liveness_score=payload.liveness_score,
        device_id=payload.device_id,
        metadata_json=json.dumps(payload.metadata, sort_keys=True),
    )
    db.add(row)
    log_event(
        db,
        actor_username=actor.username,
        action="VERIFICATION_EVENT",
        target=payload.student_number_mask,
        metadata={"status": payload.status, "confidence": payload.confidence},
    )
    db.commit()
    db.refresh(row)
    return {"ok": True, "log": _verification_log_to_dict(row)}


@router.get("/logs")
def list_verification_logs(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_roles("Super Admin", "Admin", "Invigilator"))],
) -> dict:
    rows = db.query(VerificationLog).order_by(VerificationLog.created_at.desc()).limit(500).all()
    return {"ok": True, "logs": [_verification_log_to_dict(row) for row in rows]}


@router.delete("/logs")
def clear_verification_logs(
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(require_roles("Super Admin", "Admin"))],
) -> dict:
    deleted_count = db.query(VerificationLog).count()
    db.query(VerificationLog).delete(synchronize_session=False)
    log_event(
        db,
        actor_username=actor.username,
        action="VERIFICATION_LOGS_CLEARED",
        metadata={"deleted": deleted_count},
    )
    db.commit()
    return {"ok": True, "deleted": deleted_count}


@router.get("/audit")
def list_audit_logs(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_roles("Super Admin", "Admin"))],
) -> dict:
    rows = db.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(500).all()
    return {
        "ok": True,
        "events": [
            {
                "id": row.id,
                "actor_username": row.actor_username,
                "action": row.action,
                "target": row.target,
                "metadata": json.loads(row.metadata_json or "{}"),
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ],
    }


def _verification_log_to_dict(row: VerificationLog) -> dict:
    return {
        "id": row.id,
        "student_id": row.student_id,
        "student_number_mask": row.student_number_mask,
        "full_name": row.full_name,
        "program": row.program,
        "status": row.status,
        "confidence": row.confidence,
        "liveness_score": row.liveness_score,
        "device_id": row.device_id,
        "metadata": json.loads(row.metadata_json or "{}"),
        "created_at": row.created_at.isoformat(),
    }
