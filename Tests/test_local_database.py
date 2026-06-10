from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from backend.config import Settings
from SRC import database


class LocalDatabaseStabilizationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_path = database.DB_PATH
        database.DB_PATH = Path(self.temp_dir.name) / "examverify-test.db"
        database.init_db()

    def tearDown(self) -> None:
        database.DB_PATH = self.original_db_path
        self.temp_dir.cleanup()

    def test_student_registration_updates_and_audit_events_do_not_crash(self) -> None:
        photo = Path(self.temp_dir.name) / "student.jpg"
        photo.write_bytes(b"test portrait")

        student_id = database.add_student(
            "2410470",
            "Test Student",
            "DIT",
            photo,
            face_embedding="[0.1, 0.2]",
            embedding_backend="test",
            level="4",
        )
        self.assertGreater(student_id, 0)

        database.update_student_details(
            student_id,
            "2410470",
            "Updated Student",
            "DIT",
            True,
            "",
            level="5",
        )
        database.update_student_photo(
            student_id,
            photo,
            face_embedding="[0.2, 0.3]",
            embedding_backend="test-refresh",
        )
        database.set_student_active(student_id, False)

        events = database.list_audit_events()
        event_types = {event["event_type"] for event in events}
        self.assertIn("STUDENT_REGISTERED", event_types)
        self.assertIn("STUDENT_DETAILS_UPDATED", event_types)
        self.assertIn("STUDENT_PHOTO_UPDATED", event_types)
        self.assertIn("STUDENT_STATUS_UPDATED", event_types)
        registered = next(
            event for event in events if event["event_type"] == "STUDENT_REGISTERED"
        )
        self.assertIn("student_number_hash=", registered["details"])
        self.assertNotIn("2410470", registered["details"])
        student = database.get_student(student_id)
        self.assertEqual(student["level"], "5")
        self.assertEqual(database.get_student_by_number("2410470")["level"], "5")
        self.assertEqual(database.list_students(active_only=False)[0]["level"], "5")
        self.assertEqual(
            database.search_students("5", active_only=False)[0]["level"],
            "5",
        )

    def test_matching_cohort_uses_program_and_level(self) -> None:
        photo = Path(self.temp_dir.name) / "student.jpg"
        photo.write_bytes(b"test portrait")
        matching_id = database.add_student(
            "2410472",
            "Matching Student",
            "DIT",
            photo,
            face_embedding="[0.1, 0.2]",
            embedding_backend="test",
            level="4",
        )
        database.add_student(
            "2410473",
            "Wrong Level",
            "DIT",
            photo,
            face_embedding="[0.1, 0.2]",
            embedding_backend="test",
            level="2",
        )
        database.add_student(
            "2410474",
            "Wrong Program",
            "DBIT",
            photo,
            face_embedding="[0.1, 0.2]",
            embedding_backend="test",
            level="4",
        )
        session_id = database.create_exam_session(
            "DIT410",
            "Management Information Systems",
            "DIT",
            "4",
            "2026-06-10",
            "",
            "",
            "Room 116",
            "admin",
        )

        self.assertEqual(database.add_matching_exam_cohort(session_id), 1)
        roster = database.list_exam_session_students(session_id)
        self.assertEqual([row["student_id"] for row in roster], [matching_id])
        self.assertEqual(roster[0]["level"], "4")

    def test_verification_log_and_integrity_check_do_not_crash(self) -> None:
        photo = Path(self.temp_dir.name) / "student.jpg"
        photo.write_bytes(b"test portrait")
        student_id = database.add_student("2410471", "Log Student", "DIT", photo)

        log_id = database.add_verification_log(
            student_id=student_id,
            result="NOT VERIFIED",
            score=0.9,
            backend="test",
            captured_image_path=None,
            match_threshold=0.45,
        )

        self.assertGreater(log_id, 0)
        integrity = database.audit_log_integrity()
        self.assertEqual(integrity["status"], "SECURE")
        self.assertEqual(integrity["tampered"], 0)

    def test_local_email_otp_expiry_and_verification_state(self) -> None:
        user = database.verify_password_for_email_otp("admin", "Admin@12345")
        self.assertIsNotNone(user)

        database.store_pending_email_otp("admin", "123456")
        self.assertIsNone(database.verify_email_otp("admin", "000000"))
        verified = database.verify_email_otp("admin", "123456")
        self.assertIsNotNone(verified)
        self.assertIsNone(database.verify_email_otp("admin", "123456"))

    def test_database_mode_names_are_explicit(self) -> None:
        self.assertEqual(
            Settings(database_url="postgresql://example/db").database_mode,
            "neon-postgresql",
        )
        self.assertEqual(
            Settings(database_url="postgresql+psycopg://example/db").database_mode,
            "neon-postgresql",
        )
        self.assertEqual(
            Settings(database_url="sqlite:///example.db").database_mode,
            "sqlite-fallback",
        )


if __name__ == "__main__":
    unittest.main()
