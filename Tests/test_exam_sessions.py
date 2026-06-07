from __future__ import annotations

import os
from pathlib import Path
import unittest

TEST_DB = Path(__file__).resolve().parent / "exam_sessions_test.db"
TEST_DB.unlink(missing_ok=True)
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB.as_posix()}"
os.environ["JWT_SECRET"] = "exam-session-test-jwt"
os.environ["DATA_ENCRYPTION_KEY"] = "exam-session-test-data-key"
os.environ["SUPER_ADMIN_PASSWORD"] = "Admin@12345"

from fastapi.testclient import TestClient

from backend.auth.security import create_access_token
from backend.database import SessionLocal, engine
from backend.main import create_app
from backend.models.tables import Student, User


class ExamSessionEligibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(create_app())
        with SessionLocal() as db:
            admin = db.query(User).filter(User.username == "admin").first()
            cls.headers = {"Authorization": f"Bearer {create_access_token(admin)}"}

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client.close()
        engine.dispose()
        TEST_DB.unlink(missing_ok=True)

    def setUp(self) -> None:
        with SessionLocal() as db:
            for table in ["verification_logs", "exam_session_students", "exam_sessions", "students"]:
                db.execute(__import__("sqlalchemy").text(f"DELETE FROM {table}"))
            db.commit()
            john = Student(
                student_number_hash="john-hash",
                student_number_mask="24***01",
                full_name="John",
                program="DIT",
                level="4",
                status="active",
                active=True,
            )
            paul = Student(
                student_number_hash="paul-hash",
                student_number_mask="24***02",
                full_name="Paul",
                program="DIT",
                level="5",
                status="active",
                active=True,
            )
            suspended = Student(
                student_number_hash="suspended-hash",
                student_number_mask="24***03",
                full_name="Suspended",
                program="DIT",
                level="4",
                status="suspended",
                active=True,
            )
            db.add_all([john, paul, suspended])
            db.commit()
            self.john_id, self.paul_id, self.suspended_id = john.id, paul.id, suspended.id
        created = self.client.post(
            "/exam-sessions",
            headers=self.headers,
            json={
                "course_code": "DBS220",
                "course_name": "Database Systems",
                "program": "DIT",
                "level": "4",
                "exam_date": "2026-06-10",
                "venue": "Main Hall",
            },
        ).json()
        self.session_id = created["exam_session"]["id"]
        self.client.post(f"/exam-sessions/{self.session_id}/activate", headers=self.headers)

    def add(self, student_id: int, kind: str = "regular") -> None:
        response = self.client.post(
            f"/exam-sessions/{self.session_id}/eligible-students",
            headers=self.headers,
            json={"student_id": student_id, "eligibility_type": kind},
        )
        self.assertEqual(response.status_code, 200)

    def verify(self, student_id: int | None, **overrides):
        payload = {
            "detected_student_id": student_id,
            "match_score": 0.20,
            "confidence_gap": 0.12,
            "liveness_passed": True,
            "identity_matched": student_id is not None,
            "device_type": "desktop",
        }
        payload.update(overrides)
        return self.client.post(
            f"/exam-sessions/{self.session_id}/verify",
            headers=self.headers,
            json=payload,
        ).json()

    def test_regular_student_verified(self):
        self.add(self.john_id)
        self.assertEqual(self.verify(self.john_id)["decision"], "VERIFIED")

    def test_registered_but_not_eligible_denied(self):
        result = self.verify(self.paul_id)
        self.assertEqual(result["decision"], "DENIED")
        self.assertIn("not eligible", result["reason"])

    def test_repeat_student_from_other_level_verified(self):
        self.add(self.paul_id, "repeat")
        result = self.verify(self.paul_id)
        self.assertEqual(result["decision"], "VERIFIED")
        self.assertEqual(result["eligibility_type"], "repeat")

    def test_unknown_face_denied(self):
        result = self.verify(None, identity_matched=False)
        self.assertEqual(result["decision"], "DENIED")

    def test_duplicate_is_already_verified(self):
        self.add(self.john_id)
        self.verify(self.john_id)
        self.assertEqual(self.verify(self.john_id)["decision"], "ALREADY_VERIFIED")

    def test_suspended_student_denied(self):
        self.add(self.suspended_id)
        self.assertIn("suspended", self.verify(self.suspended_id)["reason"])

    def test_low_confidence_denied(self):
        self.add(self.john_id)
        result = self.verify(self.john_id, match_score=0.50)
        self.assertIn("threshold", result["reason"])

    def test_ambiguous_identity_denied(self):
        self.add(self.john_id)
        result = self.verify(self.john_id, confidence_gap=0.01)
        self.assertIn("ambiguous", result["reason"])


if __name__ == "__main__":
    unittest.main()
