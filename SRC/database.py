import sqlite3
import base64
from contextlib import closing
from datetime import datetime
import hashlib
import hmac
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
        _ensure_student_columns(connection)
        _ensure_log_columns(connection)
        _ensure_user_columns(connection)
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
