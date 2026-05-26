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


class StudentSyncIn(BaseModel):
    student_number_hash: str
    student_number_mask: str
    full_name: str
    program: str = ""
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
