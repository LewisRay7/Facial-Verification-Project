from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.auth.security import require_roles
from backend.database import get_db
from backend.logs.audit import log_event
from backend.models.schemas import (
    EligibleStudentAdd,
    ExamEntryEvaluateIn,
    ExamSessionCreate,
    ExamSessionUpdate,
)
from backend.models.tables import (
    ExamSession,
    ExamSessionStudent,
    Student,
    User,
    VerificationLog,
)

router = APIRouter(prefix="/exam-sessions", tags=["exam-sessions"])


@router.post("")
def create_exam_session(
    payload: ExamSessionCreate,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(require_roles("Super Admin", "Admin"))],
) -> dict:
    row = ExamSession(**payload.model_dump(), created_by=actor.username)
    db.add(row)
    log_event(db, actor_username=actor.username, action="EXAM_SESSION_CREATED", target=payload.course_code)
    db.commit()
    db.refresh(row)
    return {"ok": True, "exam_session": _session_dict(row)}


@router.get("")
def list_exam_sessions(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_roles("Super Admin", "Admin", "Invigilator"))],
) -> dict:
    rows = db.query(ExamSession).order_by(ExamSession.exam_date.desc(), ExamSession.start_time.desc()).all()
    return {"ok": True, "exam_sessions": [_session_dict(row) for row in rows]}


@router.get("/active")
def active_exam_sessions(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_roles("Super Admin", "Admin", "Invigilator"))],
) -> dict:
    rows = db.query(ExamSession).filter(ExamSession.status == "active").order_by(ExamSession.course_code).all()
    return {"ok": True, "exam_sessions": [_session_dict(row) for row in rows]}


@router.get("/{session_id}")
def get_exam_session(
    session_id: int,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_roles("Super Admin", "Admin", "Invigilator"))],
) -> dict:
    return {"ok": True, "exam_session": _session_dict(_session_or_404(db, session_id))}


@router.put("/{session_id}")
def update_exam_session(
    session_id: int,
    payload: ExamSessionUpdate,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(require_roles("Super Admin", "Admin"))],
) -> dict:
    row = _session_or_404(db, session_id)
    for key, value in payload.model_dump(exclude_none=True).items():
        setattr(row, key, value)
    row.updated_at = datetime.utcnow()
    log_event(db, actor_username=actor.username, action="EXAM_SESSION_UPDATED", target=str(session_id))
    db.commit()
    db.refresh(row)
    return {"ok": True, "exam_session": _session_dict(row)}


@router.post("/{session_id}/activate")
def activate_exam_session(
    session_id: int,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(require_roles("Super Admin", "Admin"))],
) -> dict:
    row = _session_or_404(db, session_id)
    row.status = "active"
    row.updated_at = datetime.utcnow()
    log_event(db, actor_username=actor.username, action="EXAM_SESSION_ACTIVATED", target=str(session_id))
    db.commit()
    return {"ok": True, "exam_session": _session_dict(row)}


@router.post("/{session_id}/complete")
def complete_exam_session(
    session_id: int,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(require_roles("Super Admin", "Admin"))],
) -> dict:
    row = _session_or_404(db, session_id)
    row.status = "completed"
    row.updated_at = datetime.utcnow()
    log_event(db, actor_username=actor.username, action="EXAM_SESSION_COMPLETED", target=str(session_id))
    db.commit()
    return {"ok": True, "exam_session": _session_dict(row)}


@router.post("/{session_id}/eligible-students")
def add_eligible_student(
    session_id: int,
    payload: EligibleStudentAdd,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(require_roles("Super Admin", "Admin"))],
) -> dict:
    _session_or_404(db, session_id)
    student = db.query(Student).filter(Student.id == payload.student_id).first()
    if student is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")
    row = db.query(ExamSessionStudent).filter(
        ExamSessionStudent.exam_session_id == session_id,
        ExamSessionStudent.student_id == payload.student_id,
    ).first()
    if row is None:
        row = ExamSessionStudent(exam_session_id=session_id, student_id=payload.student_id)
        db.add(row)
    row.eligibility_type = payload.eligibility_type
    row.eligibility_status = payload.eligibility_status
    row.notes = payload.notes
    row.updated_at = datetime.utcnow()
    log_event(db, actor_username=actor.username, action="EXAM_ELIGIBILITY_UPDATED", target=str(payload.student_id))
    db.commit()
    db.refresh(row)
    return {"ok": True, "eligible_student": _eligibility_dict(row)}


