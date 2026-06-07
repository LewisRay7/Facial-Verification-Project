from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.auth.security import require_roles
from backend.database import get_db
from backend.logs.audit import log_event
from backend.models.schemas import StudentSyncIn
from backend.models.tables import Student, User
from backend.security.data_encryption import (
    PREFIX,
    decrypt_json,
    decrypt_text,
    encrypt_json,
    encrypt_text,
    sha256_text,
)

router = APIRouter(prefix="/students", tags=["students"])


@router.get("")
def list_students(
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(require_roles("Super Admin", "Admin", "Invigilator"))],
) -> dict:
    rows = db.query(Student).filter(Student.active.is_(True)).order_by(Student.full_name.asc()).all()
    students = []
    for row in rows:
        students.append(_student_to_dict(row))
        if row.photo_url and not row.photo_url.startswith(PREFIX):
            row.photo_url = encrypt_text(row.photo_url)
        if row.biometric_profile_json and not row.biometric_profile_json.startswith(PREFIX):
            row.biometric_profile_json = encrypt_text(row.biometric_profile_json)
    log_event(
        db,
        actor_username=actor.username,
        action="STUDENT_RECORDS_VIEWED",
        metadata={"record_count": len(students)},
    )
    db.commit()
    return {"ok": True, "students": students}


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
    biometric_profile = dict(payload.biometric_profile)
    biometric_profile["portrait_sha256"] = sha256_text(payload.photo_url)
    row.photo_url = encrypt_text(payload.photo_url)
    row.biometric_profile_json = encrypt_json(biometric_profile)
    row.active = True
    row.updated_at = datetime.utcnow()
    log_event(db, actor_username=actor.username, action="STUDENT_SYNCED", target=payload.student_number_mask)
    db.commit()
    db.refresh(row)
    return {"ok": True, "student": _student_to_dict(row)}


@router.delete("/{student_number_hash}")
def delete_student(
    student_number_hash: str,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(require_roles("Super Admin", "Admin"))],
) -> dict:
    row = db.query(Student).filter(Student.student_number_hash == student_number_hash).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")
    row.active = False
    row.updated_at = datetime.utcnow()
    log_event(
        db,
        actor_username=actor.username,
        action="STUDENT_DELETED",
        target=row.student_number_mask,
    )
    db.commit()
    return {"ok": True, "message": "Student record deleted"}


def _student_to_dict(row: Student) -> dict:
    try:
        photo_url = decrypt_text(row.photo_url or "")
        biometric_profile = decrypt_json(row.biometric_profile_json or "{}")
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Stored student biometric data could not be authenticated.",
        ) from error
    expected_hash = biometric_profile.get("portrait_sha256")
    if expected_hash and expected_hash != sha256_text(photo_url):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Stored student portrait failed its integrity check.",
        )
    return {
        "id": row.id,
        "student_number_hash": row.student_number_hash,
        "student_number_mask": row.student_number_mask,
        "full_name": row.full_name,
        "program": row.program,
        "photo_url": photo_url,
        "biometric_profile": biometric_profile,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }
