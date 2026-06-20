from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import patch

from backend.otp import email


def _settings(**overrides):
    values = {
        "resend_api_key": "",
        "resend_from": "",
        "smtp_host": "",
        "smtp_port": 587,
        "smtp_user": "",
        "smtp_password": "",
        "smtp_from": "",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class OtpEmailTests(unittest.TestCase):
    def test_smtp_fallback_runs_when_resend_fails(self) -> None:
        settings = _settings(
            resend_api_key="re_test",
            resend_from="ExamVerify <otp@example.edu>",
            smtp_host="smtp.example.edu",
            smtp_user="otp@example.edu",
            smtp_password="secret",
            smtp_from="otp@example.edu",
        )
        with (
            patch.object(email, "settings", settings),
            patch.object(
                email,
                "_send_resend_email",
                side_effect=RuntimeError("resend unavailable"),
            ),
            patch.object(email, "_send_smtp_email", return_value=True) as smtp,
        ):
            self.assertTrue(email.send_otp_email("approved@example.com", "123456"))
            smtp.assert_called_once_with("approved@example.com", "123456")

    def test_local_only_recipient_is_rejected_without_delivery_attempt(self) -> None:
        settings = _settings(
            resend_api_key="re_test",
            resend_from="ExamVerify <onboarding@resend.dev>",
        )
        with (
            patch.object(email, "settings", settings),
            patch.object(email, "_send_resend_email") as resend,
        ):
            self.assertFalse(
                email.send_otp_email("invigilator@examverify.local", "123456")
            )
            resend.assert_not_called()

    def test_delivery_status_flags_resend_test_sender(self) -> None:
        settings = _settings(
            resend_api_key="re_test",
            resend_from="ExamVerify <onboarding@resend.dev>",
        )
        with patch.object(email, "settings", settings):
            status = email.email_delivery_status()
        self.assertTrue(status["configured"])
        self.assertTrue(status["resend_test_sender"])
        self.assertFalse(status["arbitrary_recipient_sender_configured"])

    def test_delivery_status_accepts_custom_resend_sender(self) -> None:
        settings = _settings(
            resend_api_key="re_live",
            resend_from="ExamVerify <otp@examverify.example>",
        )
        with patch.object(email, "settings", settings):
            status = email.email_delivery_status()
        self.assertTrue(status["configured"])
        self.assertFalse(status["resend_test_sender"])
        self.assertTrue(status["arbitrary_recipient_sender_configured"])

    def test_smtp_configuration_does_not_claim_hosted_delivery_readiness(self) -> None:
        settings = _settings(
            resend_api_key="re_test",
            resend_from="ExamVerify <onboarding@resend.dev>",
            smtp_host="smtp.example.edu",
            smtp_user="otp@example.edu",
            smtp_password="secret",
            smtp_from="otp@example.edu",
        )
        with patch.object(email, "settings", settings):
            status = email.email_delivery_status()
        self.assertTrue(status["smtp_fallback_configured"])
        self.assertFalse(status["arbitrary_recipient_sender_configured"])


if __name__ == "__main__":
    unittest.main()
