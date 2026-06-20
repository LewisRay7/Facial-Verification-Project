from __future__ import annotations

import smtplib
import json
import logging
import urllib.error
import urllib.request
from email.message import EmailMessage
from email.utils import parseaddr

from backend.config import settings


logger = logging.getLogger(__name__)


def send_otp_email(recipient: str, code: str) -> bool:
    recipient = recipient.strip().lower()
    if not _is_deliverable_email(recipient):
        logger.warning("OTP email skipped: invalid or local-only recipient %s", recipient)
        return False

    if settings.resend_api_key and settings.resend_from:
        try:
            if _send_resend_email(recipient, code):
                return True
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            logger.warning(
                "OTP email delivery failed via resend: HTTP %s %s",
                exc.code,
                body,
            )
        except Exception as exc:
            logger.warning("OTP email delivery failed via resend: %s", exc)

    if _smtp_configured():
        try:
            return _send_smtp_email(recipient, code)
        except Exception as exc:
            logger.warning("OTP email delivery failed via smtp fallback: %s", exc)

    logger.warning(
        "OTP email delivery failed: no successful provider and SMTP fallback is incomplete."
    )
    return False


def email_delivery_status() -> dict[str, object]:
    resend_configured = bool(settings.resend_api_key and settings.resend_from)
    sender_address = parseaddr(settings.resend_from)[1].strip().lower()
    sender_domain = sender_address.rsplit("@", 1)[-1] if "@" in sender_address else ""
    resend_test_sender = sender_domain == "resend.dev"
    smtp_configured = _smtp_configured()
    return {
        "configured": resend_configured or smtp_configured,
        "resend_configured": resend_configured,
        "resend_sender_domain": sender_domain,
        "resend_test_sender": resend_test_sender,
        "smtp_fallback_configured": smtp_configured,
        "arbitrary_recipient_sender_configured": bool(
            smtp_configured or (resend_configured and sender_domain and not resend_test_sender)
        ),
    }


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
            "User-Agent": "ExamVerify/1.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return 200 <= response.status < 300


def _send_smtp_email(recipient: str, code: str) -> bool:
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


def _smtp_configured() -> bool:
    return bool(
        settings.smtp_host
        and settings.smtp_user
        and settings.smtp_password
        and settings.smtp_from
    )


def _is_deliverable_email(recipient: str) -> bool:
    if "@" not in recipient:
        return False
    domain = recipient.rsplit("@", 1)[-1]
    return bool(domain and domain not in {"localhost", "examverify.local"})
