import sqlite3
import base64
from contextlib import closing
from datetime import datetime
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import struct
import time
from typing import Any

import bcrypt

from .config import DB_PATH, ROOT_DIR, ensure_directories

IDENTIFIER_PEPPER = "ExamVerify-Local-Identifier-Pepper-v2"
DEFAULT_2FA_SECRETS = {
    "admin": "JBSWY3DPEHPK3PXP",
    "invigilator": "JBSWY3DPEHPK3PXQ",
    "viewer": "JBSWY3DPEHPK3PXR",
}
DEFAULT_ADMIN_EMAIL = os.getenv("EXAMVERIFY_ADMIN_EMAIL") or os.getenv("EXAMVERIFY_SMTP_USER") or "admin@examverify.local"
OTP_EXPIRY_SECONDS = 5 * 60
LOCKOUT_FAILURES = 5
LOCKOUT_SECONDS = 15 * 60


def get_connection() -> sqlite3.Connection:
    ensure_directories()
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def _resolve_moved_project_path(value: str | None) -> str | None:
    if not value:
        return value

    path = Path(value)
    if path.exists():
        return str(path)

    parts = path.parts
    if "Data" not in parts:
        return value

    data_index = parts.index("Data")
    relocated_path = ROOT_DIR.joinpath(*parts[data_index:])
    if relocated_path.exists():
        return str(relocated_path)
    return value


