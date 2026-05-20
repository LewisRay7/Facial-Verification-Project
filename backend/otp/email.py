from __future__ import annotations

import smtplib
import json
import urllib.request
from email.message import EmailMessage

from backend.config import settings


def send_otp_email(recipient: str, code: str) -> bool:
    if settings.resend_api_key and settings.resend_from:
        return _send_resend_email(recipient, code)
    if not settings.smtp_host or not settings.smtp_user or not settings.smtp_password:
        return False

    message = EmailMessage()
    message["Subject"] = "ExamVerify verification code"
    message["From"] = settings.smtp_from
    message["To"] = recipient
    message.set_content(
        f"Your ExamVerify verification code is {code}.\n\nThis code expires shortly."
    )

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as server:
        server.starttls()
        server.login(settings.smtp_user, settings.smtp_password)
        server.send_message(message)
    return True


def _send_resend_email(recipient: str, code: str) -> bool:
    payload = json.dumps(
        {
            "from": settings.resend_from,
            "to": [recipient],
            "subject": "ExamVerify verification code",
            "text": f"Your ExamVerify verification code is {code}.\n\nThis code expires shortly.",
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        "https://api.resend.com/emails",
        data=payload,
        headers={
            "Authorization": f"Bearer {settings.resend_api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return 200 <= response.status < 300
