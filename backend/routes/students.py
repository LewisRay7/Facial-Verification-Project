from __future__ import annotations

from datetime import datetime
import json
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
    incoming_profile = _normalized_biometric_profile(payload.biometric_profile)
    if row is None:
        if not payload.review_confirmed:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Enrollment review is required. Confirm the student details "
                    "and captured portrait before saving the biometric profile."
                ),
            )
        row = Student(student_number_hash=payload.student_number_hash, student_number_mask=payload.student_number_mask)
        db.add(row)
        row.biometric_profile_version = 1
    else:
        current_profile = decrypt_json(row.biometric_profile_json or "{}")
        if _biometric_profile_changed(current_profile, incoming_profile):
            if not payload.replace_biometric_profile:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "This student already has an approved biometric profile. "
                        "Use controlled biometric replacement and provide a reason."
                    ),
                )
            if not payload.review_confirmed or not payload.replacement_reason.strip():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        "Biometric replacement requires enrollment review confirmation "
                        "and a replacement reason."
                    ),
                )
            incoming_profile = _profile_with_history(
                current_profile,
                incoming_profile,
                actor.username,
                payload.replacement_reason.strip(),
            )
            row.biometric_profile_version = max(
                1, int(row.biometric_profile_version or 1)
            ) + 1
            log_event(
                db,
                actor_username=actor.username,
                action="STUDENT_BIOMETRIC_REPLACED",
                target=row.student_number_mask,
                metadata={
                    "reason": payload.replacement_reason.strip(),
                    "profile_version": row.biometric_profile_version,
                },
            )
    row.full_name = payload.full_name
    row.program = payload.program
    row.level = payload.level
    row.status = payload.status
    biometric_profile = incoming_profile
    biometric_profile["portrait_sha256"] = sha256_text(payload.photo_url)
    biometric_profile["reviewed_by"] = actor.username
    biometric_profile["reviewed_at"] = datetime.utcnow().isoformat()
    biometric_profile["profile_version"] = row.biometric_profile_version
    row.photo_url = encrypt_text(payload.photo_url)
    row.biometric_profile_json = encrypt_json(biometric_profile)
    row.enrollment_status = "approved"
    row.enrollment_reviewed_by = actor.username
    row.enrollment_reviewed_at = datetime.utcnow()
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
        "level": row.level,
        "status": row.status,
        "enrollment_status": row.enrollment_status,
        "enrollment_reviewed_by": row.enrollment_reviewed_by,
        "enrollment_reviewed_at": (
            row.enrollment_reviewed_at.isoformat()
            if row.enrollment_reviewed_at
            else None
        ),
        "biometric_profile_version": row.biometric_profile_version,
        "photo_url": photo_url,
        "biometric_profile": biometric_profile,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def _normalized_biometric_profile(profile: dict) -> dict:
    normalized = dict(profile)
    samples: list[list[float]] = []
    values = normalized.get("embeddings")
    if isinstance(values, list):
        for value in values:
            if isinstance(value, list) and value:
                samples.append([float(item) for item in value])
    signature = normalized.get("signature")
    if isinstance(signature, list) and signature:
        sample = [float(item) for item in signature]
        if sample not in samples:
            samples.insert(0, sample)
    if samples:
        normalized["signature"] = samples[0]
        normalized["embeddings"] = samples[:5]
    return normalized


def _profile_samples(profile: dict) -> list[list[float]]:
    return _normalized_biometric_profile(profile).get("embeddings", [])


def _biometric_profile_changed(current: dict, incoming: dict) -> bool:
    return json.dumps(_profile_samples(current), sort_keys=True) != json.dumps(
        _profile_samples(incoming), sort_keys=True
    )


def _profile_with_history(
    current: dict,
    incoming: dict,
    actor_username: str,
    reason: str,
) -> dict:
    updated = dict(incoming)
    current_samples = _profile_samples(current)
    incoming_samples = _profile_samples(incoming)
    if incoming_samples:
        updated["signature"] = incoming_samples[0]
        updated["embeddings"] = incoming_samples[:5]
    history = list(current.get("replacement_history") or [])
    history.append(
        {
            "replaced_at": datetime.utcnow().isoformat(),
            "replaced_by": actor_username,
            "reason": reason,
            "previous_portrait_sha256": current.get("portrait_sha256", ""),
            "previous_embedding_count": len(current_samples),
        }
    )
    updated["replacement_history"] = history[-10:]
    return updated