def _student_record(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    record = dict(row)
    record["photo_path"] = _resolve_moved_project_path(record.get("photo_path"))
    return record


def init_db() -> None:
    with closing(get_connection()) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS students (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_number TEXT NOT NULL UNIQUE,
                full_name TEXT NOT NULL,
                program TEXT,
                photo_path TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS verification_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                result TEXT NOT NULL,
                score REAL,
                backend TEXT NOT NULL,
                captured_image_path TEXT,
                verified_at TEXT NOT NULL,
                FOREIGN KEY (student_id) REFERENCES students(id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                full_name TEXT NOT NULL,
                email TEXT,
                role TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                password_scheme TEXT,
                active INTEGER NOT NULL DEFAULT 1,
                failed_attempts INTEGER NOT NULL DEFAULT 0,
                locked_until TEXT,
                pending_otp_hash TEXT,
                pending_otp_expires_at TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                username TEXT,
                actor TEXT,
                details TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS exam_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                course_code TEXT NOT NULL,
                course_name TEXT NOT NULL,
                program TEXT,
                level TEXT,
                exam_date TEXT,
                start_time TEXT,
                end_time TEXT,
                venue TEXT,
                status TEXT NOT NULL DEFAULT 'scheduled',
                created_by TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS exam_session_students (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                exam_session_id INTEGER NOT NULL,
                student_id INTEGER NOT NULL,
                eligibility_type TEXT NOT NULL DEFAULT 'regular',
                eligibility_status TEXT NOT NULL DEFAULT 'eligible',
                attendance_status TEXT NOT NULL DEFAULT 'not_verified',
                verified_at TEXT,
                verified_by TEXT,
                verified_device_id TEXT,
                notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT,
                UNIQUE(exam_session_id, student_id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS exam_import_audits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                exam_session_id INTEGER NOT NULL,
                imported_by TEXT,
                filename TEXT,
                total_rows INTEGER NOT NULL DEFAULT 0,
                linked_count INTEGER NOT NULL DEFAULT 0,
                unmatched_count INTEGER NOT NULL DEFAULT 0,
                no_face_count INTEGER NOT NULL DEFAULT 0,
                duplicate_count INTEGER NOT NULL DEFAULT 0,
                invalid_count INTEGER NOT NULL DEFAULT 0,
                review_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS exam_session_invigilators (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                exam_session_id INTEGER NOT NULL,
                invigilator_username TEXT NOT NULL,
                assigned_by TEXT,
                assigned_at TEXT NOT NULL,
                role_in_session TEXT NOT NULL DEFAULT 'support',
                UNIQUE(exam_session_id, invigilator_username)
            )
            """
        )
        _ensure_student_columns(connection)
        _ensure_log_columns(connection)
        _ensure_user_columns(connection)
        _ensure_exam_session_columns(connection)
        _seed_default_users(connection)
        _backfill_student_hashes(connection)
        connection.commit()


def _ensure_student_columns(connection: sqlite3.Connection) -> None:
    existing_columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(students)").fetchall()
    }
    migrations = {
        "active": "ALTER TABLE students ADD COLUMN active INTEGER NOT NULL DEFAULT 1",
        "updated_at": "ALTER TABLE students ADD COLUMN updated_at TEXT",
        "face_embedding": "ALTER TABLE students ADD COLUMN face_embedding TEXT",
        "embedding_backend": "ALTER TABLE students ADD COLUMN embedding_backend TEXT",
        "exam_eligible": "ALTER TABLE students ADD COLUMN exam_eligible INTEGER NOT NULL DEFAULT 1",
        "eligibility_note": "ALTER TABLE students ADD COLUMN eligibility_note TEXT",
        "student_number_hash": "ALTER TABLE students ADD COLUMN student_number_hash TEXT",
        "level": "ALTER TABLE students ADD COLUMN level TEXT",
        "student_status": "ALTER TABLE students ADD COLUMN student_status TEXT NOT NULL DEFAULT 'active'",
    }
    for column_name, statement in migrations.items():
        if column_name not in existing_columns:
            connection.execute(statement)


def _ensure_log_columns(connection: sqlite3.Connection) -> None:
    existing_columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(verification_logs)").fetchall()
    }
    migrations = {
        "expected_result": "ALTER TABLE verification_logs ADD COLUMN expected_result TEXT",
        "duration_ms": "ALTER TABLE verification_logs ADD COLUMN duration_ms REAL",
        "match_threshold": "ALTER TABLE verification_logs ADD COLUMN match_threshold REAL",
        "previous_log_hash": "ALTER TABLE verification_logs ADD COLUMN previous_log_hash TEXT",
        "log_hash": "ALTER TABLE verification_logs ADD COLUMN log_hash TEXT",
        "student_number_hash": "ALTER TABLE verification_logs ADD COLUMN student_number_hash TEXT",
    }
    for column_name, statement in migrations.items():
        if column_name not in existing_columns:
            connection.execute(statement)


def _ensure_user_columns(connection: sqlite3.Connection) -> None:
    existing_columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(users)").fetchall()
    }
    migrations = {
        "two_factor_secret": "ALTER TABLE users ADD COLUMN two_factor_secret TEXT",
        "email": "ALTER TABLE users ADD COLUMN email TEXT",
        "password_scheme": "ALTER TABLE users ADD COLUMN password_scheme TEXT",
        "failed_attempts": "ALTER TABLE users ADD COLUMN failed_attempts INTEGER NOT NULL DEFAULT 0",
        "locked_until": "ALTER TABLE users ADD COLUMN locked_until TEXT",
        "pending_otp_hash": "ALTER TABLE users ADD COLUMN pending_otp_hash TEXT",
        "pending_otp_expires_at": "ALTER TABLE users ADD COLUMN pending_otp_expires_at TEXT",
    }
    for column_name, statement in migrations.items():
        if column_name not in existing_columns:
            connection.execute(statement)


def _ensure_exam_session_columns(connection: sqlite3.Connection) -> None:
    existing_columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(exam_session_students)").fetchall()
    }
    if "verified_device_id" not in existing_columns:
        connection.execute(
            "ALTER TABLE exam_session_students ADD COLUMN verified_device_id TEXT"
        )


def _hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        120_000,
    ).hex()


def _bcrypt_hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def _bcrypt_verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def _hash_otp(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def _seed_default_users(connection: sqlite3.Connection) -> None:
    users = [
        ("admin", "System Administrator", DEFAULT_ADMIN_EMAIL, "Super Admin", "Admin@12345"),
        ("invigilator", "Exam Invigilator", "invigilator@examverify.local", "Admin", "Verify@12345"),
        ("viewer", "Audit Viewer", "viewer@examverify.local", "Viewer", "View@12345"),
    ]
    existing = {
        row["username"]
        for row in connection.execute("SELECT username FROM users").fetchall()
    }
    now = datetime.now().isoformat(timespec="seconds")
    for username, full_name, email, role, password in users:
        if username in existing:
            continue
        salt = secrets.token_hex(16)
        connection.execute(
            """
            INSERT INTO users (
                username, full_name, email, role, password_hash, salt,
                password_scheme, two_factor_secret, active, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, 'bcrypt', ?, 1, ?)
            """,
            (
                username,
                full_name,
                email,
                role,
                _bcrypt_hash_password(password),
                salt,
                DEFAULT_2FA_SECRETS[username],
                now,
            ),
        )
    for username, secret in DEFAULT_2FA_SECRETS.items():
        connection.execute(
            """
            UPDATE users
            SET two_factor_secret = COALESCE(two_factor_secret, ?)
            WHERE username = ?
            """,
            (secret, username),
        )
    for username, _, email, role, password in users:
        row = connection.execute(
            "SELECT password_hash, password_scheme, email FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        if row and row["password_scheme"] != "bcrypt":
            connection.execute(
                """
                UPDATE users
                SET password_hash = ?, password_scheme = 'bcrypt', email = COALESCE(email, ?), role = ?
                WHERE username = ?
                """,
                (_bcrypt_hash_password(password), email, role, username),
            )
        if row and (not row["email"] or str(row["email"]).endswith(".local")):
            connection.execute(
                "UPDATE users SET email = ? WHERE username = ?",
                (email, username),
            )


def start_login(username: str, password: str, otp_code: str) -> dict[str, Any] | None:
    return authenticate_user(username, password, otp_code)


def verify_password_for_email_otp(username: str, password: str) -> dict[str, Any] | None:
    with closing(get_connection()) as connection:
        row = connection.execute(
            """
            SELECT
                id, username, full_name, role, password_hash, salt,
                password_scheme, email, active, failed_attempts, locked_until
            FROM users
            WHERE username = ?
            """,
            (username.strip().lower(),),
        ).fetchone()
        if row is None or not row["active"] or _is_locked(row["locked_until"]):
            log_audit_event("LOGIN_BLOCKED", username=username, details="Inactive, missing, or locked account")
            return None
        valid = _bcrypt_verify_password(password, row["password_hash"])
        if not valid and row["password_scheme"] != "bcrypt":
            supplied_hash = _hash_password(password, row["salt"])
            valid = hmac.compare_digest(supplied_hash, row["password_hash"])
        if not valid:
            _record_failed_login(connection, row)
            connection.commit()
            log_audit_event("LOGIN_FAILED", username=row["username"], details="Invalid password")
            return None
        connection.execute(
            """
            UPDATE users
            SET failed_attempts = 0, locked_until = NULL
            WHERE id = ?
            """,
            (row["id"],),
        )
        connection.commit()
    return {
        "id": int(row["id"]),
        "username": row["username"],
        "full_name": row["full_name"],
        "email": row["email"] or "",
        "role": row["role"],
    }


def authenticate_user(username: str, password: str, otp_code: str) -> dict[str, Any] | None:
    user = verify_password_for_email_otp(username, password)
    if user is None:
        return None
    with closing(get_connection()) as connection:
        row = connection.execute(
            """
            SELECT two_factor_secret
            FROM users
            WHERE username = ?
            """,
            (username.strip().lower(),),
        ).fetchone()
    if row is None or not verify_totp(row["two_factor_secret"], otp_code):
        log_audit_event("LOGIN_FAILED", username=username, details="Invalid authenticator code")
        return None
    log_audit_event("LOGIN_SUCCESS", username=username, details="TOTP login")
    return user


def store_pending_email_otp(username: str, code: str) -> None:
    expires_at = datetime.fromtimestamp(time.time() + OTP_EXPIRY_SECONDS).isoformat(timespec="seconds")
    with closing(get_connection()) as connection:
        connection.execute(
            """
            UPDATE users
            SET pending_otp_hash = ?, pending_otp_expires_at = ?
            WHERE username = ?
            """,
            (_hash_otp(code), expires_at, username.strip().lower()),
        )
        connection.commit()
    log_audit_event("EMAIL_OTP_SENT", username=username, details="Email OTP generated")


def verify_email_otp(username: str, code: str) -> dict[str, Any] | None:
    with closing(get_connection()) as connection:
        row = connection.execute(
            """
            SELECT id, username, full_name, email, role, pending_otp_hash, pending_otp_expires_at
            FROM users
            WHERE username = ?
            """,
            (username.strip().lower(),),
        ).fetchone()
        if row is None or not row["pending_otp_hash"] or not row["pending_otp_expires_at"]:
            return None
        if datetime.fromisoformat(row["pending_otp_expires_at"]) < datetime.now():
            log_audit_event("LOGIN_FAILED", username=username, details="Expired email OTP")
            return None
        if not hmac.compare_digest(_hash_otp(code), row["pending_otp_hash"]):
            log_audit_event("LOGIN_FAILED", username=username, details="Invalid email OTP")
            return None
        connection.execute(
            """
            UPDATE users
            SET pending_otp_hash = NULL, pending_otp_expires_at = NULL, failed_attempts = 0, locked_until = NULL
            WHERE id = ?
            """,
            (row["id"],),
        )
        connection.commit()
    log_audit_event("LOGIN_SUCCESS", username=username, details="Email OTP login")
    return {
        "id": int(row["id"]),
        "username": row["username"],
        "full_name": row["full_name"],
        "email": row["email"] or "",
        "role": row["role"],
    }


def _is_locked(locked_until: str | None) -> bool:
    if not locked_until:
        return False
    try:
        return datetime.fromisoformat(locked_until) > datetime.now()
    except ValueError:
        return False


def _record_failed_login(connection: sqlite3.Connection, row: sqlite3.Row) -> None:
    attempts = int(row["failed_attempts"] or 0) + 1
    locked_until = None
    if attempts >= LOCKOUT_FAILURES:
        locked_until = datetime.fromtimestamp(time.time() + LOCKOUT_SECONDS).isoformat(timespec="seconds")
    connection.execute(
        """
        UPDATE users
        SET failed_attempts = ?, locked_until = ?
        WHERE id = ?
        """,
        (attempts, locked_until, row["id"]),
    )


def log_audit_event(
    event_type: str,
    username: str | None = None,
    actor: str | None = None,
    details: str = "",
) -> None:
    with closing(get_connection()) as connection:
        connection.execute(
            """
            INSERT INTO audit_events (event_type, username, actor, details, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                event_type,
                username.strip().lower() if username else None,
                actor,
                details,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        connection.commit()


def list_audit_events(limit: int = 200) -> list[dict[str, Any]]:
    with closing(get_connection()) as connection:
        rows = connection.execute(
            """
            SELECT event_type, username, actor, details, created_at
            FROM audit_events
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def hash_student_identifier(student_number: str) -> str:
    normalized = student_number.strip().upper()
    payload = f"{IDENTIFIER_PEPPER}|{normalized}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def mask_student_identifier(student_number: str) -> str:
    cleaned = student_number.strip()
    if len(cleaned) <= 4:
        return "*" * len(cleaned)
    return f"{cleaned[:2]}{'*' * max(2, len(cleaned) - 4)}{cleaned[-2:]}"


def _backfill_student_hashes(connection: sqlite3.Connection) -> None:
    rows = connection.execute(
        """
        SELECT id, student_number
        FROM students
        WHERE student_number_hash IS NULL OR student_number_hash = ''
        """
    ).fetchall()
    for row in rows:
        connection.execute(
            "UPDATE students SET student_number_hash = ? WHERE id = ?",
            (hash_student_identifier(row["student_number"]), row["id"]),
        )


def generate_totp(secret: str, for_time: int | None = None, interval: int = 30) -> str:
    timestamp = int(time.time() if for_time is None else for_time)
    counter = timestamp // interval
    key = base64.b32decode(secret.upper(), casefold=True)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return f"{code % 1_000_000:06d}"


def verify_totp(secret: str | None, otp_code: str, window: int = 1) -> bool:
    if not secret:
        return False
    cleaned_code = "".join(char for char in otp_code.strip() if char.isdigit())
    if len(cleaned_code) != 6:
        return False
    now = int(time.time())
    for step in range(-window, window + 1):
        expected = generate_totp(secret, now + (step * 30))
        if hmac.compare_digest(expected, cleaned_code):
            return True
    return False


def two_factor_setup_hint(username: str) -> dict[str, str] | None:
    normalized = username.strip().lower()
    secret = DEFAULT_2FA_SECRETS.get(normalized)
    if not secret:
        return None
    return {
        "secret": secret,
        "current_code": generate_totp(secret),
    }


def _log_hash_payload(
    student_id: int,
    result: str,
    score: float | None,
    backend: str,
    captured_image_path: str | None,
    expected_result: str | None,
    duration_ms: float | None,
    match_threshold: float | None,
    verified_at: str,
    previous_log_hash: str,
) -> str:
    fields = [
        str(student_id),
        result,
        "" if score is None else f"{float(score):.8f}",
        backend,
        captured_image_path or "",
        expected_result or "",
        "" if duration_ms is None else f"{float(duration_ms):.4f}",
        "" if match_threshold is None else f"{float(match_threshold):.4f}",
        verified_at,
        previous_log_hash,
    ]
    return "|".join(fields)


def _compute_log_hash(
    student_id: int,
    result: str,
    score: float | None,
    backend: str,
    captured_image_path: str | None,
    expected_result: str | None,
    duration_ms: float | None,
    match_threshold: float | None,
    verified_at: str,
    previous_log_hash: str,
) -> str:
    payload = _log_hash_payload(
        student_id,
        result,
        score,
        backend,
        captured_image_path,
        expected_result,
        duration_ms,
        match_threshold,
        verified_at,
        previous_log_hash,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def add_student(
    student_number: str,
    full_name: str,
    program: str,
    photo_path: Path,
    face_embedding: str | None = None,
    embedding_backend: str | None = None,
    exam_eligible: bool = True,
    eligibility_note: str = "",
) -> int:
    with closing(get_connection()) as connection:
        cursor = connection.execute(
            """
            INSERT INTO students (
                student_number, full_name, program, photo_path,
                student_number_hash, face_embedding, embedding_backend, exam_eligible,
                eligibility_note, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                student_number.strip(),
                full_name.strip(),
                program.strip(),
                str(photo_path),
                hash_student_identifier(student_number),
                face_embedding,
                embedding_backend,
                1 if exam_eligible else 0,
                eligibility_note.strip(),
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        connection.commit()
        log_id = int(cursor.lastrowid)
    log_audit_event(
        "VERIFICATION_EVENT",
        details=f"student_id={student_id}; result={result}; backend={backend}",
    )
    return log_id


def update_student_photo(
    student_id: int,
    photo_path: Path,
    face_embedding: str | None = None,
    embedding_backend: str | None = None,
) -> None:
    with closing(get_connection()) as connection:
        connection.execute(
            """
            UPDATE students
            SET photo_path = ?, face_embedding = ?, embedding_backend = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                str(photo_path),
                face_embedding,
                embedding_backend,
                datetime.now().isoformat(timespec="seconds"),
                student_id,
            ),
        )
        connection.commit()


def update_student_details(
    student_id: int,
    student_number: str,
    full_name: str,
    program: str,
    exam_eligible: bool,
    eligibility_note: str,
) -> None:
    with closing(get_connection()) as connection:
        connection.execute(
            """
            UPDATE students
            SET
                student_number = ?,
                student_number_hash = ?,
                full_name = ?,
                program = ?,
                exam_eligible = ?,
                eligibility_note = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                student_number.strip(),
                hash_student_identifier(student_number),
                full_name.strip(),
                program.strip(),
                1 if exam_eligible else 0,
                eligibility_note.strip(),
                datetime.now().isoformat(timespec="seconds"),
                student_id,
            ),
        )
        connection.commit()


def set_student_active(student_id: int, active: bool) -> None:
    with closing(get_connection()) as connection:
        connection.execute(
            """
            UPDATE students
            SET active = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                1 if active else 0,
                datetime.now().isoformat(timespec="seconds"),
                student_id,
            ),
        )
        connection.commit()


def list_students(active_only: bool = True) -> list[dict[str, Any]]:
    active_filter = "WHERE active = 1" if active_only else ""
    with closing(get_connection()) as connection:
        rows = connection.execute(
                f"""
                SELECT
                    id, student_number, student_number_hash, full_name, program, photo_path, created_at,
                    active, face_embedding, embedding_backend,
                    exam_eligible, eligibility_note
                FROM students
                {active_filter}
                ORDER BY full_name COLLATE NOCASE
                """
            ).fetchall()
        return [_student_record(row) for row in rows if row is not None]


def search_students(search_text: str = "", active_only: bool = True) -> list[dict[str, Any]]:
    query = f"%{search_text.strip()}%"
    active_filter = "AND active = 1" if active_only else ""
    with closing(get_connection()) as connection:
        rows = connection.execute(
                f"""
                SELECT
                    id, student_number, student_number_hash, full_name, program, photo_path, created_at,
                    active, face_embedding, embedding_backend,
                    exam_eligible, eligibility_note
                FROM students
                WHERE (student_number LIKE ? OR full_name LIKE ? OR program LIKE ?)
                {active_filter}
                ORDER BY full_name COLLATE NOCASE
                """,
                (query, query, query),
            ).fetchall()
        return [_student_record(row) for row in rows if row is not None]


def get_student(student_id: int) -> dict[str, Any] | None:
    with closing(get_connection()) as connection:
        row = connection.execute(
            """
            SELECT
                id, student_number, student_number_hash, full_name, program, photo_path, created_at,
                active, face_embedding, embedding_backend,
                exam_eligible, eligibility_note
            FROM students
            WHERE id = ?
            """,
            (student_id,),
        ).fetchone()
        return _student_record(row)


def get_student_by_number(student_number: str) -> dict[str, Any] | None:
    with closing(get_connection()) as connection:
        row = connection.execute(
            """
            SELECT
                id, student_number, student_number_hash, full_name, program, photo_path, created_at,
                active, face_embedding, embedding_backend,
                exam_eligible, eligibility_note
            FROM students
            WHERE student_number = ?
            """,
            (student_number.strip(),),
        ).fetchone()
        return _student_record(row)


def add_verification_log(
    student_id: int,
    result: str,
    score: float | None,
    backend: str,
    captured_image_path: Path | None,
    expected_result: str | None = None,
    duration_ms: float | None = None,
    match_threshold: float | None = None,
) -> int:
    with closing(get_connection()) as connection:
        verified_at = datetime.now().isoformat(timespec="seconds")
        captured_image = str(captured_image_path) if captured_image_path else None
        student_row = connection.execute(
            "SELECT student_number, student_number_hash FROM students WHERE id = ?",
            (student_id,),
        ).fetchone()
        student_number_hash = ""
        if student_row is not None:
            student_number_hash = student_row["student_number_hash"] or hash_student_identifier(
                student_row["student_number"]
            )
        previous_row = connection.execute(
            """
            SELECT log_hash
            FROM verification_logs
            WHERE log_hash IS NOT NULL
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
        previous_log_hash = previous_row["log_hash"] if previous_row else "GENESIS"
        log_hash = _compute_log_hash(
            student_id,
            result,
            score,
            backend,
            captured_image,
            expected_result,
            duration_ms,
            match_threshold,
            verified_at,
            previous_log_hash,
        )
        cursor = connection.execute(
            """
            INSERT INTO verification_logs (
                student_id, result, score, backend, captured_image_path,
                expected_result, duration_ms, match_threshold, student_number_hash,
                verified_at,
                previous_log_hash, log_hash
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                student_id,
                result,
                score,
                backend,
                captured_image,
                expected_result,
                duration_ms,
                match_threshold,
                student_number_hash,
                verified_at,
                previous_log_hash,
                log_hash,
            ),
        )
        connection.commit()
        return int(cursor.lastrowid)


def list_logs(limit: int = 100) -> list[dict[str, Any]]:
    with closing(get_connection()) as connection:
        rows = connection.execute(
            """
            SELECT
                verification_logs.id,
                students.student_number,
                students.full_name,
                verification_logs.result,
                verification_logs.score,
                verification_logs.backend,
                verification_logs.captured_image_path,
                verification_logs.expected_result,
                verification_logs.duration_ms,
                verification_logs.match_threshold,
                verification_logs.student_number_hash,
                verification_logs.verified_at,
                verification_logs.previous_log_hash,
                verification_logs.log_hash
            FROM verification_logs
            JOIN students ON students.id = verification_logs.student_id
            ORDER BY verification_logs.verified_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]


def audit_log_integrity() -> dict[str, Any]:
    with closing(get_connection()) as connection:
        rows = connection.execute(
            """
            SELECT
                id, student_id, result, score, backend, captured_image_path,
                expected_result, duration_ms, match_threshold, verified_at,
                previous_log_hash, log_hash
            FROM verification_logs
            ORDER BY id ASC
            """
        ).fetchall()

    checked = 0
    unsigned = 0
    tampered: list[int] = []
    previous_log_hash = "GENESIS"
    for row in rows:
        stored_hash = row["log_hash"]
        stored_previous = row["previous_log_hash"]
        if not stored_hash or not stored_previous:
            unsigned += 1
            continue
        checked += 1
        expected_hash = _compute_log_hash(
            int(row["student_id"]),
            row["result"],
            row["score"],
            row["backend"],
            row["captured_image_path"],
            row["expected_result"],
            row["duration_ms"],
            row["match_threshold"],
            row["verified_at"],
            previous_log_hash,
        )
        if stored_previous != previous_log_hash or stored_hash != expected_hash:
            tampered.append(int(row["id"]))
        previous_log_hash = stored_hash

    return {
        "total": len(rows),
        "checked": checked,
        "unsigned": unsigned,
        "tampered": len(tampered),
        "tampered_ids": tampered,
        "status": "SECURE" if not tampered else "ATTENTION",
    }


def clear_verification_logs() -> int:
    with closing(get_connection()) as connection:
        deleted = connection.execute("DELETE FROM verification_logs").rowcount
        connection.commit()
        return int(deleted)


def create_exam_session(
    course_code: str,
    course_name: str,
    program: str,
    level: str,
    exam_date: str,
    start_time: str,
    end_time: str,
    venue: str,
    created_by: str = "admin",
) -> int:
    now = datetime.now().isoformat(timespec="seconds")
    with closing(get_connection()) as connection:
        cursor = connection.execute(
            """
            INSERT INTO exam_sessions (
                course_code, course_name, program, level, exam_date, start_time, end_time, venue,
                status, created_by, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'scheduled', ?, ?, ?)
            """,
            (course_code, course_name, program, level, exam_date, start_time, end_time, venue, created_by, now, now),
        )
        connection.commit()
        return int(cursor.lastrowid)


def list_exam_sessions() -> list[dict[str, Any]]:
    with closing(get_connection()) as connection:
        rows = connection.execute(
            "SELECT * FROM exam_sessions ORDER BY exam_date DESC, course_code"
        ).fetchall()
        return [dict(row) for row in rows]


def active_exam_session() -> dict[str, Any] | None:
    with closing(get_connection()) as connection:
        row = connection.execute(
            "SELECT * FROM exam_sessions WHERE status = 'active' ORDER BY updated_at DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None


def active_exam_sessions(username: str | None = None) -> list[dict[str, Any]]:
    with closing(get_connection()) as connection:
        assignments_exist = connection.execute(
            "SELECT 1 FROM exam_session_invigilators LIMIT 1"
        ).fetchone()
        if username and assignments_exist:
            rows = connection.execute(
                """
                SELECT sessions.* FROM exam_sessions sessions
                JOIN exam_session_invigilators assignments
                  ON assignments.exam_session_id = sessions.id
                WHERE sessions.status = 'active'
                  AND assignments.invigilator_username = ?
                ORDER BY sessions.course_code
                """,
                (username,),
            ).fetchall()
        else:
            rows = connection.execute(
                "SELECT * FROM exam_sessions WHERE status = 'active' ORDER BY course_code"
            ).fetchall()
        return [dict(row) for row in rows]


def assign_exam_session_invigilator(
    session_id: int,
    username: str,
    assigned_by: str,
    role_in_session: str = "support",
) -> None:
    with closing(get_connection()) as connection:
        connection.execute(
            """
            INSERT INTO exam_session_invigilators (
                exam_session_id, invigilator_username, assigned_by, assigned_at, role_in_session
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(exam_session_id, invigilator_username) DO UPDATE SET
                role_in_session = excluded.role_in_session,
                assigned_by = excluded.assigned_by,
                assigned_at = excluded.assigned_at
            """,
            (
                session_id, username, assigned_by,
                datetime.now().isoformat(timespec="seconds"), role_in_session,
            ),
        )
        connection.commit()


def list_invigilator_users() -> list[dict[str, Any]]:
    with closing(get_connection()) as connection:
        rows = connection.execute(
            "SELECT username, full_name, role FROM users WHERE active = 1 AND lower(role) = 'invigilator'"
        ).fetchall()
        return [dict(row) for row in rows]


def set_exam_session_status(session_id: int, status: str) -> None:
    with closing(get_connection()) as connection:
        connection.execute(
            "UPDATE exam_sessions SET status = ?, updated_at = ? WHERE id = ?",
            (status, datetime.now().isoformat(timespec="seconds"), session_id),
        )
        connection.commit()


def add_exam_session_student(
    session_id: int,
    student_id: int,
    eligibility_type: str = "regular",
    eligibility_status: str = "eligible",
    notes: str = "",
) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    with closing(get_connection()) as connection:
        connection.execute(
            """
            INSERT INTO exam_session_students (
                exam_session_id, student_id, eligibility_type, eligibility_status,
                attendance_status, notes, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, 'not_verified', ?, ?, ?)
            ON CONFLICT(exam_session_id, student_id) DO UPDATE SET
                eligibility_type = excluded.eligibility_type,
                eligibility_status = excluded.eligibility_status,
                notes = excluded.notes,
                updated_at = excluded.updated_at
            """,
            (session_id, student_id, eligibility_type, eligibility_status, notes, now, now),
        )
        connection.commit()


def add_matching_exam_cohort(session_id: int) -> int:
    now = datetime.now().isoformat(timespec="seconds")
    with closing(get_connection()) as connection:
        session = connection.execute(
            "SELECT * FROM exam_sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if session is None:
            return 0
        students = connection.execute(
            """
            SELECT id FROM students
            WHERE active = 1
              AND face_embedding IS NOT NULL AND face_embedding != ''
              AND (? = '' OR lower(program) = lower(?))
              AND (? = '' OR lower(level) = lower(?))
            """,
            (
                session["program"] or "",
                session["program"] or "",
                session["level"] or "",
                session["level"] or "",
            ),
        ).fetchall()
        added = 0
        for student in students:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO exam_session_students (
                    exam_session_id, student_id, eligibility_type, eligibility_status,
                    attendance_status, notes, created_at, updated_at
                )
                VALUES (?, ?, 'regular', 'eligible', 'not_verified', ?, ?, ?)
                """,
                (
                    session_id,
                    student["id"],
                    "Added from matching program and level cohort.",
                    now,
                    now,
                ),
            )
            added += max(cursor.rowcount, 0)
        connection.commit()
        return added


def import_exam_eligibility_rows(
    session_id: int,
    rows: list[dict[str, Any]],
    filename: str,
    imported_by: str,
) -> dict[str, Any]:
    now = datetime.now().isoformat(timespec="seconds")
    review: list[dict[str, str]] = []
    counts = {
        "total_rows": len(rows),
        "linked_count": 0,
        "already_added_count": 0,
        "unmatched_count": 0,
        "no_face_count": 0,
        "duplicate_count": 0,
        "invalid_count": 0,
    }
    seen: set[str] = set()
    allowed_types = {"regular", "repeat", "deferred", "supplementary", "manual_override"}
    with closing(get_connection()) as connection:
        for raw in rows:
            number = str(raw.get("student_number") or "").strip().upper()
            full_name = str(raw.get("full_name") or "").strip()
            eligibility_type = str(raw.get("eligibility_type") or "regular").strip().lower()
            notes = str(raw.get("notes") or "").strip()
            result = {
                "student_number": number,
                "full_name": full_name,
                "issue": "",
                "suggested_action": "",
            }
            if not number:
                result.update(issue="Invalid student number", suggested_action="Correct student number")
                counts["invalid_count"] += 1
            elif number in seen:
                result.update(issue="Duplicate row", suggested_action="Ignore")
                counts["duplicate_count"] += 1
            elif eligibility_type not in allowed_types:
                result.update(issue="Invalid eligibility type", suggested_action="Correct eligibility type")
                counts["invalid_count"] += 1
            else:
                seen.add(number)
                student = connection.execute(
                    "SELECT * FROM students WHERE student_number_hash = ?",
                    (hash_student_identifier(number),),
                ).fetchone()
                if student is None:
                    result.update(
                        issue="Student not found in biometric database",
                        suggested_action="Register face first or correct student number",
                    )
                    counts["unmatched_count"] += 1
                elif not student["face_embedding"]:
                    result.update(
                        full_name=student["full_name"],
                        issue="Student exists but face not enrolled",
                        suggested_action="Register face first",
                    )
                    counts["no_face_count"] += 1
                elif connection.execute(
                    "SELECT id FROM exam_session_students WHERE exam_session_id = ? AND student_id = ?",
                    (session_id, student["id"]),
                ).fetchone():
                    result.update(
                        full_name=student["full_name"],
                        issue="Already linked to session",
                        suggested_action="Ignore",
                    )
                    counts["already_added_count"] += 1
                else:
                    connection.execute(
                        """
                        INSERT INTO exam_session_students (
                            exam_session_id, student_id, eligibility_type, eligibility_status,
                            attendance_status, notes, created_at, updated_at
                        ) VALUES (?, ?, ?, 'eligible', 'not_verified', ?, ?, ?)
                        """,
                        (session_id, student["id"], eligibility_type, notes or f"Imported from {filename}.", now, now),
                    )
                    counts["linked_count"] += 1
                    continue
            review.append(result)
        connection.execute(
            """
            INSERT INTO exam_import_audits (
                exam_session_id, imported_by, filename, total_rows, linked_count,
                unmatched_count, no_face_count, duplicate_count, invalid_count,
                review_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id, imported_by, filename, counts["total_rows"],
                counts["linked_count"], counts["unmatched_count"], counts["no_face_count"],
                counts["duplicate_count"], counts["invalid_count"], json.dumps(review), now,
            ),
        )
        connection.commit()
    return {**counts, "filename": filename, "review": review}


def list_exam_session_students(session_id: int) -> list[dict[str, Any]]:
    with closing(get_connection()) as connection:
        rows = connection.execute(
            """
            SELECT ess.*, students.student_number, students.full_name, students.program,
                   students.level, students.student_status,
                   CASE WHEN students.face_embedding IS NOT NULL AND students.face_embedding != ''
                        THEN 'face_enrolled' ELSE 'no_face' END AS biometric_status
            FROM exam_session_students ess
            JOIN students ON students.id = ess.student_id
            WHERE ess.exam_session_id = ?
            ORDER BY students.full_name COLLATE NOCASE
            """,
            (session_id,),
        ).fetchall()
        return [dict(row) for row in rows]


def set_exam_session_student_status(
    session_id: int, student_id: int, eligibility_status: str
) -> None:
    with closing(get_connection()) as connection:
        connection.execute(
            """
            UPDATE exam_session_students
            SET eligibility_status = ?, updated_at = ?
            WHERE exam_session_id = ? AND student_id = ?
            """,
            (
                eligibility_status,
                datetime.now().isoformat(timespec="seconds"),
                session_id,
                student_id,
            ),
        )
        connection.commit()


def remove_exam_session_student(session_id: int, student_id: int) -> None:
    with closing(get_connection()) as connection:
        connection.execute(
            "DELETE FROM exam_session_students WHERE exam_session_id = ? AND student_id = ?",
            (session_id, student_id),
        )
        connection.commit()


def evaluate_local_exam_entry(
    session_id: int | None,
    student_id: int | None,
    liveness_passed: bool,
    identity_matched: bool,
) -> dict[str, Any]:
    if session_id is None:
        return {"decision": "DENIED", "reason": "No active exam session selected."}
    if not liveness_passed:
        return {"decision": "DENIED", "reason": "Liveness failed."}
    if not identity_matched or student_id is None:
        return {"decision": "DENIED", "reason": "Face not recognized."}
    with closing(get_connection()) as connection:
        student = connection.execute(
            "SELECT active, student_status FROM students WHERE id = ?",
            (student_id,),
        ).fetchone()
        if student is None:
            return {"decision": "DENIED", "reason": "Face not recognized."}
        if int(student["active"]) != 1 or student["student_status"] != "active":
            return {"decision": "DENIED", "reason": "Student inactive or suspended."}
        eligibility = connection.execute(
            """
            SELECT * FROM exam_session_students
            WHERE exam_session_id = ? AND student_id = ?
            """,
            (session_id, student_id),
        ).fetchone()
        if eligibility is None:
            return {
                "decision": "DENIED",
                "reason": "Student is registered in the system but not eligible for this exam session.",
            }
        if eligibility["eligibility_status"] != "eligible":
            return {"decision": "DENIED", "reason": "Student blocked from this exam session."}
        if eligibility["attendance_status"] == "verified":
            return {
                "decision": "ALREADY_VERIFIED",
                "reason": f"Student was already verified at {eligibility['verified_at']}.",
            }
        updated = connection.execute(
            """
            UPDATE exam_session_students
            SET attendance_status = 'verified', verified_at = ?, verified_by = ?,
                verified_device_id = 'offline-local', updated_at = ?
            WHERE id = ? AND attendance_status != 'verified'
            """,
            (
                datetime.now().isoformat(timespec="seconds"),
                "offline-local",
                datetime.now().isoformat(timespec="seconds"),
                eligibility["id"],
            ),
        ).rowcount
        if not updated:
            current = connection.execute(
                "SELECT * FROM exam_session_students WHERE id = ?", (eligibility["id"],)
            ).fetchone()
            return {
                "decision": "ALREADY_VERIFIED",
                "reason": (
                    f"Student was already verified at {current['verified_at']} by "
                    f"{current['verified_by'] or 'another invigilator'}."
                ),
            }
        connection.commit()
        return {
            "decision": "VERIFIED",
            "reason": "Identity, liveness, and exam-session eligibility confirmed.",
            "eligibility_type": eligibility["eligibility_type"],
        }


def dashboard_summary() -> dict[str, int]:
    with closing(get_connection()) as connection:
        total_students = connection.execute(
            "SELECT COUNT(*) FROM students WHERE active = 1"
        ).fetchone()[0]
        total_attempts = connection.execute(
            "SELECT COUNT(*) FROM verification_logs"
        ).fetchone()[0]
        verified_attempts = connection.execute(
            "SELECT COUNT(*) FROM verification_logs WHERE result = 'VERIFIED'"
        ).fetchone()[0]
        failed_attempts = connection.execute(
            "SELECT COUNT(*) FROM verification_logs WHERE result = 'NOT VERIFIED'"
        ).fetchone()[0]
        error_attempts = connection.execute(
            "SELECT COUNT(*) FROM verification_logs WHERE result = 'ERROR'"
        ).fetchone()[0]

    return {
        "total_students": int(total_students),
        "total_attempts": int(total_attempts),
        "verified_attempts": int(verified_attempts),
        "failed_attempts": int(failed_attempts),
        "error_attempts": int(error_attempts),
    }


def evaluation_summary() -> dict[str, float | int]:
    with closing(get_connection()) as connection:
        rows = connection.execute(
            """
            SELECT result, score, expected_result, duration_ms, backend, match_threshold
            FROM verification_logs
            WHERE result IN ('VERIFIED', 'NOT VERIFIED')
            """
        ).fetchall()

    total_tests = len(rows)
    verified = sum(1 for row in rows if row["result"] == "VERIFIED")
    not_verified = sum(1 for row in rows if row["result"] == "NOT VERIFIED")
    scores = [float(row["score"]) for row in rows if row["score"] is not None]
    average_score = sum(scores) / len(scores) if scores else 0.0
    verification_rate = (verified / total_tests * 100) if total_tests else 0.0
    evaluated_rows = [row for row in rows if row["expected_result"]]
    correct = sum(
        1
        for row in evaluated_rows
        if (row["expected_result"] == "MATCH" and row["result"] == "VERIFIED")
        or (row["expected_result"] == "NO_MATCH" and row["result"] == "NOT VERIFIED")
    )
    false_accepts = sum(
        1
        for row in evaluated_rows
        if row["expected_result"] == "NO_MATCH" and row["result"] == "VERIFIED"
    )
    false_rejects = sum(
        1
        for row in evaluated_rows
        if row["expected_result"] == "MATCH" and row["result"] == "NOT VERIFIED"
    )
    durations = [
        float(row["duration_ms"]) for row in rows if row["duration_ms"] is not None
    ]
    average_duration_ms = sum(durations) / len(durations) if durations else 0.0
    accuracy = (correct / len(evaluated_rows) * 100) if evaluated_rows else 0.0
    opencv_match_scores = [
        float(row["score"])
        for row in evaluated_rows
        if row["backend"] == "OpenCV lightweight fallback"
        and row["expected_result"] == "MATCH"
        and row["score"] is not None
    ]
    opencv_no_match_scores = [
        float(row["score"])
        for row in evaluated_rows
        if row["backend"] == "OpenCV lightweight fallback"
        and row["expected_result"] == "NO_MATCH"
        and row["score"] is not None
    ]
    suggested_opencv_threshold = 0.0
    if opencv_match_scores and opencv_no_match_scores:
        suggested_opencv_threshold = (
            min(opencv_match_scores) + max(opencv_no_match_scores)
        ) / 2
    elif opencv_match_scores:
        suggested_opencv_threshold = min(opencv_match_scores)
    elif opencv_no_match_scores:
        suggested_opencv_threshold = max(opencv_no_match_scores) + 0.01

    return {
        "total_tests": total_tests,
        "verified": verified,
        "not_verified": not_verified,
        "average_score": average_score,
        "verification_rate": verification_rate,
        "evaluated_tests": len(evaluated_rows),
        "accuracy": accuracy,
        "false_accepts": false_accepts,
        "false_rejects": false_rejects,
        "average_duration_ms": average_duration_ms,
        "suggested_opencv_threshold": suggested_opencv_threshold,
    }
