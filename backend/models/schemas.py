from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field


Role = Literal["Super Admin", "Admin", "Invigilator"]


class LoginRequest(BaseModel):
    username: str = Field(min_length=2, max_length=80)
    password: str = Field(min_length=6, max_length=200)
    requested_role: Literal["Admin", "Invigilator"] | None = None


class OtpVerifyRequest(BaseModel):
    username: str
    otp: str = Field(min_length=6, max_length=6)


class TokenResponse(BaseModel):
    ok: bool = True
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: dict[str, Any]


class AdminAccessRequestCreate(BaseModel):
    full_name: str = Field(min_length=3, max_length=160)
    email: EmailStr
    username: str = Field(min_length=3, max_length=80)
    phone_number: str = Field(default="", max_length=40)
    department: str = Field(default="", max_length=160)
    requested_role: Literal["Admin", "Invigilator"] = "Invigilator"
    note: str = ""


class AdminDecisionRequest(BaseModel):
    status: Literal["approved", "rejected"]
    temporary_password: str | None = Field(default=None, min_length=8)


class UserPasswordResetRequest(BaseModel):
    username: str = Field(min_length=3, max_length=80)
    temporary_password: str = Field(min_length=8, max_length=200)


class StudentSyncIn(BaseModel):
    student_number_hash: str
    student_number_mask: str
    full_name: str
    program: str = ""
    level: str = ""
    status: Literal["active", "inactive", "suspended"] = "active"
    photo_url: str = ""
    biometric_profile: dict[str, Any] = Field(default_factory=dict)


class VerificationLogIn(BaseModel):
    student_id: int | None = None
    student_number_mask: str = ""
    full_name: str = ""
    program: str = ""
    status: Literal["VERIFIED", "UNAUTHORIZED", "SPOOF_DETECTED", "REJECTED"]
    confidence: float = 0.0
    liveness_score: float = 0.0
    device_id: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    exam_session_id: int | None = None
    decision: str = ""
    reason: str = ""
    confidence_gap: float = 0.0
    liveness_passed: bool = False
    eligibility_type: str = ""
    device_type: str = ""
    venue: str = ""


class ExamSessionCreate(BaseModel):
    course_code: str = Field(min_length=2, max_length=60)
    course_name: str = Field(min_length=2, max_length=180)
    program: str = ""
    level: str = ""
    exam_date: str
    start_time: str = ""
    end_time: str = ""
    venue: str = ""


class ExamSessionUpdate(BaseModel):
    course_code: str | None = None
    course_name: str | None = None
    program: str | None = None
    level: str | None = None
    exam_date: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    venue: str | None = None
    status: Literal["scheduled", "active", "completed", "cancelled"] | None = None


class EligibleStudentAdd(BaseModel):
    student_id: int
    eligibility_type: Literal[
        "regular", "repeat", "deferred", "supplementary", "manual_override"
    ] = "regular"
    eligibility_status: Literal["eligible", "blocked", "completed"] = "eligible"
    notes: str = ""


class InvigilatorAssignmentIn(BaseModel):
    invigilator_user_id: int
    role_in_session: Literal["lead", "support"] = "support"


class ExamEntryEvaluateIn(BaseModel):
    detected_student_id: int | None = None
    match_score: float = 1.0
    confidence_gap: float = 0.0
    match_threshold: float = 0.30
    minimum_confidence_gap: float = 0.08
    liveness_passed: bool = False
    identity_matched: bool = False
    device_type: Literal["mobile", "desktop", "web"] = "desktop"
    device_id: str = ""
    device_name: str = ""
    admin_override: bool = False
    override_reason: str = ""


class ApiMessage(BaseModel):
    ok: bool = True
    message: str


class AuditLogOut(BaseModel):
    id: int
    actor_username: str
    action: str
    target: str
    metadata: dict[str, Any]
    created_at: datetime
