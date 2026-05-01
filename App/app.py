from datetime import datetime
from pathlib import Path
import sys
from time import perf_counter

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import pandas as pd
import streamlit as st

from SRC.config import CAPTURE_DIR, PHOTO_DIR, ensure_directories
from SRC.config import FACE_MATCH_THRESHOLD, LIGHTWEIGHT_MATCH_THRESHOLD
from SRC.database import (
    add_student,
    add_verification_log,
    dashboard_summary,
    evaluation_summary,
    get_student_by_number,
    init_db,
    list_logs,
    list_students,
    search_students,
    update_student_photo,
)
from SRC.face_matcher import (
    FaceMatchError,
    save_camera_image,
    save_uploaded_image,
    verify_faces,
)


st.set_page_config(
    page_title="Exam Verification System",
    layout="wide",
)

ensure_directories()
init_db()


def safe_file_part(value: str) -> str:
    cleaned = "".join(char for char in value.strip() if char.isalnum() or char in ("-", "_"))
    return cleaned or "student"


def prepare_log_frame(logs: list[dict]) -> pd.DataFrame:
    frame = pd.DataFrame(logs)
    if "expected_result" in frame.columns:
        expected_labels = {
            "MATCH": "Same student",
            "NO_MATCH": "Different person",
        }
        frame["expected_outcome"] = (
            frame["expected_result"].map(expected_labels).fillna("Not evaluated")
        )
        frame["accuracy_result"] = frame.apply(log_accuracy_result, axis=1)
    if "duration_ms" in frame.columns:
        frame["response_time_s"] = frame["duration_ms"].apply(
            lambda value: "" if pd.isna(value) else f"{float(value) / 1000:.2f}"
        )
    if "match_threshold" in frame.columns:
        frame["threshold"] = frame["match_threshold"].apply(
            lambda value: "" if pd.isna(value) else f"{float(value):.2f}"
        )
    return frame


def log_accuracy_result(row: pd.Series) -> str:
    expected = row.get("expected_result")
    result = row.get("result")
    if expected == "MATCH" and result == "VERIFIED":
        return "Correct"
    if expected == "NO_MATCH" and result == "NOT VERIFIED":
        return "Correct"
    if expected == "NO_MATCH" and result == "VERIFIED":
        return "False accept"
    if expected == "MATCH" and result == "NOT VERIFIED":
        return "False reject"
    return "Not evaluated"


