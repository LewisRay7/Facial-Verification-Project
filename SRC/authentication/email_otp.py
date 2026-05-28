from __future__ import annotations

from dataclasses import dataclass
import os
import random
import smtplib
from email.message import EmailMessage


@dataclass
class EmailOtpResult:
    sent: bool
    message: str


def generate_email_otp() -> str:
    return f"{random.SystemRandom().randint(0, 999999):06d}"


def send_email_otp(recipient: str, code: str) -> EmailOtpResult:
    host = os.getenv("EXAMVERIFY_SMTP_HOST")
    username = os.getenv("EXAMVERIFY_SMTP_USER")
    password = os.getenv("EXAMVERIFY_SMTP_PASSWORD")
    sender = os.getenv("EXAMVERIFY_SMTP_FROM", username or "")
    port = int(os.getenv("EXAMVERIFY_SMTP_PORT", "587"))

    if not host or not username or not password or not recipient:
        return EmailOtpResult(
            sent=False,
            message="SMTP is not configured. Using local demo OTP display.",
        )

    message = EmailMessage()
    message["Subject"] = "ExamVerify login code"
    message["From"] = sender
    message["To"] = recipient
    message.set_content(
        f"Your ExamVerify login code is {code}.\n\n"
        "This code expires in 5 minutes. If you did not request it, ignore this email."
    )

    with smtplib.SMTP(host, port, timeout=20) as server:
        server.starttls()
        server.login(username, password)
        server.send_message(message)

    return EmailOtpResult(sent=True, message=f"OTP sent to {recipient}.")
