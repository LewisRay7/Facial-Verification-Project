from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from backend.config import Settings, _env_int


class ConfigurationParsingTests(unittest.TestCase):
    def test_blank_numeric_environment_values_use_defaults(self) -> None:
        with patch.dict(
            os.environ,
            {
                "JWT_MINUTES": "",
                "OTP_TTL_SECONDS": "",
                "LOCKOUT_FAILURES": "",
                "LOCKOUT_MINUTES": "",
                "SMTP_PORT": "",
            },
            clear=False,
        ):
            settings = Settings()

        self.assertEqual(settings.jwt_minutes, 60)
        self.assertEqual(settings.otp_ttl_seconds, 600)
        self.assertEqual(settings.lockout_failures, 5)
        self.assertEqual(settings.lockout_minutes, 15)
        self.assertEqual(settings.smtp_port, 587)

    def test_valid_numeric_environment_value_is_preserved(self) -> None:
        with patch.dict(os.environ, {"SMTP_PORT": "2525"}, clear=False):
            self.assertEqual(_env_int("SMTP_PORT", 587), 2525)

    def test_invalid_numeric_environment_value_uses_default(self) -> None:
        with patch.dict(os.environ, {"SMTP_PORT": "not-a-port"}, clear=False):
            self.assertEqual(_env_int("SMTP_PORT", 587), 587)


if __name__ == "__main__":
    unittest.main()
