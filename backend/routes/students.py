from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.auth.security import require_roles
from backend.database import get_db
from backend.logs.audit import log_event
from backend.models.schemas import StudentSyncIn
from backend.models.tables import Student, User

router = APIRouter(prefix="/students", tags=["students"])


@router.get("")
def list_students(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_roles("Super Admin", "Admin", "Invigilator"))],
) -> dict:
    rows = db.query(Student).filter(Student.active.is_(True)).order_by(Student.full_name.asc()).all()
    return {"ok": True, "students": [_student_to_dict(row) for row in rows]}


@router.post("/sync")
def sync_student(
    payload: StudentSyncIn,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(require_roles("Super Admin", "Admin"))],
) -> dict:
    row = db.query(Student).filter(Student.student_number_hash == payload.student_number_hash).first()
    if row is None:
        row = Student(student_number_hash=payload.student_number_hash, student_number_mask=payload.student_number_mask)
        db.add(row)
    row.full_name = payload.full_name
    row.program = payload.program
    row.photo_url = payload.photo_url
    row.biometric_profile_json = json.dumps(payload.biometric_profile, sort_keys=True)
    row.active = True
    row.updated_at = datetime.utcnow()
    log_event(db, actor_username=actor.username, action="STUDENT_SYNCED", target=payload.student_number_mask)
    db.commit()
    db.refresh(row)
    return {"ok": True, "student": _student_to_dict(row)}


def _student_to_dict(row: Student) -> dict:
    return {
        "id": row.id,
        "student_number_hash": row.student_number_hash,
        "student_number_mask": row.student_number_mask,
        "full_name": row.full_name,
        "program": row.program,
        "photo_url": row.photo_url,
        "biometric_profile": json.loads(row.biometric_profile_json or "{}"),
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }
