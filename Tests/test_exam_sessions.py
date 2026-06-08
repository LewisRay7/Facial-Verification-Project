from __future__ import annotations

import os
from pathlib import Path
import unittest
from io import BytesIO
from openpyxl import Workbook

TEST_DB = Path(__file__).resolve().parent / "exam_sessions_test.db"
TEST_DB.unlink(missing_ok=True)
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB.as_posix()}"
os.environ["JWT_SECRET"] = "exam-session-test-jwt"
os.environ["DATA_ENCRYPTION_KEY"] = "exam-session-test-data-key"
os.environ["SUPER_ADMIN_PASSWORD"] = "Admin@12345"

from fastapi.testclient import TestClient

from backend.auth.security import create_access_token, hash_password
from backend.database import SessionLocal, engine
from backend.main import create_app
from backend.models.tables import Student, User
from backend.security.data_encryption import encrypt_json, hash_student_identifier


class ExamSessionEligibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(create_app())
        with SessionLocal() as db:
            admin = db.query(User).filter(User.username == "admin").first()
            cls.headers = {"Authorization": f"Bearer {create_access_token(admin)}"}
            for username in ["invigilator_a", "invigilator_b", "invigilator_c"]:
                user = db.query(User).filter(User.username == username).first()
                if user is None:
                    user = User(
                        username=username,
                        full_name=username.replace("_", " ").title(),
                        email=f"{username}@example.com",
                        role="Invigilator",
                        account_status="approved",
                        password_hash=hash_password("Verify@12345"),
                        active=True,
                    )
                    db.add(user)
                    db.commit()
                setattr(
                    cls,
                    f"{username}_headers",
                    {"Authorization": f"Bearer {create_access_token(user)}"},
                )
                setattr(cls, f"{username}_id", user.id)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client.close()
        engine.dispose()
        TEST_DB.unlink(missing_ok=True)

    def setUp(self) -> None:
        with SessionLocal() as db:
            for table in ["verification_logs", "exam_import_audits", "exam_session_invigilators", "exam_session_students", "exam_sessions", "students"]:
                db.execute(__import__("sqlalchemy").text(f"DELETE FROM {table}"))
            db.commit()
            john = Student(
                student_number_hash=hash_student_identifier("240001"),
                student_number_mask="24***01",
                full_name="John",
                program="DIT",
                level="4",
                status="active",
                active=True,
                biometric_profile_json=encrypt_json({"signature": [0.1] * 192}),
            )
            paul = Student(
                student_number_hash=hash_student_identifier("240002"),
                student_number_mask="24***02",
                full_name="Paul",
                program="DIT",
                level="5",
                status="active",
                active=True,
                biometric_profile_json=encrypt_json({"signature": [0.2] * 192}),
            )
            suspended = Student(
                student_number_hash=hash_student_identifier("240003"),
                student_number_mask="24***03",
                full_name="Suspended",
                program="DIT",
                level="4",
                status="suspended",
                active=True,
                biometric_profile_json=encrypt_json({"signature": [0.3] * 192}),
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

    def verify(self, student_id: int | None, headers=None, **overrides):
        payload = {
            "detected_student_id": student_id,
            "match_score": 0.20,
            "confidence_gap": 0.12,
            "liveness_passed": True,
            "identity_matched": student_id is not None,
            "device_type": "desktop",
            "device_id": "desk-a",
            "device_name": "Room 116 Desk A",
        }
        payload.update(overrides)
        return self.client.post(
            f"/exam-sessions/{self.session_id}/verify",
            headers=headers or self.headers,
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

    def test_matching_cohort_adds_only_active_program_and_level(self):
        response = self.client.post(
            f"/exam-sessions/{self.session_id}/eligible-students/from-cohort",
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["added"], 1)
        roster = self.client.get(
            f"/exam-sessions/{self.session_id}/eligible-students",
            headers=self.headers,
        ).json()["eligible_students"]
        self.assertEqual([row["student_name"] for row in roster], ["John"])

    def test_csv_import_links_existing_faces_and_reports_issues(self):
        with SessionLocal() as db:
            no_face = Student(
                student_number_hash=hash_student_identifier("24NOFACE"),
                student_number_mask="24***NF",
                full_name="No Face",
                program="DIT",
                level="4",
                status="active",
                active=True,
            )
            db.add(no_face)
            db.commit()
        csv_body = (
            "student_number,eligibility_type,full_name\n"
            "240001,regular,John\n"
            "24NOFACE,regular,No Face\n"
            "24MISSING,regular,Missing\n"
        )
        response = self.client.post(
            f"/exam-sessions/{self.session_id}/eligible-students/import",
            headers=self.headers,
            files={"file": ("eligible.csv", csv_body, "text/csv")},
        )
        self.assertEqual(response.status_code, 200)
        report = response.json()
        self.assertEqual(report["no_face_count"], 1)
        self.assertEqual(report["unmatched_count"], 1)
        self.assertEqual(report["linked_count"], 1)

    def test_twenty_row_import_summary(self):
        rows = []
        with SessionLocal() as db:
            for index in range(15):
                number = f"25FACE{index:02d}"
                db.add(
                    Student(
                        student_number_hash=hash_student_identifier(number),
                        student_number_mask=f"25***{index:02d}",
                        full_name=f"Face Student {index}",
                        program="DIT",
                        level="4",
                        status="active",
                        active=True,
                        biometric_profile_json=encrypt_json({"signature": [0.1] * 192}),
                    )
                )
                rows.append(f"{number},regular,Face Student {index}")
            for index in range(3):
                number = f"25NOFACE{index}"
                db.add(
                    Student(
                        student_number_hash=hash_student_identifier(number),
                        student_number_mask=f"25***N{index}",
                        full_name=f"No Face {index}",
                        program="DIT",
                        level="4",
                        status="active",
                        active=True,
                    )
                )
                rows.append(f"{number},regular,No Face {index}")
            db.commit()
        rows.extend(["25MISSING1,regular,Missing 1", "25MISSING2,regular,Missing 2"])
        response = self.client.post(
            f"/exam-sessions/{self.session_id}/eligible-students/import",
            headers=self.headers,
            files={
                "file": (
                    "twenty.csv",
                    "student_number,eligibility_type,full_name\n" + "\n".join(rows),
                    "text/csv",
                )
            },
        )
        report = response.json()
        self.assertEqual(report["total_rows"], 20)
        self.assertEqual(report["linked_count"], 15)
        self.assertEqual(report["no_face_count"], 3)
        self.assertEqual(report["unmatched_count"], 2)

    def test_xlsx_import_links_existing_face(self):
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["student_number", "eligibility_type", "notes"])
        sheet.append(["240001", "regular", "Registrar list"])
        content = BytesIO()
        workbook.save(content)
        response = self.client.post(
            f"/exam-sessions/{self.session_id}/eligible-students/import",
            headers=self.headers,
            files={
                "file": (
                    "eligible.xlsx",
                    content.getvalue(),
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["linked_count"], 1)

    def test_multiple_sessions_can_be_active(self):
        created = self.client.post(
            "/exam-sessions",
            headers=self.headers,
            json={
                "course_code": "BIT4400",
                "course_name": "Advanced Systems",
                "program": "BIT",
                "level": "4",
                "exam_date": "2026-06-10",
                "venue": "Main Hall",
            },
        ).json()["exam_session"]
        self.client.post(f"/exam-sessions/{created['id']}/activate", headers=self.headers)
        active = self.client.get("/exam-sessions/active", headers=self.headers).json()["exam_sessions"]
        self.assertEqual({row["course_code"] for row in active}, {"DBS220", "BIT4400"})

    def test_assigned_invigilators_share_atomic_duplicate_state(self):
        self.add(self.john_id)
        for user_id in [self.invigilator_a_id, self.invigilator_b_id]:
            self.client.post(
                f"/exam-sessions/{self.session_id}/assign-invigilator",
                headers=self.headers,
                json={"invigilator_user_id": user_id, "role_in_session": "support"},
            )
        first = self.verify(self.john_id, headers=self.invigilator_a_headers)
        second = self.verify(
            self.john_id,
            headers=self.invigilator_b_headers,
            device_id="desk-b",
            device_name="Room 116 Desk B",
        )
        self.assertEqual(first["decision"], "VERIFIED")
        self.assertEqual(second["decision"], "ALREADY_VERIFIED")
        self.assertEqual(second["verified_by"], "invigilator_a")
        self.assertEqual(second["verified_device_id"], "desk-a")

    def test_unassigned_invigilator_cannot_verify_assigned_session(self):
        self.add(self.john_id)
        self.client.post(
            f"/exam-sessions/{self.session_id}/assign-invigilator",
            headers=self.headers,
            json={"invigilator_user_id": self.invigilator_a_id, "role_in_session": "lead"},
        )
        result = self.verify(self.john_id, headers=self.invigilator_c_headers)
        self.assertIn("not assigned", result["reason"])

    def test_assigned_to_me_filters_active_sessions(self):
        self.client.post(
            f"/exam-sessions/{self.session_id}/assign-invigilator",
            headers=self.headers,
            json={"invigilator_user_id": self.invigilator_a_id, "role_in_session": "lead"},
        )
        sessions = self.client.get(
            "/exam-sessions/assigned-to-me",
            headers=self.invigilator_a_headers,
        ).json()["exam_sessions"]
        self.assertEqual([row["id"] for row in sessions], [self.session_id])

    def test_other_session_activity_returns_warning_without_blocking(self):
        self.add(self.john_id)
        self.assertEqual(self.verify(self.john_id)["decision"], "VERIFIED")
        second = self.client.post(
            "/exam-sessions",
            headers=self.headers,
            json={
                "course_code": "DIT410",
                "course_name": "Management Information Systems",
                "program": "DIT",
                "level": "4",
                "exam_date": "2026-06-10",
                "venue": "Room 116",
            },
        ).json()["exam_session"]
        self.client.post(f"/exam-sessions/{second['id']}/activate", headers=self.headers)
        self.client.post(
            f"/exam-sessions/{second['id']}/eligible-students",
            headers=self.headers,
            json={"student_id": self.john_id, "eligibility_type": "regular"},
        )
        result = self.client.post(
            f"/exam-sessions/{second['id']}/verify",
            headers=self.headers,
            json={
                "detected_student_id": self.john_id,
                "match_score": 0.20,
                "confidence_gap": 0.12,
                "liveness_passed": True,
                "identity_matched": True,
                "device_type": "desktop",
                "device_id": "desk-c",
            },
        ).json()
        self.assertEqual(result["decision"], "VERIFIED")
        self.assertTrue(result["other_session_activity"])

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