@router.get("/{session_id}/eligible-students")
def list_eligible_students(
    session_id: int,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_roles("Super Admin", "Admin", "Invigilator"))],
) -> dict:
    _session_or_404(db, session_id)
    rows = db.query(ExamSessionStudent).filter(ExamSessionStudent.exam_session_id == session_id).all()
    return {"ok": True, "eligible_students": [_eligibility_dict(row) for row in rows]}


@router.delete("/{session_id}/eligible-students/{student_id}")
def remove_eligible_student(
    session_id: int,
    student_id: int,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(require_roles("Super Admin", "Admin"))],
) -> dict:
    deleted = db.query(ExamSessionStudent).filter(
        ExamSessionStudent.exam_session_id == session_id,
        ExamSessionStudent.student_id == student_id,
    ).delete(synchronize_session=False)
    log_event(db, actor_username=actor.username, action="EXAM_ELIGIBILITY_REMOVED", target=str(student_id))
    db.commit()
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Eligible student link not found")
    return {"ok": True, "message": "Student removed from exam session"}


@router.post("/{session_id}/verify")
def evaluate_exam_entry(
    session_id: int,
    payload: ExamEntryEvaluateIn,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(require_roles("Super Admin", "Admin", "Invigilator"))],
) -> dict:
    session = _session_or_404(db, session_id)
    decision = "DENIED"
    reason = ""
    student = db.query(Student).filter(Student.id == payload.detected_student_id).first() if payload.detected_student_id else None
    eligibility = db.query(ExamSessionStudent).filter(
        ExamSessionStudent.exam_session_id == session_id,
        ExamSessionStudent.student_id == payload.detected_student_id,
    ).first() if payload.detected_student_id else None

    if session.status != "active":
        reason = "No active exam session selected."
    elif not payload.liveness_passed:
        reason = "Liveness failed."
    elif payload.match_score > payload.match_threshold:
        reason = "Match score below threshold."
    elif payload.confidence_gap < payload.minimum_confidence_gap:
        reason = "Similarity gap too small / ambiguous identity."
    elif not payload.identity_matched or student is None:
        reason = "Face not recognized."
    elif student.status != "active" or not student.active:
        reason = "Student inactive or suspended."
    elif eligibility is None:
        reason = "Student is registered in the system but not eligible for this exam session."
    elif eligibility.eligibility_status != "eligible":
        reason = "Student blocked from this exam session."
    elif eligibility.attendance_status == "verified" and not payload.admin_override:
        decision = "ALREADY_VERIFIED"
        reason = f"Student was already verified for this exam session at {eligibility.verified_at}."
    elif payload.admin_override and actor.role not in {"Super Admin", "Admin"}:
        reason = "Only an Admin or Super Admin may override a previous verification."
    elif payload.admin_override and not payload.override_reason.strip():
        reason = "Admin override requires a reason."
    else:
        decision = "VERIFIED"
        reason = "Identity, liveness, and exam-session eligibility confirmed."
        eligibility.attendance_status = "verified"
        eligibility.verified_at = datetime.utcnow()
        eligibility.verified_by = actor.username
        if payload.admin_override:
            eligibility.eligibility_type = "manual_override"
            eligibility.notes = payload.override_reason.strip()
        eligibility.updated_at = datetime.utcnow()

    if eligibility is not None and decision != "VERIFIED":
        eligibility.attendance_status = "already_verified" if decision == "ALREADY_VERIFIED" else "denied"
        eligibility.updated_at = datetime.utcnow()

    log = VerificationLog(
        student_id=student.id if student else None,
        exam_session_id=session.id,
        student_number_mask=student.student_number_mask if student else "",
        full_name=student.full_name if student else "Unknown face",
        program=student.program if student else "",
        status=decision,
        decision=decision,
        reason=reason,
        confidence=max(0.0, 1.0 - payload.match_score),
        confidence_gap=payload.confidence_gap,
        liveness_score=1.0 if payload.liveness_passed else 0.0,
        liveness_passed=payload.liveness_passed,
        eligibility_type=eligibility.eligibility_type if eligibility else "",
        verified_by=actor.username,
        device_type=payload.device_type,
        venue=session.venue,
        metadata_json=json.dumps({"admin_override": payload.admin_override}, sort_keys=True),
    )
    db.add(log)
    log_event(db, actor_username=actor.username, action="EXAM_ENTRY_DECISION", target=str(session_id), metadata={"decision": decision, "reason": reason})
    db.commit()
    return _decision_dict(decision, reason, session, student, eligibility, payload)


