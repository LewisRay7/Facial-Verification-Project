from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    app_name: str = "ExamVerify Cloud API"
    environment: str = os.getenv("EXAMVERIFY_ENV", "development")
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./examverify_cloud.db")
    jwt_secret: str = os.getenv("JWT_SECRET", "change-this-before-deploying")
    data_encryption_key: str = os.getenv("DATA_ENCRYPTION_KEY", "")
    jwt_issuer: str = os.getenv("JWT_ISSUER", "examverify")
    jwt_minutes: int = int(os.getenv("JWT_MINUTES", "60"))
    otp_ttl_seconds: int = int(os.getenv("OTP_TTL_SECONDS", "600"))
    lockout_failures: int = int(os.getenv("LOCKOUT_FAILURES", "5"))
    lockout_minutes: int = int(os.getenv("LOCKOUT_MINUTES", "15"))
    cors_origins: str = os.getenv("CORS_ORIGINS", "*")

    super_admin_username: str = os.getenv("SUPER_ADMIN_USERNAME", "admin")
    super_admin_email: str = os.getenv("SUPER_ADMIN_EMAIL", "admin@examverify.local")
    super_admin_password: str = os.getenv("SUPER_ADMIN_PASSWORD", "Admin@12345")

    smtp_host: str = os.getenv("SMTP_HOST", "")
    smtp_port: int = int(os.getenv("SMTP_PORT", "587"))
    smtp_user: str = os.getenv("SMTP_USER", "")
    smtp_password: str = os.getenv("SMTP_PASSWORD", "")
    smtp_from: str = os.getenv("SMTP_FROM", "") or os.getenv("SMTP_USER", "")
    resend_api_key: str = os.getenv("RESEND_API_KEY", "")
    resend_from: str = os.getenv("RESEND_FROM", "") or os.getenv("SMTP_FROM", "")

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"

    @property
    def cors_list(self) -> list[str]:
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
