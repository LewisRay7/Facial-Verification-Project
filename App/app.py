from datetime import datetime
from pathlib import Path
import sys
from time import sleep
from time import perf_counter

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import cv2
import pandas as pd
import streamlit as st

from SRC.config import CAPTURE_DIR, PHOTO_DIR, ensure_directories
from SRC.config import FACE_MATCH_THRESHOLD, LIGHTWEIGHT_MATCH_THRESHOLD
from SRC.database import (
    add_student,
    add_verification_log,
    clear_verification_logs,
    dashboard_summary,
    evaluation_summary,
    get_student_by_number,
    init_db,
    list_logs,
    list_students,
    search_students,
    set_student_active,
    update_student_details,
    update_student_photo,
)
from SRC.face_matcher import (
    FaceMatchError,
    generate_face_embedding,
    identify_face_from_embeddings,
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


def apply_app_style() -> None:
    st.markdown(
        """
        <style>
            .stApp {
                background: #0b1120;
                color: #f8fafc;
            }

            [data-testid="stSidebar"] {
                background: #111827;
                border-right: 1px solid #334155;
            }

            [data-testid="stSidebar"] * {
                color: #f8fafc !important;
            }

            [data-testid="stSidebar"] label,
            [data-testid="stSidebar"] p,
            [data-testid="stSidebar"] span {
                font-weight: 650;
            }

            h1, h2, h3 {
                color: #f8fafc;
                letter-spacing: 0;
            }

            p, li, label, span, div {
                color: #e5e7eb;
            }

            div[data-testid="stMetric"] {
                background: #111827;
                border: 1px solid #334155;
                border-radius: 8px;
                padding: 16px 18px;
                box-shadow: 0 14px 30px rgba(0, 0, 0, 0.20);
            }

            div[data-testid="stMetric"] label,
            div[data-testid="stMetric"] [data-testid="stMetricValue"] {
                color: #f8fafc !important;
            }

            div[data-testid="stDataFrame"] {
                border: 1px solid #334155;
                border-radius: 8px;
                overflow: hidden;
            }

            .evs-hero {
                background: linear-gradient(135deg, #111827 0%, #172554 100%);
                border: 1px solid #2563eb;
                border-radius: 8px;
                padding: 20px 22px;
                margin-bottom: 18px;
                box-shadow: 0 18px 42px rgba(0, 0, 0, 0.28);
            }

            .evs-hero-title {
                font-size: 1.7rem;
                font-weight: 700;
                margin-bottom: 4px;
                color: #ffffff;
            }

            .evs-hero-subtitle {
                color: #cbd5e1;
                font-size: 0.98rem;
            }

            .evs-status {
                border-radius: 999px;
                display: inline-block;
                font-size: 0.9rem;
                font-weight: 800;
                letter-spacing: 0;
                padding: 8px 13px;
                text-transform: uppercase;
            }

            .evs-status-ok {
                background: #22c55e;
                color: #052e16;
                box-shadow: 0 0 0 1px rgba(34, 197, 94, 0.55), 0 0 18px rgba(34, 197, 94, 0.35);
            }

            .evs-status-blocked {
                background: #f97316;
                color: #431407;
                box-shadow: 0 0 0 1px rgba(249, 115, 22, 0.55), 0 0 18px rgba(249, 115, 22, 0.35);
            }

            .evs-status-unknown {
                background: #22d3ee;
                color: #083344;
                box-shadow: 0 0 0 1px rgba(34, 211, 238, 0.55), 0 0 18px rgba(34, 211, 238, 0.35);
            }

            .evs-status-low {
                background: #facc15;
                color: #422006;
                box-shadow: 0 0 0 1px rgba(250, 204, 21, 0.55), 0 0 18px rgba(250, 204, 21, 0.35);
            }

            .evs-panel {
                background: #111827;
                border: 1px solid #334155;
                border-radius: 8px;
                padding: 16px;
                margin-bottom: 16px;
                box-shadow: 0 14px 30px rgba(0, 0, 0, 0.20);
            }

            .stButton > button,
            .stDownloadButton > button,
            button[kind="primary"] {
                background: #06b6d4 !important;
                border: 1px solid #67e8f9 !important;
                border-radius: 8px !important;
                color: #082f49 !important;
                font-weight: 800 !important;
            }

            .stButton > button:hover,
            .stDownloadButton > button:hover {
                background: #22d3ee !important;
                border-color: #a5f3fc !important;
                color: #082f49 !important;
            }

            img {
                border: 1px solid #475569;
                border-radius: 8px;
                box-shadow: 0 14px 30px rgba(0, 0, 0, 0.28);
            }

            [data-testid="stAlert"] {
                border-radius: 8px;
                font-weight: 700;
            }

            input, textarea, select {
                color: #f8fafc !important;
            }

            .evs-result-card {
                background: #111827;
                border: 1px solid #38bdf8;
                border-radius: 8px;
                padding: 18px;
                margin-top: 14px;
                box-shadow: 0 18px 42px rgba(8, 47, 73, 0.35);
            }

            .evs-result-grid {
                display: grid;
                grid-template-columns: repeat(2, minmax(0, 1fr));
                gap: 12px;
            }

            .evs-result-label {
                color: #94a3b8;
                font-size: 0.78rem;
                font-weight: 800;
                text-transform: uppercase;
            }

            .evs-result-value {
                color: #ffffff;
                font-size: 1rem;
                font-weight: 800;
                margin-top: 2px;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


def page_header(title: str, subtitle: str) -> None:
    st.markdown(
        f"""
        <div class="evs-hero">
            <div class="evs-hero-title">{title}</div>
            <div class="evs-hero-subtitle">{subtitle}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def eligibility_badge(is_eligible: bool) -> str:
    if is_eligible:
        return '<span class="evs-status evs-status-ok">Eligible to write</span>'
    return '<span class="evs-status evs-status-blocked">Not eligible</span>'


def unknown_badge() -> str:
    return '<span class="evs-status evs-status-unknown">Unknown student</span>'


def low_confidence_badge() -> str:
    return '<span class="evs-status evs-status-low">Low confidence match</span>'


def safe_file_part(value: str) -> str:
    cleaned = "".join(char for char in value.strip() if char.isalnum() or char in ("-", "_"))
    return cleaned or "student"


def find_student_by_id(students: list[dict], student_id: int | None) -> dict | None:
    if student_id is None:
        return None
    return next((row for row in students if int(row["id"]) == student_id), None)


def ranked_distance_frame(students: list[dict], ranked_matches: list[tuple[int, float]]) -> pd.DataFrame:
    rows = []
    for student_id, distance in ranked_matches:
        student = find_student_by_id(students, student_id)
        if student is None:
            continue
        rows.append(
            {
                "student_number": student["student_number"],
                "full_name": student["full_name"],
                "distance": f"{distance:.4f}",
            }
        )
    return pd.DataFrame(rows)


def render_result_card(
    status: str,
    student: dict | None,
    distance: float,
    threshold: float,
    response_time_ms: float,
    suggested_threshold: float,
    second_best_score: float | None,
) -> None:
    name = student["full_name"] if student else "Unknown"
    student_number = student["student_number"] if student else "Not identified"
    confidence = max(0.0, min(100.0, (1 - (distance / max(threshold, 0.01))) * 100))
    second_best = f"{second_best_score:.4f}" if second_best_score is not None else "N/A"
    st.markdown(
        f"""
        <div class="evs-result-card">
            <div class="evs-result-grid">
                <div>
                    <div class="evs-result-label">Name</div>
                    <div class="evs-result-value">{name}</div>
                </div>
                <div>
                    <div class="evs-result-label">Student ID</div>
                    <div class="evs-result-value">{student_number}</div>
                </div>
                <div>
                    <div class="evs-result-label">Status</div>
                    <div class="evs-result-value">{status}</div>
                </div>
                <div>
                    <div class="evs-result-label">Confidence</div>
                    <div class="evs-result-value">{confidence:.1f}%</div>
                </div>
                <div>
                    <div class="evs-result-label">Best distance</div>
                    <div class="evs-result-value">{distance:.4f}</div>
                </div>
                <div>
                    <div class="evs-result-label">Second-best distance</div>
                    <div class="evs-result-value">{second_best}</div>
                </div>
                <div>
                    <div class="evs-result-label">Threshold used</div>
                    <div class="evs-result-value">{threshold:.2f}</div>
                </div>
                <div>
                    <div class="evs-result-label">Response time</div>
                    <div class="evs-result-value">{response_time_ms / 1000:.2f}s</div>
                </div>
                <div>
                    <div class="evs-result-label">Suggested threshold</div>
                    <div class="evs-result-value">{suggested_threshold:.2f}</div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def detect_largest_face_box(frame) -> tuple[int, int, int, int] | None:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    face_cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )
    faces = face_cascade.detectMultiScale(
        gray,
        scaleFactor=1.1,
        minNeighbors=5,
        minSize=(80, 80),
    )
    if len(faces) == 0:
        return None
    x, y, width, height = max(faces, key=lambda face: face[2] * face[3])
    return int(x), int(y), int(width), int(height)


def face_box_is_stable(
    previous_box: tuple[int, int, int, int] | None,
    current_box: tuple[int, int, int, int],
    max_shift: int = 35,
) -> bool:
    if previous_box is None:
        return False
    return all(abs(current - previous) <= max_shift for current, previous in zip(current_box, previous_box))


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


def create_embedding_for_photo(photo_path: Path) -> tuple[str | None, str | None]:
    embedding_result = generate_face_embedding(photo_path)
    if embedding_result is None:
        return None, None
    return embedding_result


def dashboard_page() -> None:
    page_header(
        "Operations Dashboard",
        "Monitor registrations, verification attempts, and recent exam-entry results.",
    )
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
    page_header(
        "Student Registration",
        "Enroll students, store their reference photo, and set exam eligibility.",
    )

    with st.form("student_registration", clear_on_submit=True):
        left, right = st.columns([1, 1])
        with left:
            student_number = st.text_input("Student number")
            full_name = st.text_input("Full name")
            program = st.text_input("Program / class")
            exam_eligible = st.checkbox("Eligible to write exam", value=True)
            eligibility_note = st.text_input(
                "Eligibility note",
                placeholder="Optional note, e.g. fees cleared or pending approval",
            )
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
        face_embedding, embedding_backend = create_embedding_for_photo(photo_path)
        if existing:
            update_student_photo(
                int(existing["id"]),
                photo_path,
                face_embedding=face_embedding,
                embedding_backend=embedding_backend,
            )
            st.warning("This student number already existed, so the stored photo was updated.")
        else:
            add_student(
                student_number,
                full_name,
                program,
                photo_path,
                face_embedding=face_embedding,
                embedding_backend=embedding_backend,
                exam_eligible=exam_eligible,
                eligibility_note=eligibility_note,
            )
            st.success("Student registered successfully.")
        if embedding_backend:
            st.info(f"Face embedding stored using {embedding_backend}.")
        else:
            st.info(
                "Face embedding was not stored because the optional FaceNet backend is not ready. "
                "The system will use the OpenCV fallback until FaceNet is installed."
            )
        st.image(str(photo_path), caption="Stored student photo", width=260)
    except Exception as exc:
        st.error(f"Could not register student: {exc}")


def verify_student_page() -> None:
    page_header(
        "Exam Verification",
        "Select a student, capture a live face, and approve or reject entry.",
    )

    search_text = st.text_input("Find student", placeholder="Search by student number, name, or program")
    students = search_students(search_text)
    if not students:
        st.info("No matching students found. Register the student or clear the search.")
        return

    options = {
        f"{row['student_number']} - {row['full_name']}": int(row["id"])
        for row in students
    }
    selected_label = st.selectbox("Select student", list(options.keys()))
    selected_student = next(
        row for row in students if int(row["id"]) == options[selected_label]
    )
    st.markdown(
        eligibility_badge(bool(selected_student["exam_eligible"])),
        unsafe_allow_html=True,
    )
    if selected_student["eligibility_note"]:
        st.caption(f"Eligibility note: {selected_student['eligibility_note']}")

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
        facenet_threshold = st.slider(
            "FaceNet distance threshold",
            min_value=0.10,
            max_value=0.80,
            value=float(FACE_MATCH_THRESHOLD),
            step=0.01,
            help="Higher accepts more same-student captures but can increase false accepts.",
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
        st.write(f"**Student number:** {selected_student['student_number']}")
        st.write(f"**Name:** {selected_student['full_name']}")
        st.write(f"**Program:** {selected_student['program'] or 'Not recorded'}")

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
            reference_embedding=selected_student["face_embedding"],
            facenet_threshold=facenet_threshold,
            lightweight_threshold=lightweight_threshold,
            backend_preference=backend_preference,
        )
        duration_ms = (perf_counter() - start_time) * 1000
        status = "VERIFIED" if result.is_match else "NOT VERIFIED"
        match_threshold = (
            facenet_threshold
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
            if selected_student["exam_eligible"]:
                st.success(f"{status}: face matched and student is eligible.")
            else:
                st.warning(
                    f"{status}: face matched, but this student is not eligible to write."
                )
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


def auto_identify_page() -> None:
    page_header(
        "Automatic Student Identification",
        "Capture a live face, find the closest registered student, and check exam eligibility.",
    )

    students = [dict(row) for row in list_students(active_only=True)]
    embedded_students = [row for row in students if row.get("face_embedding")]

    col1, col2, col3 = st.columns(3)
    col1.metric("Active students", len(students))
    col2.metric("Ready for auto scan", len(embedded_students))
    col3.metric("Missing embeddings", len(students) - len(embedded_students))

    if not students:
        st.info("No active students are registered yet.")
        return

    if not embedded_students:
        st.warning(
            "Automatic identification needs stored FaceNet embeddings. Open the Students "
            "page and generate embeddings for registered students first."
        )
        return

    with st.expander("Identification settings"):
        facenet_threshold = st.slider(
            "Maximum L2 face distance",
            min_value=0.10,
            max_value=1.40,
            value=0.60,
            step=0.01,
            help="The system returns Unknown when the closest normalized embedding distance is above this value.",
        )
        min_distance_gap = st.slider(
            "Minimum gap from next closest student",
            min_value=0.00,
            max_value=0.30,
            value=0.08,
            step=0.01,
            help="Raise this if similar faces are being confused. The best match must beat the second-best match by this amount.",
        )
        st.info(
            "This mode L2-normalizes FaceNet embeddings, calculates distances to all "
            "active students, and returns Unknown unless the closest distance is below "
            "the threshold and clearly better than the next closest student."
        )

    left, right = st.columns([1, 1])
    with left:
        st.caption("Live camera scan")
        camera_image = st.camera_input("Capture face for automatic identification")

    with right:
        st.caption("Identification result")
        st.info("Scanning face... Capture a clear front-facing image to begin.")

    if camera_image is None:
        return

    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    capture_path = CAPTURE_DIR / f"auto_identify_{timestamp}.jpg"

    try:
        save_camera_image(camera_image, capture_path)
        with st.spinner("Processing face embedding and comparing distances..."):
            start_time = perf_counter()
            result = identify_face_from_embeddings(
                capture_path,
                embedded_students,
                facenet_threshold=facenet_threshold,
                min_distance_gap=min_distance_gap,
            )
            duration_ms = (perf_counter() - start_time) * 1000

        matched_student = find_student_by_id(embedded_students, result.student_id)
        if result.status == "UNKNOWN":
            st.markdown(unknown_badge(), unsafe_allow_html=True)
            st.error(result.message)
            render_result_card(
                "Unknown",
                None,
                result.score,
                facenet_threshold,
                duration_ms,
                result.suggested_threshold,
                result.second_best_score,
            )
            distance_frame = ranked_distance_frame(embedded_students, result.ranked_matches)
            if not distance_frame.empty:
                st.caption("Closest stored student distances")
                st.dataframe(distance_frame, use_container_width=True, hide_index=True)
            return

        if matched_student is None:
            st.error("A matching result was returned, but the student record could not be loaded.")
            return

        log_status = "VERIFIED" if result.status == "VERIFIED" else "NOT VERIFIED"
        add_verification_log(
            student_id=int(matched_student["id"]),
            result=log_status,
            score=result.score,
            backend=result.backend,
            captured_image_path=capture_path,
            expected_result=None,
            duration_ms=duration_ms,
            match_threshold=facenet_threshold,
        )

        if result.status == "LOW_CONFIDENCE":
            st.markdown(low_confidence_badge(), unsafe_allow_html=True)
            st.warning(result.message)
        else:
            st.markdown(
                eligibility_badge(bool(matched_student["exam_eligible"])),
                unsafe_allow_html=True,
            )

        if result.status == "VERIFIED" and matched_student["exam_eligible"]:
            st.success("Student identified and approved for exam entry.")
        elif result.status == "VERIFIED":
            st.warning("Student identified, but they are not eligible to write this exam.")

        result_left, result_right = st.columns([1, 1])
        with result_left:
            st.image(matched_student["photo_path"], caption="Matched student photo", width=280)
        with result_right:
            st.write(f"**Student number:** {matched_student['student_number']}")
            st.write(f"**Name:** {matched_student['full_name']}")
            st.write(f"**Program:** {matched_student['program'] or 'Not recorded'}")
            if matched_student["eligibility_note"]:
                st.write(f"**Eligibility note:** {matched_student['eligibility_note']}")
            render_result_card(
                result.status.replace("_", " ").title(),
                matched_student,
                result.score,
                facenet_threshold,
                duration_ms,
                result.suggested_threshold,
                result.second_best_score,
            )
            distance_frame = ranked_distance_frame(embedded_students, result.ranked_matches)
            if not distance_frame.empty:
                st.caption("Closest stored student distances")
                st.dataframe(distance_frame, use_container_width=True, hide_index=True)
            st.caption(f"Required gap from next closest student: {min_distance_gap:.2f}")
            st.caption(f"Backend: {result.backend}. {result.message}")
    except FaceMatchError as exc:
        st.error(str(exc))
    except Exception as exc:
        st.error(f"Automatic identification failed: {exc}")


def face_unlock_scanner_page() -> None:
    page_header(
        "Real-Time Face Unlock Scanner",
        "Continuously scan the webcam, wait for a stable face, then identify the student automatically.",
    )

    students = [dict(row) for row in list_students(active_only=True)]
    embedded_students = [row for row in students if row.get("face_embedding")]

    col1, col2, col3 = st.columns(3)
    col1.metric("Active students", len(students))
    col2.metric("Ready for scanner", len(embedded_students))
    col3.metric("Cooldown", "2.5s")

    if not embedded_students:
        st.warning(
            "Real-time scanning needs active students with stored FaceNet embeddings. "
            "Generate embeddings from the Students page first."
        )
        return

    with st.expander("Scanner settings", expanded=True):
        threshold = st.slider(
            "Maximum L2 face distance",
            min_value=0.10,
            max_value=1.40,
            value=0.60,
            step=0.01,
        )
        min_gap = st.slider(
            "Minimum gap from next closest student",
            min_value=0.00,
            max_value=0.30,
            value=0.08,
            step=0.01,
        )
        stable_seconds = st.slider(
            "Face stability duration",
            min_value=0.5,
            max_value=2.0,
            value=0.8,
            step=0.1,
            help="Recognition starts only after the largest face stays steady for this long.",
        )
        cooldown_seconds = st.slider(
            "Recognition cooldown",
            min_value=1.0,
            max_value=5.0,
            value=2.5,
            step=0.5,
            help="After a recognition attempt, wait this long before trying again.",
        )
        scan_seconds = st.slider(
            "Scanner run time",
            min_value=10,
            max_value=120,
            value=45,
            step=5,
            help="Streamlit runs this scanner in a controlled session so the app stays responsive.",
        )

    start_scanner = st.button("Start automatic scanner", type="primary")
    status_slot = st.empty()
    frame_slot = st.empty()
    result_slot = st.empty()

    if not start_scanner:
        status_slot.info("Scanning face will begin when you start the automatic scanner.")
        return

    camera = cv2.VideoCapture(0)
    if not camera.isOpened():
        st.error("Could not open the webcam. Close other camera apps and try again.")
        return

    previous_box = None
    stable_start = None
    last_recognition_time = 0.0
    scanner_started = perf_counter()

    status_slot.info("Scanning face...")
    try:
        while perf_counter() - scanner_started < scan_seconds:
            ok, frame = camera.read()
            if not ok:
                status_slot.error("Could not read a webcam frame.")
                break

            frame = cv2.resize(frame, (640, 480))
            face_box = detect_largest_face_box(frame)
            now = perf_counter()

            if face_box is None:
                previous_box = None
                stable_start = None
                status_slot.info("Scanning face...")
            else:
                x, y, width, height = face_box
                cv2.rectangle(frame, (x, y), (x + width, y + height), (34, 211, 238), 2)
                if face_box_is_stable(previous_box, face_box):
                    if stable_start is None:
                        stable_start = now
                    stable_duration = now - stable_start
                    if stable_duration < stable_seconds:
                        status_slot.info("Hold still...")
                    elif now - last_recognition_time >= cooldown_seconds:
                        status_slot.info("Processing face recognition...")
                        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
                        capture_path = CAPTURE_DIR / f"face_unlock_{timestamp}.jpg"
                        cv2.imwrite(str(capture_path), frame)

                        start_time = perf_counter()
                        result = identify_face_from_embeddings(
                            capture_path,
                            embedded_students,
                            facenet_threshold=threshold,
                            min_distance_gap=min_gap,
                        )
                        duration_ms = (perf_counter() - start_time) * 1000
                        matched_student = find_student_by_id(
                            embedded_students,
                            result.student_id,
                        )
                        result_slot.empty()
                        with result_slot.container():
                            if result.status == "VERIFIED" and matched_student:
                                st.markdown(
                                    eligibility_badge(bool(matched_student["exam_eligible"])),
                                    unsafe_allow_html=True,
                                )
                                if matched_student["exam_eligible"]:
                                    st.success("Verified. Student identified and eligible.")
                                else:
                                    st.warning("Verified identity, but student is not eligible.")
                                render_result_card(
                                    "Verified",
                                    matched_student,
                                    result.score,
                                    threshold,
                                    duration_ms,
                                    result.suggested_threshold,
                                    result.second_best_score,
                                )
                            elif result.status == "LOW_CONFIDENCE" and matched_student:
                                st.markdown(low_confidence_badge(), unsafe_allow_html=True)
                                st.warning("Low confidence match. Manual review recommended.")
                                render_result_card(
                                    "Low Confidence",
                                    matched_student,
                                    result.score,
                                    threshold,
                                    duration_ms,
                                    result.suggested_threshold,
                                    result.second_best_score,
                                )
                            else:
                                st.markdown(unknown_badge(), unsafe_allow_html=True)
                                st.error("Unknown student.")
                                render_result_card(
                                    "Unknown",
                                    None,
                                    result.score,
                                    threshold,
                                    duration_ms,
                                    result.suggested_threshold,
                                    result.second_best_score,
                                )
                            distance_frame = ranked_distance_frame(
                                embedded_students,
                                result.ranked_matches,
                            )
                            if not distance_frame.empty:
                                st.caption("Closest stored student distances")
                                st.dataframe(
                                    distance_frame,
                                    use_container_width=True,
                                    hide_index=True,
                                )

                        if result.status == "VERIFIED" and matched_student:
                            add_verification_log(
                                student_id=int(matched_student["id"]),
                                result="VERIFIED",
                                score=result.score,
                                backend=result.backend,
                                captured_image_path=capture_path,
                                expected_result=None,
                                duration_ms=duration_ms,
                                match_threshold=threshold,
                            )
                        last_recognition_time = now
                        stable_start = None
                    else:
                        remaining = cooldown_seconds - (now - last_recognition_time)
                        status_slot.info(f"Cooldown active: {remaining:.1f}s")
                else:
                    stable_start = None
                    status_slot.info("Hold still...")
                previous_box = face_box

            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            frame_slot.image(frame_rgb, channels="RGB", use_column_width=True)
            sleep(0.08)
    finally:
        camera.release()
        status_slot.success("Scanner stopped.")


def logs_page() -> None:
    page_header(
        "Verification Logs",
        "Review captured attempts, outcomes, thresholds, and exported evidence.",
    )
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

    preview_options = {
        f"{row['verified_at']} | {row['student_number']} | {row['result']}": row
        for row in logs
        if row.get("captured_image_path")
    }
    if not preview_options:
        return

    selected_log_label = st.selectbox(
        "Preview captured verification image",
        list(preview_options.keys()),
    )
    selected_log = preview_options[selected_log_label]
    captured_path = Path(selected_log["captured_image_path"])
    if captured_path.exists():
        st.image(
            str(captured_path),
            caption=(
                f"{selected_log['student_number']} - {selected_log['full_name']} "
                f"({selected_log['result']})"
            ),
            width=300,
        )
    else:
        st.warning("The captured image file for this log entry is no longer available.")


def students_page() -> None:
    page_header(
        "Registered Students",
        "Maintain student details, photos, embeddings, status, and exam eligibility.",
    )
    show_inactive = st.checkbox("Show inactive students")
    search_text = st.text_input("Search by student number, name, or program")
    students = search_students(search_text, active_only=not show_inactive)

    if not students:
        st.info("No students found.")
        return

    frame = pd.DataFrame([dict(row) for row in students])
    frame["status"] = frame["active"].apply(lambda value: "Active" if value else "Inactive")
    frame["eligibility"] = frame["exam_eligible"].apply(
        lambda value: "Eligible" if value else "Not eligible"
    )
    st.dataframe(
        frame[
            [
                "student_number",
                "full_name",
                "program",
                "eligibility",
                "status",
                "created_at",
            ]
        ],
        use_container_width=True,
        hide_index=True,
    )

    selected_label = st.selectbox(
        "Manage student",
        [f"{row['student_number']} - {row['full_name']}" for row in students],
    )
    selected_student = students[
        [f"{row['student_number']} - {row['full_name']}" for row in students].index(
            selected_label
        )
    ]
    current_photo = Path(selected_student["photo_path"])

    left, right = st.columns([1, 1])
    with left:
        if current_photo.exists():
            st.image(str(current_photo), caption="Current student photo", width=260)
        else:
            st.warning("The stored photo file for this student is missing.")
        if selected_student["embedding_backend"]:
            st.info(f"Stored embedding: {selected_student['embedding_backend']}")
        else:
            st.warning("No stored face embedding yet. Generate one after installing FaceNet.")
        if st.button(
            "Generate / refresh face embedding",
            disabled=not current_photo.exists(),
            key=f"embedding_{selected_student['id']}",
        ):
            face_embedding, embedding_backend = create_embedding_for_photo(current_photo)
            if embedding_backend:
                update_student_photo(
                    int(selected_student["id"]),
                    current_photo,
                    face_embedding=face_embedding,
                    embedding_backend=embedding_backend,
                )
                st.success("Face embedding updated.")
                st.rerun()
            else:
                st.error(
                    "Could not create a FaceNet embedding. Install the optional FaceNet "
                    "backend, then try again with a clear front-facing photo."
                )

    with right:
        with st.form(f"manage_student_{selected_student['id']}"):
            updated_student_number = st.text_input(
                "Student number",
                value=selected_student["student_number"],
            )
            updated_full_name = st.text_input(
                "Full name",
                value=selected_student["full_name"],
            )
            updated_program = st.text_input(
                "Program / class",
                value=selected_student["program"] or "",
            )
            updated_exam_eligible = st.checkbox(
                "Eligible to write exam",
                value=bool(selected_student["exam_eligible"]),
            )
            updated_eligibility_note = st.text_input(
                "Eligibility note",
                value=selected_student["eligibility_note"] or "",
            )
            replacement_photo = st.file_uploader(
                "Replace student photo",
                type=["jpg", "jpeg", "png"],
                help="Leave empty if the current photo should stay unchanged.",
            )
            save_changes = st.form_submit_button("Save student changes", type="primary")

        if save_changes:
            if not updated_student_number.strip() or not updated_full_name.strip():
                st.error("Student number and full name are required.")
            else:
                try:
                    update_student_details(
                        int(selected_student["id"]),
                        updated_student_number,
                        updated_full_name,
                        updated_program,
                        updated_exam_eligible,
                        updated_eligibility_note,
                    )
                    if replacement_photo is not None:
                        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
                        filename = f"{safe_file_part(updated_student_number)}_{timestamp}.jpg"
                        photo_path = PHOTO_DIR / filename
                        save_uploaded_image(replacement_photo, photo_path)
                        face_embedding, embedding_backend = create_embedding_for_photo(photo_path)
                        update_student_photo(
                            int(selected_student["id"]),
                            photo_path,
                            face_embedding=face_embedding,
                            embedding_backend=embedding_backend,
                        )
                    st.success("Student record updated.")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Could not update student: {exc}")

        is_active = bool(selected_student["active"])
        if is_active:
            confirm_deactivate = st.checkbox(
                "I understand this student will be hidden from verification.",
                key=f"confirm_deactivate_{selected_student['id']}",
            )
            if st.button(
                "Deactivate student",
                disabled=not confirm_deactivate,
                key=f"deactivate_{selected_student['id']}",
            ):
                set_student_active(int(selected_student["id"]), False)
                st.success("Student deactivated. Existing logs were kept.")
                st.rerun()
        elif st.button("Reactivate student", key=f"reactivate_{selected_student['id']}"):
            set_student_active(int(selected_student["id"]), True)
            st.success("Student reactivated.")
            st.rerun()


def evaluation_page() -> None:
    page_header(
        "System Evaluation",
        "Measure accuracy, false accepts, false rejects, and response time.",
    )
    summary = evaluation_summary()

    with st.expander("Demo and testing guide", expanded=True):
        st.write(
            "Before the official test, run one practice verification to warm up FaceNet. "
            "The first attempt can take longer while the model loads; later attempts should "
            "be much faster."
        )
        st.markdown(
            """
            - Clear old verification logs before the final evaluation.
            - Use Auto or FaceNet only when the FaceNet backend is available.
            - Test the same number of same-student and different-person attempts.
            - Mark every real test with the correct expected outcome.
            - Aim for at least 10 same-student attempts and 10 different-person attempts.
            """
        )

    with st.expander("Start a fresh evaluation"):
        st.write(
            "Clear old verification attempts before a new test run. Student records and "
            "registered photos will stay saved."
        )
        confirm_clear = st.checkbox("I want to clear all verification logs")
        if st.button(
            "Clear verification logs",
            disabled=not confirm_clear,
            type="secondary",
        ):
            deleted_count = clear_verification_logs()
            st.success(f"Cleared {deleted_count} verification log(s).")
            st.rerun()

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


apply_app_style()
st.title("Automated Exam Verification System")
st.caption("Face-based student identity verification for exam entry.")

pages = {
    "Dashboard": dashboard_page,
    "Register Student": register_student_page,
    "Verify Student": verify_student_page,
    "Auto Identify": auto_identify_page,
    "Face Unlock Scanner": face_unlock_scanner_page,
    "Students": students_page,
    "System Evaluation": evaluation_page,
    "Verification Logs": logs_page,
}

selected_page = st.sidebar.radio("Navigation", list(pages.keys()))
pages[selected_page]()
