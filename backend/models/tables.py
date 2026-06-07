from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(160))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    role: Mapped[str] = mapped_column(String(40), default="Invigilator")
    account_status: Mapped[str] = mapped_column(String(30), default="approved")
    password_hash: Mapped[str] = mapped_column(String(255))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    pending_otp_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    pending_otp_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AdminRequest(Base):
    __tablename__ = "admin_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    full_name: Mapped[str] = mapped_column(String(160))
    email: Mapped[str] = mapped_column(String(255), index=True)
    username: Mapped[str] = mapped_column(String(80), index=True)
    phone_number: Mapped[str] = mapped_column(String(40), default="")
    department: Mapped[str] = mapped_column(String(160), default="")
    requested_role: Mapped[str] = mapped_column(String(40), default="Invigilator")
    status: Mapped[str] = mapped_column(String(30), default="pending")
    note: Mapped[str] = mapped_column(Text, default="")
    decided_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Student(Base):
    __tablename__ = "students"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_number_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    student_number_mask: Mapped[str] = mapped_column(String(40), index=True)
    full_name: Mapped[str] = mapped_column(String(180), index=True)
    program: Mapped[str] = mapped_column(String(180), default="")
    level: Mapped[str] = mapped_column(String(60), default="")
    status: Mapped[str] = mapped_column(String(30), default="active", index=True)
    photo_url: Mapped[str] = mapped_column(Text, default="")
    biometric_profile_json: Mapped[str] = mapped_column(Text, default="{}")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    logs: Mapped[list["VerificationLog"]] = relationship(back_populates="student")
    exam_eligibilities: Mapped[list["ExamSessionStudent"]] = relationship(
        back_populates="student"
    )


class ExamSession(Base):
    __tablename__ = "exam_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    course_code: Mapped[str] = mapped_column(String(60), index=True)
    course_name: Mapped[str] = mapped_column(String(180))
    program: Mapped[str] = mapped_column(String(180), default="")
    level: Mapped[str] = mapped_column(String(60), default="")
    exam_date: Mapped[str] = mapped_column(String(20), index=True)
    start_time: Mapped[str] = mapped_column(String(20), default="")
    end_time: Mapped[str] = mapped_column(String(20), default="")
    venue: Mapped[str] = mapped_column(String(180), default="")
    status: Mapped[str] = mapped_column(String(30), default="scheduled", index=True)
    created_by: Mapped[str] = mapped_column(String(80), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    eligible_students: Mapped[list["ExamSessionStudent"]] = relationship(
        back_populates="exam_session", cascade="all, delete-orphan"
    )


class ExamSessionStudent(Base):
    __tablename__ = "exam_session_students"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    exam_session_id: Mapped[int] = mapped_column(
        ForeignKey("exam_sessions.id"), index=True
    )
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), index=True)
    eligibility_type: Mapped[str] = mapped_column(String(30), default="regular")
    eligibility_status: Mapped[str] = mapped_column(String(30), default="eligible")
    attendance_status: Mapped[str] = mapped_column(String(30), default="not_verified")
    verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    verified_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    exam_session: Mapped[ExamSession] = relationship(back_populates="eligible_students")
    student: Mapped[Student] = relationship(back_populates="exam_eligibilities")


class VerificationLog(Base):
    __tablename__ = "verification_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int | None] = mapped_column(ForeignKey("students.id"), nullable=True)
    exam_session_id: Mapped[int | None] = mapped_column(
        ForeignKey("exam_sessions.id"), nullable=True, index=True
    )
    student_number_mask: Mapped[str] = mapped_column(String(40), default="")
    full_name: Mapped[str] = mapped_column(String(180), default="")
    program: Mapped[str] = mapped_column(String(180), default="")
    status: Mapped[str] = mapped_column(String(40), index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    liveness_score: Mapped[float] = mapped_column(Float, default=0.0)
    decision: Mapped[str] = mapped_column(String(40), default="")
    reason: Mapped[str] = mapped_column(Text, default="")
    confidence_gap: Mapped[float] = mapped_column(Float, default=0.0)
    liveness_passed: Mapped[bool] = mapped_column(Boolean, default=False)
    eligibility_type: Mapped[str] = mapped_column(String(30), default="")
    verified_by: Mapped[str] = mapped_column(String(80), default="")
    device_type: Mapped[str] = mapped_column(String(40), default="")
    venue: Mapped[str] = mapped_column(String(180), default="")
    device_id: Mapped[str] = mapped_column(String(120), default="")
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    student: Mapped[Student | None] = relationship(back_populates="logs")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_username: Mapped[str] = mapped_column(String(80), default="system")
    action: Mapped[str] = mapped_column(String(120), index=True)
    target: Mapped[str] = mapped_column(String(180), default="")
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
