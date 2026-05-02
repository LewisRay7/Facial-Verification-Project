import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import DB_PATH, ensure_directories


def get_connection() -> sqlite3.Connection:
    ensure_directories()
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


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
        _ensure_student_columns(connection)
        _ensure_log_columns(connection)
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
    }
    for column_name, statement in migrations.items():
        if column_name not in existing_columns:
            connection.execute(statement)


def add_student(
    student_number: str,
    full_name: str,
    program: str,
    photo_path: Path,
    face_embedding: str | None = None,
    embedding_backend: str | None = None,
) -> int:
    with closing(get_connection()) as connection:
        cursor = connection.execute(
            """
            INSERT INTO students (
                student_number, full_name, program, photo_path,
                face_embedding, embedding_backend, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                student_number.strip(),
                full_name.strip(),
                program.strip(),
                str(photo_path),
                face_embedding,
                embedding_backend,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        connection.commit()
        return int(cursor.lastrowid)


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
) -> None:
    with closing(get_connection()) as connection:
        connection.execute(
            """
            UPDATE students
            SET student_number = ?, full_name = ?, program = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                student_number.strip(),
                full_name.strip(),
                program.strip(),
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


def list_students(active_only: bool = True) -> list[sqlite3.Row]:
    active_filter = "WHERE active = 1" if active_only else ""
    with closing(get_connection()) as connection:
        return list(
            connection.execute(
                f"""
                SELECT
                    id, student_number, full_name, program, photo_path, created_at,
                    active, face_embedding, embedding_backend
                FROM students
                {active_filter}
                ORDER BY full_name COLLATE NOCASE
                """
            )
        )


def search_students(search_text: str = "", active_only: bool = True) -> list[sqlite3.Row]:
    query = f"%{search_text.strip()}%"
    active_filter = "AND active = 1" if active_only else ""
    with closing(get_connection()) as connection:
        return list(
            connection.execute(
                f"""
                SELECT
                    id, student_number, full_name, program, photo_path, created_at,
                    active, face_embedding, embedding_backend
                FROM students
                WHERE (student_number LIKE ? OR full_name LIKE ? OR program LIKE ?)
                {active_filter}
                ORDER BY full_name COLLATE NOCASE
                """,
                (query, query, query),
            )
        )


def get_student(student_id: int) -> sqlite3.Row | None:
    with closing(get_connection()) as connection:
        return connection.execute(
            """
            SELECT
                id, student_number, full_name, program, photo_path, created_at,
                active, face_embedding, embedding_backend
            FROM students
            WHERE id = ?
            """,
            (student_id,),
        ).fetchone()


def get_student_by_number(student_number: str) -> sqlite3.Row | None:
    with closing(get_connection()) as connection:
        return connection.execute(
            """
            SELECT
                id, student_number, full_name, program, photo_path, created_at,
                active, face_embedding, embedding_backend
            FROM students
            WHERE student_number = ?
            """,
            (student_number.strip(),),
        ).fetchone()


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
        cursor = connection.execute(
            """
            INSERT INTO verification_logs (
                student_id, result, score, backend, captured_image_path,
                expected_result, duration_ms, match_threshold, verified_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                student_id,
                result,
                score,
                backend,
                str(captured_image_path) if captured_image_path else None,
                expected_result,
                duration_ms,
                match_threshold,
                datetime.now().isoformat(timespec="seconds"),
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
                verification_logs.verified_at
            FROM verification_logs
            JOIN students ON students.id = verification_logs.student_id
            ORDER BY verification_logs.verified_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]


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