@router.get("/{session_id}/logs")
def exam_session_logs(
    session_id: int,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_roles("Super Admin", "Admin", "Invigilator"))],
) -> dict:
    rows = db.query(VerificationLog).filter(VerificationLog.exam_session_id == session_id).order_by(VerificationLog.created_at.desc()).all()
    return {"ok": True, "logs": [_log_dict(row) for row in rows]}


def _session_or_404(db: Session, session_id: int) -> ExamSession:
    row = db.query(ExamSession).filter(ExamSession.id == session_id).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exam session not found")
    return row


def _session_dict(row: ExamSession) -> dict:
    return {
        "id": row.id, "course_code": row.course_code, "course_name": row.course_name,
        "program": row.program, "level": row.level, "exam_date": row.exam_date,
        "start_time": row.start_time, "end_time": row.end_time, "venue": row.venue,
        "status": row.status, "created_by": row.created_by,
        "created_at": row.created_at.isoformat(), "updated_at": row.updated_at.isoformat(),
    }


def _eligibility_dict(row: ExamSessionStudent) -> dict:
    student = row.student
    return {
        "id": row.id, "exam_session_id": row.exam_session_id, "student_id": row.student_id,
        "student_number_mask": student.student_number_mask, "student_name": student.full_name,
        "program": student.program, "level": student.level, "student_status": student.status,
        "eligibility_type": row.eligibility_type, "eligibility_status": row.eligibility_status,
        "attendance_status": row.attendance_status,
        "verified_at": row.verified_at.isoformat() if row.verified_at else None,
        "verified_by": row.verified_by, "notes": row.notes,
    }


def _decision_dict(decision: str, reason: str, session: ExamSession, student: Student | None, eligibility: ExamSessionStudent | None, payload: ExamEntryEvaluateIn) -> dict:
    return {
        "decision": decision, "student_id": student.id if student else None,
        "student_name": student.full_name if student else None,
        "student_number": student.student_number_mask if student else None,
        "match_score": payload.match_score, "confidence_gap": payload.confidence_gap,
        "liveness_passed": payload.liveness_passed, "reason": reason,
        "eligibility_type": eligibility.eligibility_type if eligibility else None,
        "exam_session_id": session.id,
    }


def _log_dict(row: VerificationLog) -> dict:
    return {
        "id": row.id, "timestamp": row.created_at.isoformat(),
        "exam_session_id": row.exam_session_id, "detected_student_id": row.student_id,
        "detected_student_name": row.full_name, "decision": row.decision or row.status,
        "reason": row.reason, "match_score": 1.0 - row.confidence,
        "confidence_gap": row.confidence_gap, "liveness_passed": row.liveness_passed,
        "eligibility_type": row.eligibility_type, "verified_by": row.verified_by,
        "device_type": row.device_type, "venue": row.venue,
    }