def dashboard_page() -> None:
    st.subheader("Dashboard")
    summary = dashboard_summary()

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Registered students", summary["total_students"])
    col2.metric("Verification attempts", summary["total_attempts"])
    col3.metric("Verified", summary["verified_attempts"])
    col4.metric("Not verified", summary["failed_attempts"])

    if summary["error_attempts"]:
        st.warning(f"{summary['error_attempts']} verification attempt(s) ended with an error.")

    recent_logs = list_logs(limit=5)
    if recent_logs:
        frame = prepare_log_frame(recent_logs)
        st.caption("Recent verification attempts")
        st.dataframe(
            frame[
                [
                    "verified_at",
                    "student_number",
                    "full_name",
                    "result",
                    "score",
                    "threshold",
                    "response_time_s",
                    "backend",
                ]
            ],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No verification attempts have been recorded yet.")


def register_student_page() -> None:
    st.subheader("Student Registration")

    with st.form("student_registration", clear_on_submit=True):
        left, right = st.columns([1, 1])
        with left:
            student_number = st.text_input("Student number")
            full_name = st.text_input("Full name")
            program = st.text_input("Program / class")
        with right:
            uploaded_photo = st.file_uploader(
                "Student ID/photo",
                type=["jpg", "jpeg", "png"],
                help="Use a clear front-facing photo for best verification results.",
            )

        submitted = st.form_submit_button("Register student", type="primary")

    if not submitted:
        return

    if not student_number.strip() or not full_name.strip() or uploaded_photo is None:
        st.error("Student number, full name, and photo are required.")
        return

    existing = get_student_by_number(student_number)
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    filename = f"{safe_file_part(student_number)}_{timestamp}.jpg"
    photo_path = PHOTO_DIR / filename

    try:
        save_uploaded_image(uploaded_photo, photo_path)
        if existing:
            update_student_photo(int(existing["id"]), photo_path)
            st.warning("This student number already existed, so the stored photo was updated.")
        else:
            add_student(student_number, full_name, program, photo_path)
            st.success("Student registered successfully.")
        st.image(str(photo_path), caption="Stored student photo", width=260)
    except Exception as exc:
        st.error(f"Could not register student: {exc}")


def verify_student_page() -> None:
    st.subheader("Exam Verification")

    students = list_students()
    if not students:
        st.info("Register at least one student before verification.")
        return

    options = {
        f"{row['student_number']} - {row['full_name']}": int(row["id"])
        for row in students
    }
    selected_label = st.selectbox("Select student", list(options.keys()))
    selected_student = next(
        row for row in students if int(row["id"]) == options[selected_label]
    )

    with st.expander("Matching settings"):
        backend_choice = st.radio(
            "Verification backend",
            ["Auto", "FaceNet only", "OpenCV fallback"],
            index=0,
            horizontal=True,
            help="Use FaceNet for better matching. Use OpenCV fallback if FaceNet is too slow on this laptop.",
        )
        lightweight_threshold = st.slider(
            "OpenCV fallback match threshold",
            min_value=-1.00,
            max_value=0.95,
            value=float(LIGHTWEIGHT_MATCH_THRESHOLD),
            step=0.01,
            help="Lower this if the same person is being rejected. Higher this if different people are being accepted.",
        )
        st.info(
            "If the backend says OpenCV fallback, matching is only for prototype testing. "
            "Install the optional FaceNet backend for better real face verification."
        )
        expected_choice = st.selectbox(
            "Expected outcome for evaluation",
            [
                "Same student should verify",
                "Different person should not verify",
                "Do not include in accuracy calculation",
            ],
            help="Use this during project testing so the evaluation page can calculate accuracy.",
        )

    left, right = st.columns([1, 1])
    with left:
        st.caption("Registered photo")
        st.image(selected_student["photo_path"], width=300)

    with right:
        st.caption("Live camera capture")
        camera_image = st.camera_input("Capture student's face")

    if camera_image is None:
        return

    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    capture_path = CAPTURE_DIR / f"{safe_file_part(selected_student['student_number'])}_{timestamp}.jpg"

    try:
        save_camera_image(camera_image, capture_path)
        start_time = perf_counter()
        backend_preference = {
            "Auto": "auto",
            "FaceNet only": "facenet",
            "OpenCV fallback": "opencv",
        }[backend_choice]
        result = verify_faces(
            Path(selected_student["photo_path"]),
            capture_path,
            lightweight_threshold=lightweight_threshold,
            backend_preference=backend_preference,
        )
        duration_ms = (perf_counter() - start_time) * 1000
        status = "VERIFIED" if result.is_match else "NOT VERIFIED"
        match_threshold = (
            FACE_MATCH_THRESHOLD
            if "FaceNet" in result.backend
            else lightweight_threshold
        )
        expected_result = {
            "Same student should verify": "MATCH",
            "Different person should not verify": "NO_MATCH",
            "Do not include in accuracy calculation": None,
        }[expected_choice]
        add_verification_log(
            student_id=int(selected_student["id"]),
            result=status,
            score=result.score,
            backend=result.backend,
            captured_image_path=capture_path,
            expected_result=expected_result,
            duration_ms=duration_ms,
            match_threshold=match_threshold,
        )

        if result.is_match:
            st.success(f"{status}: face matched.")
        else:
            st.error(f"{status}: face did not match.")

        metric_label = "Distance" if "FaceNet" in result.backend else "Similarity"
        score_col, time_col = st.columns(2)
        score_col.metric(metric_label, f"{result.score:.4f}")
        time_col.metric("Response time", f"{duration_ms / 1000:.2f}s")
        st.caption(f"Threshold used: {match_threshold:.2f}")
        st.caption(f"Backend: {result.backend}. {result.message}")
    except FaceMatchError as exc:
        add_verification_log(
            student_id=int(selected_student["id"]),
            result="ERROR",
            score=None,
            backend="Unavailable",
            captured_image_path=capture_path,
        )
        st.error(str(exc))
    except Exception as exc:
        st.error(f"Verification failed: {exc}")


def logs_page() -> None:
    st.subheader("Verification Logs")
    logs = list_logs()
    if not logs:
        st.info("No verification attempts have been recorded yet.")
        return

    frame = prepare_log_frame(logs)
    st.download_button(
        "Export logs as CSV",
        data=frame.to_csv(index=False).encode("utf-8"),
        file_name=f"verification_logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        mime="text/csv",
    )
    st.dataframe(
        frame[
            [
                "verified_at",
                "student_number",
                "full_name",
                "result",
                "score",
                "threshold",
                "expected_outcome",
                "accuracy_result",
                "response_time_s",
                "backend",
            ]
        ],
        use_container_width=True,
        hide_index=True,
    )


def students_page() -> None:
    st.subheader("Registered Students")
    search_text = st.text_input("Search by student number, name, or program")
    students = search_students(search_text)

    if not students:
        st.info("No students found.")
        return

    frame = pd.DataFrame([dict(row) for row in students])
    st.dataframe(
        frame[["student_number", "full_name", "program", "created_at"]],
        use_container_width=True,
        hide_index=True,
    )

    selected_label = st.selectbox(
        "Preview student photo",
        [f"{row['student_number']} - {row['full_name']}" for row in students],
    )
    selected_student = students[
        [f"{row['student_number']} - {row['full_name']}" for row in students].index(
            selected_label
        )
    ]
    st.image(selected_student["photo_path"], width=260)


def evaluation_page() -> None:
    st.subheader("System Evaluation")
    summary = evaluation_summary()

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Test cases", summary["total_tests"])
    col2.metric("Verified results", summary["verified"])
    col3.metric("Not verified results", summary["not_verified"])
    col4.metric("Verification rate", f"{summary['verification_rate']:.1f}%")

    metric1, metric2, metric3, metric4 = st.columns(4)
    metric1.metric("Evaluated cases", summary["evaluated_tests"])
    metric2.metric("Accuracy", f"{summary['accuracy']:.1f}%")
    metric3.metric("False accepts", summary["false_accepts"])
    metric4.metric("False rejects", summary["false_rejects"])

    score_col, duration_col = st.columns(2)
    score_col.metric("Average match score", f"{summary['average_score']:.4f}")
    duration_col.metric(
        "Average response time",
        f"{summary['average_duration_ms'] / 1000:.2f}s",
    )

    if summary["evaluated_tests"]:
        if summary["false_rejects"]:
            st.warning(
                "False rejects mean the system rejected a person who was expected to match. "
                "For OpenCV fallback tests, try lowering the fallback threshold and retesting "
                "with stronger lighting and a front-facing camera angle."
            )
        if summary["false_accepts"]:
            st.warning(
                "False accepts mean the system accepted a person who was expected not to match. "
                "For OpenCV fallback tests, raise the fallback threshold and retest."
            )
    if summary["suggested_opencv_threshold"]:
        st.info(
            "Suggested OpenCV threshold from evaluated fallback tests: "
            f"{summary['suggested_opencv_threshold']:.2f}. "
            "Treat this as a starting point, then retest."
        )

    st.write("Evaluation notes")
    st.text_area(
        "Notes for report",
        value=(
            "The system was evaluated using locally registered student photos and live "
            "webcam captures. Verification results were recorded in the system logs. "
            "Performance may vary depending on lighting, webcam quality, face angle, "
            "and the quality of the registered student photo."
        ),
        height=120,
    )

    export_frame = pd.DataFrame(
        [
            {
                "metric": "Total test cases",
                "value": summary["total_tests"],
            },
            {
                "metric": "Verified results",
                "value": summary["verified"],
            },
            {
                "metric": "Not verified results",
                "value": summary["not_verified"],
            },
            {
                "metric": "Verification rate",
                "value": f"{summary['verification_rate']:.1f}%",
            },
            {
                "metric": "Average match score",
                "value": f"{summary['average_score']:.4f}",
            },
            {
                "metric": "Evaluated test cases",
                "value": summary["evaluated_tests"],
            },
            {
                "metric": "Accuracy",
                "value": f"{summary['accuracy']:.1f}%",
            },
            {
                "metric": "False accepts",
                "value": summary["false_accepts"],
            },
            {
                "metric": "False rejects",
                "value": summary["false_rejects"],
            },
            {
                "metric": "Average response time",
                "value": f"{summary['average_duration_ms'] / 1000:.2f}s",
            },
            {
                "metric": "Suggested OpenCV threshold",
                "value": f"{summary['suggested_opencv_threshold']:.2f}",
            },
        ]
    )

    st.download_button(
        "Export evaluation summary",
        data=export_frame.to_csv(index=False).encode("utf-8"),
        file_name=f"evaluation_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        mime="text/csv",
    )

    logs = list_logs(limit=200)
    if logs:
        frame = prepare_log_frame(logs)
        st.caption("Evaluation source records")
        st.dataframe(
            frame[
                [
                    "verified_at",
                    "student_number",
                    "full_name",
                    "result",
                    "score",
                    "threshold",
                    "expected_outcome",
                    "accuracy_result",
                    "response_time_s",
                    "backend",
                ]
            ],
            use_container_width=True,
            hide_index=True,
        )


st.title("Automated Exam Verification System")
st.caption("Face-based student identity verification for exam entry.")

dashboard_tab, register_tab, verify_tab, students_tab, evaluation_tab, logs_tab = st.tabs(
    [
        "Dashboard",
        "Register Student",
        "Verify Student",
        "Students",
        "System Evaluation",
        "Verification Logs",
    ]
)

with dashboard_tab:
    dashboard_page()

with register_tab:
    register_student_page()

with verify_tab:
    verify_student_page()

with students_tab:
    students_page()

with evaluation_tab:
    evaluation_page()

with logs_tab:
    logs_page()
