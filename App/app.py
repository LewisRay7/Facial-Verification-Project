from datetime import datetime
import base64
from html import escape
from pathlib import Path
import sys
from textwrap import dedent
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
    add_exam_session_student,
    active_exam_sessions,
    assign_exam_session_invigilator,
    add_matching_exam_cohort,
    add_verification_log,
    active_exam_session,
    audit_log_integrity,
    authenticate_user,
    clear_verification_logs,
    create_exam_session,
    dashboard_summary,
    evaluation_summary,
    get_student_by_number,
    import_exam_eligibility_rows,
    init_db,
    list_logs,
    list_audit_events,
    list_students,
    list_exam_sessions,
    list_exam_session_students,
    list_invigilator_users,
    log_audit_event,
    mask_student_identifier,
    remove_exam_session_student,
    search_students,
    set_student_active,
    set_exam_session_status,
    set_exam_session_student_status,
    evaluate_local_exam_entry,
    store_pending_email_otp,
    two_factor_setup_hint,
    verify_email_otp,
    verify_password_for_email_otp,
    update_student_details,
    update_student_photo,
)
from SRC.authentication import generate_email_otp, send_email_otp
from SRC.face_verification import run_static_liveness_check
from SRC.liveness import LivenessPipeline
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
    page_icon=str(ROOT_DIR / "Assets" / "examverify_logo_512.png"),
    layout="wide",
)

ensure_directories()
init_db()

SESSION_TIMEOUT_SECONDS = 10 * 60
ROLE_PAGES = {
    "Super Admin": {
        "Dashboard",
        "Register Student",
        "Verify Student",
        "Auto Identify",
        "Face Unlock Scanner",
        "Students",
        "Exam Sessions",
        "System Evaluation",
        "Verification Logs",
    },
    "Admin": {
        "Dashboard",
        "Register Student",
        "Verify Student",
        "Auto Identify",
        "Face Unlock Scanner",
        "Students",
        "Exam Sessions",
        "System Evaluation",
        "Verification Logs",
    },
    "Invigilator": {
        "Dashboard",
        "Verify Student",
        "Auto Identify",
        "Face Unlock Scanner",
        "Verification Logs",
    },
    "Viewer": {"Dashboard", "System Evaluation", "Verification Logs"},
}


def load_css(relative_path: str) -> None:
    css_path = Path(__file__).resolve().parent / relative_path
    try:
        css = css_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        st.warning(f"UI stylesheet not found: {css_path}")
        return
    render_html(f"<style>\n{css}\n</style>")


def render_html(markup: str) -> None:
    html = dedent(markup).strip()
    html = "\n".join(line.strip() for line in html.splitlines())
    st.markdown(html, unsafe_allow_html=True)


def apply_app_style() -> None:
    load_css("styles/main.css")


def page_header(title: str, subtitle: str, accent: str = "#22d3ee") -> None:
    render_html(
        f"""
        <div class="evs-hero" style="border-left: 4px solid {accent}; border-left-color: {accent};">
            <div class="evs-kicker" style="color:{accent};">Biometric Verification System</div>
            <div class="evs-hero-title">{escape(title)}</div>
            <div class="evs-hero-subtitle">{escape(subtitle)}</div>
            <div class="evs-hero-meta">
                <span class="evs-chip">Live identity verification</span>
                <span class="evs-chip">FaceNet ready</span>
                <span class="evs-chip">Local secure prototype</span>
            </div>
        </div>
        """
    )


def render_sidebar_brand() -> None:
    logo_path = ROOT_DIR / "Assets" / "examverify_logo_512.png"
    logo_src = ""
    if logo_path.exists():
        encoded_logo = base64.b64encode(logo_path.read_bytes()).decode("ascii")
        logo_src = f"data:image/png;base64,{encoded_logo}"
    st.sidebar.markdown(
        dedent(
            f"""
        <div class="evs-sidebar-brand">
            <div class="evs-brand-logo-row">
                <div class="evs-brand-mark">
                    <img src="{logo_src}" alt="ExamVerify logo" />
                </div>
                <div>
                    <div class="evs-brand-title">ExamVerify</div>
                    <div class="evs-brand-version">Exam Authentication System</div>
                </div>
            </div>
            <div class="evs-brand-divider"></div>
            <div class="evs-brand-tags">
                <span class="evs-brand-tag">v2.0</span>
                <span class="evs-brand-tag evs-brand-tag-live">LIVE</span>
            </div>
        </div>
        """
        ).strip(),
        unsafe_allow_html=True,
    )


def render_sidebar_footer() -> None:
    from datetime import datetime as _dt
    _now = _dt.now().strftime("%H:%M")
    st.sidebar.markdown(
        dedent(
            f"""
        <div class="evs-sidebar-status">
            <div class="evs-sidebar-status-row">
                <span class="evs-status-label">System state</span>
                <span class="evs-status-value"><span class="evs-dot evs-dot-pulse"></span>&nbsp;Online</span>
            </div>
            <div class="evs-sidebar-status-row">
                <span class="evs-status-label">Engine</span>
                <span class="evs-status-value">FaceNet</span>
            </div>
            <div class="evs-sidebar-status-row">
                <span class="evs-status-label">Session</span>
                <span class="evs-status-value">{_now}</span>
            </div>
        </div>
        <div class="evs-sidebar-footer">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
            &nbsp;Local Streamlit Console - DeepFace + OpenCV
        </div>
        """
        ).strip(),
        unsafe_allow_html=True,
    )


def current_user() -> dict | None:
    return st.session_state.get("auth_user")


def user_role() -> str:
    user = current_user() or {}
    return str(user.get("role") or "Viewer")


def is_admin() -> bool:
    return user_role() in {"Super Admin", "Admin"}


def authorized_pages() -> list[str]:
    role = user_role()
    allowed = ROLE_PAGES.get(role, ROLE_PAGES["Viewer"])
    return [page for page in NAV_ITEMS if page in allowed]


def session_is_expired() -> bool:
    last_activity = st.session_state.get("last_activity")
    if not last_activity:
        return False
    return (datetime.now() - last_activity).total_seconds() > SESSION_TIMEOUT_SECONDS


def sign_out(message: str | None = None) -> None:
    st.session_state.pop("auth_user", None)
    st.session_state.pop("last_activity", None)
    if message:
        st.session_state["auth_message"] = message
    st.rerun()


def require_admin() -> None:
    if not is_admin():
        st.error("This action requires an administrator account.")
        st.stop()


def render_login_page() -> None:
    page_header(
        "Secure Exam Console",
        "Sign in to access biometric registration, verification, and audit records.",
        accent="#22d3ee",
    )
    st.info("Demo accounts: admin / Admin@12345, invigilator / Verify@12345, viewer / View@12345")
    message = st.session_state.pop("auth_message", None)
    if message:
        st.warning(message)
    pending_username = st.session_state.get("pending_otp_username")
    if pending_username:
        st.success("Password accepted. Enter the email OTP to complete login.")
        with st.form("examverify_email_otp"):
            otp_code = st.text_input("Email OTP", max_chars=6)
            verify_submitted = st.form_submit_button("Verify OTP", type="primary")
        if st.session_state.get("pending_otp_demo_code"):
            st.caption(f"Local demo OTP: {st.session_state['pending_otp_demo_code']}")
        if st.button("Cancel login"):
            st.session_state.pop("pending_otp_username", None)
            st.session_state.pop("pending_otp_demo_code", None)
            st.rerun()
        if not verify_submitted:
            st.stop()
        user = verify_email_otp(pending_username, otp_code)
        if user is None:
            st.error("Invalid or expired email OTP.")
            st.stop()
        st.session_state.pop("pending_otp_username", None)
        st.session_state.pop("pending_otp_demo_code", None)
        st.session_state["auth_user"] = user
        st.session_state["last_activity"] = datetime.now()
        st.rerun()

    with st.form("examverify_login"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Send email OTP", type="primary")
    if not submitted:
        st.stop()
    user = verify_password_for_email_otp(username, password)
    if user is None:
        st.error("Invalid username/password, inactive account, or locked account.")
        st.stop()
    code = generate_email_otp()
    store_pending_email_otp(user["username"], code)
    try:
        email_result = send_email_otp(user.get("email", ""), code)
        if email_result.sent:
            st.success(email_result.message)
            st.session_state.pop("pending_otp_demo_code", None)
        else:
            st.warning(email_result.message)
            st.session_state["pending_otp_demo_code"] = code
    except Exception as exc:
        st.warning(
            "Could not send email OTP through SMTP. Using local demo OTP display."
        )
        st.caption(str(exc))
        st.session_state["pending_otp_demo_code"] = code
    st.session_state["pending_otp_username"] = user["username"]
    st.rerun()


def run_liveness_capture(student_number: str, seconds: int = 25) -> tuple[bool, Path | None, str]:
    status_slot = st.empty()
    frame_slot = st.empty()
    pipeline = LivenessPipeline(timeout_seconds=float(seconds))
    capture_path: Path | None = None
    camera = cv2.VideoCapture(0)
    if not camera.isOpened():
        pipeline.close()
        return False, None, "Could not open webcam for liveness challenge."
    try:
        started = perf_counter()
        while perf_counter() - started < seconds:
            ok, frame = camera.read()
            if not ok:
                return False, None, "Could not read a webcam frame."
            frame = cv2.resize(frame, (640, 480))
            result = pipeline.process(frame)
            status_slot.info(
                f"{result.message} | Blinks: {result.blink_count}/2 | Challenge: {result.challenge}"
            )
            cv2.putText(
                frame,
                result.message[:58],
                (18, 34),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.65,
                (34, 211, 238),
                2,
            )
            frame_slot.image(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB), channels="RGB", use_container_width=True)
            if result.passed and pipeline.state.best_frame is not None:
                timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
                capture_path = CAPTURE_DIR / f"live_liveness_{safe_file_part(student_number)}_{timestamp}.jpg"
                cv2.imwrite(str(capture_path), pipeline.state.best_frame)
                log_audit_event("LIVENESS_PASSED", actor=user_role(), details=result.message)
                return True, capture_path, result.message
            sleep(0.08)
    finally:
        camera.release()
        pipeline.close()
    log_audit_event("SPOOF_DETECTED", actor=user_role(), details="Liveness challenge timed out or failed")
    return False, capture_path, "Liveness challenge failed or timed out."


def enforce_login() -> None:
    if current_user() and session_is_expired():
        sign_out("Your session expired. Please sign in again.")
    if not current_user():
        render_login_page()
    st.session_state["last_activity"] = datetime.now()


def render_user_panel() -> None:
    user = current_user()
    if not user:
        return
    st.sidebar.markdown(
        dedent(
            f"""
            <div class="evs-user-panel">
                <div class="evs-user-name">{escape(str(user["full_name"]))}</div>
                <div class="evs-user-meta">{escape(str(user["role"]))} access</div>
            </div>
            """
        ).strip(),
        unsafe_allow_html=True,
    )
    if st.sidebar.button("Sign out", use_container_width=True):
        sign_out()


def admin_threshold_controls(
    default_facenet: float,
    default_lightweight: float | None = None,
    default_gap: float | None = None,
) -> tuple[float, float | None]:
    if is_admin():
        facenet_threshold = st.slider(
            "FaceNet distance threshold" if default_lightweight is not None else "Maximum L2 face distance",
            min_value=0.10,
            max_value=1.40 if default_lightweight is None else 0.80,
            value=float(default_facenet),
            step=0.01,
            help="Admin-controlled threshold for verification sensitivity.",
        )
        secondary = None
        if default_lightweight is not None:
            secondary = st.slider(
                "OpenCV fallback match threshold",
                min_value=-1.00,
                max_value=0.95,
                value=float(default_lightweight),
                step=0.01,
                help="Admin-controlled fallback threshold.",
            )
        elif default_gap is not None:
            secondary = st.slider(
                "Minimum gap from next closest student",
                min_value=0.00,
                max_value=0.30,
                value=float(default_gap),
                step=0.01,
                help="Admin-controlled ambiguity guard.",
            )
        return facenet_threshold, secondary

    st.caption("Threshold controls are locked to administrator accounts.")
    if default_lightweight is not None:
        return float(default_facenet), float(default_lightweight)
    return float(default_facenet), default_gap


def section_header(title: str, subtitle: str = "") -> None:
    subtitle_html = (
        f'<div class="evs-section-subtitle">{escape(subtitle)}</div>'
        if subtitle
        else ""
    )
    render_html(
        f"""
        <div class="evs-section-heading">
            <div>
                <div class="evs-section-title">{escape(title)}</div>
                {subtitle_html}
            </div>
        </div>
        """
    )


def mini_card(label: str, value: str) -> None:
    render_html(
        f"""
        <div class="evs-mini-card">
            <div class="evs-mini-label">{escape(label)}</div>
            <div class="evs-mini-value">{escape(value)}</div>
        </div>
        """
    )


def dashboard_metric_card(label: str, value: str | int | float, tone: str) -> None:
    render_html(
        f"""
        <div class="evs-metric-card {escape(tone)}">
            <div class="evs-metric-label">{escape(label)}</div>
            <div class="evs-metric-value">{escape(str(value))}</div>
        </div>
        """
    )


def dashboard_widgets(widgets: list[dict[str, str]]) -> None:
    cards = []
    for widget in widgets:
        cards.append(
            f"""
            <div class="evs-widget-card">
                <div class="evs-widget-top">
                    <div>
                        <div class="evs-widget-title">{escape(widget["title"])}</div>
                        <div class="evs-widget-value">{escape(widget["value"])}</div>
                    </div>
                    <div class="evs-icon-pill">{escape(widget["icon"])}</div>
                </div>
                <div class="evs-widget-text">{escape(widget["text"])}</div>
            </div>
            """
        )
    render_html(
        f'<div class="evs-widget-grid">{"".join(cards)}</div>',
    )


def camera_note(text: str) -> None:
    render_html(
        f'<div class="evs-camera-note">{escape(text)}</div>',
    )


def eligibility_badge(is_eligible: bool) -> str:
    if is_eligible:
        return '<span class="evs-status evs-status-ok">Eligible to write</span>'
    return '<span class="evs-status evs-status-blocked">Not eligible</span>'


def selected_active_exam_session(key: str) -> dict | None:
    user = current_user() or {}
    sessions = active_exam_sessions(
        user.get("username") if str(user.get("role", "")).lower() == "invigilator" else None
    )
    if not sessions:
        return None
    session = st.selectbox(
        "Select Active Exam Session",
        sessions,
        format_func=lambda row: (
            f"{row['course_code']} - {row['course_name']} | {row['venue']} | "
            f"{row['exam_date']} {row.get('start_time') or ''}"
        ),
        key=key,
    )
    st.info(
        f"Course: {session['course_code']} | Venue: {session['venue']} | "
        f"Invigilator: {user.get('full_name') or user.get('username')} | Device: Streamlit web"
    )
    return session


def unknown_badge() -> str:
    return '<span class="evs-status evs-status-unknown">Unknown student</span>'


def low_confidence_badge() -> str:
    return '<span class="evs-status evs-status-low">Low confidence match</span>'


def status_tone(value: str) -> str:
    status = value.upper()
    if status == "VERIFIED":
        return "verified"
    if status in {"ERROR", "UNKNOWN"} or "UNKNOWN" in status:
        return "error"
    return "not-verified"


def result_card_tone(value: str) -> str:
    tone = status_tone(value)
    if tone == "verified":
        return "is-verified"
    if "LOW" in value.upper():
        return "is-warning"
    return "is-denied"


def status_pill(value: str) -> str:
    tone = status_tone(value)
    return f'<span class="evs-log-status {tone}">{escape(value)}</span>'


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
    name = escape(str(student["full_name"])) if student else "Unknown"
    student_number = escape(str(student["student_number"])) if student else "Not identified"
    confidence = max(0.0, min(100.0, (1 - (distance / max(threshold, 0.01))) * 100))
    second_best = f"{second_best_score:.4f}" if second_best_score is not None else "N/A"
    status_html = status_pill(status)
    tone_class = result_card_tone(status)
    render_html(
        f"""
        <div class="evs-result-card {tone_class}">
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
                    <div class="evs-result-value">{status_html}</div>
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
        """
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
    if "student_number" in frame.columns:
        frame["student_number_masked"] = frame["student_number"].apply(
            lambda value: mask_student_identifier(str(value))
        )
    if "student_number_hash" in frame.columns:
        frame["student_id_hash"] = frame["student_number_hash"].apply(
            lambda value: "" if pd.isna(value) else str(value)[:16]
        )
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


def render_log_cards(logs: list[dict], limit: int | None = None) -> None:
    visible_logs = logs[:limit] if limit else logs
    cards = []
    for log in visible_logs:
        result = str(log.get("result") or "UNKNOWN")
        tone = status_tone(result)
        masked_number = escape(mask_student_identifier(str(log.get("student_number") or "")))
        hash_text = escape(str(log.get("student_number_hash") or "")[:16])
        full_name = escape(str(log.get("full_name") or "Unknown student"))
        verified_at = escape(str(log.get("verified_at") or "Pending")[:16])
        backend = escape(str(log.get("backend") or "Backend unavailable"))
        score = log.get("score")
        score_text = "Score N/A" if score is None else f"Score {float(score):.4f}"
        threshold = log.get("match_threshold")
        threshold_text = "" if threshold is None else f"Threshold {float(threshold):.2f}"
        meta = " / ".join(item for item in [backend, threshold_text] if item)
        cards.append(
            f"""
            <div class="evs-log-card {tone}">
                <div>
                    <div class="evs-log-time">{verified_at}</div>
                    <div class="evs-log-meta">{meta}</div>
                </div>
                <div>
                    <div class="evs-log-name">{full_name}</div>
                    <div class="evs-log-id">#{masked_number} / hash {hash_text}</div>
                </div>
                {status_pill(result)}
                <div class="evs-log-score">{escape(score_text)}</div>
            </div>
            """
        )
    render_html(
        f'<div class="evs-log-card-list">{"".join(cards)}</div>',
    )


def create_embedding_for_photo(photo_path: Path) -> tuple[str | None, str | None]:
    embedding_result = generate_face_embedding(photo_path)
    if embedding_result is None:
        return None, None
    return embedding_result


def dashboard_page() -> None:
    page_header(
        "Operations Dashboard",
        "Monitor registrations, verification attempts, and recent exam-entry results.",
        accent="#22d3ee",
    )
    summary = dashboard_summary()

    section_header("Command Metrics", "Current platform activity and verification outcomes.")
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        dashboard_metric_card("Registered students", summary["total_students"], "students")
    with col2:
        dashboard_metric_card("Verification attempts", summary["total_attempts"], "attempts")
    with col3:
        dashboard_metric_card("Verified", summary["verified_attempts"], "verified")
    with col4:
        dashboard_metric_card("Not verified", summary["failed_attempts"], "failed")

    dashboard_widgets(
        [
            {
                "icon": "SEC",
                "title": "Identity Engine",
                "value": "FaceNet",
                "text": "Deep embedding search with OpenCV fallback for prototype resilience.",
            },
            {
                "icon": "OK",
                "title": "Access Control",
                "value": f"{summary['verified_attempts']} approvals",
                "text": "Exam-entry decisions are logged with backend, score, threshold, and time.",
            },
            {
                "icon": "LOG",
                "title": "Audit Mode",
                "value": f"{summary['total_attempts']} records",
                "text": "Verification activity is exportable for lecturer review and evaluation.",
            },
        ]
    )

    if summary["error_attempts"]:
        st.warning(f"{summary['error_attempts']} verification attempt(s) ended with an error.")

    recent_logs = list_logs(limit=8)
    section_header("Recent Verification Attempts", "Latest exam-entry decisions recorded by the system.")
    if recent_logs:
        render_log_cards(recent_logs, limit=8)
    else:
        st.info("No verification attempts have been recorded yet.")


def register_student_page() -> None:
    require_admin()
    page_header(
        "Student Registration",
        "Enroll students, store their reference photo, and set exam eligibility.",
        accent="#60a5fa",
    )

    section_header("Enrollment Form", "Use a clear front-facing image so FaceNet can generate reliable embeddings.")
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
    session = selected_active_exam_session("verify_active_session")
    if session is None:
        page_header(
            "Verify Student",
            "Identity plus selected exam-session eligibility validation.",
        )
        st.error("Activate an exam session before verifying exam entry.")
        return
    page_header(
        "Exam Verification",
        "Select a student, capture a live face, and approve or reject entry.",
        accent="#22c55e",
    )

    section_header("Student Lookup", "Search, confirm eligibility, then capture the live face for verification.")
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
    render_html(eligibility_badge(bool(selected_student["exam_eligible"])))
    if selected_student["eligibility_note"]:
        st.caption(f"Eligibility note: {selected_student['eligibility_note']}")

    with st.expander("Matching settings"):
        if is_admin():
            backend_choice = st.radio(
                "Verification backend",
                ["Auto", "FaceNet only", "OpenCV fallback"],
                index=0,
                horizontal=True,
                help="Use FaceNet for better matching. Use OpenCV fallback if FaceNet is too slow on this laptop.",
            )
        else:
            backend_choice = "Auto"
            st.caption("Backend selection is locked to Auto for non-admin accounts.")
        facenet_threshold, lightweight_threshold = admin_threshold_controls(
            FACE_MATCH_THRESHOLD,
            LIGHTWEIGHT_MATCH_THRESHOLD,
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
        section_header("Registered Identity", "Stored reference details for the selected student.")
        reference_photo = Path(selected_student["photo_path"])
        if reference_photo.exists():
            st.image(str(reference_photo), width=300)
        else:
            st.error("The stored reference photo for this student is missing. Update the student photo before verification.")
            return
        a, b, c = st.columns(3)
        a.markdown("**Student number**")
        a.write(selected_student["student_number"])
        b.markdown("**Name**")
        b.write(selected_student["full_name"])
        c.markdown("**Program**")
        c.write(selected_student["program"] or "Not recorded")

    with right:
        section_header("Live Capture", "Take a current webcam image for face comparison.")
        camera_note("Camera guidance: blink twice, follow the head movement challenge, and keep your face centered.")
        challenge_key = f"liveness_capture_{selected_student['id']}"
        if st.button("Run liveness challenge", type="primary"):
            passed, live_path, live_message = run_liveness_capture(
                str(selected_student["student_number"])
            )
            if passed and live_path:
                st.session_state[challenge_key] = str(live_path)
                st.success(live_message)
            else:
                st.session_state.pop(challenge_key, None)
                st.error(live_message)
        if st.session_state.get(challenge_key):
            st.image(st.session_state[challenge_key], caption="Liveness-verified capture", width=300)
        with st.expander("Fallback single image capture"):
            st.caption("Use this only for controlled testing. Full verification requires the liveness challenge.")
            camera_image = st.camera_input("Capture student's face")

    if not st.session_state.get(challenge_key) and camera_image is None:
        return

    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    capture_path = CAPTURE_DIR / f"{safe_file_part(selected_student['student_number'])}_{timestamp}.jpg"

    try:
        if st.session_state.get(challenge_key):
            capture_path = Path(st.session_state[challenge_key])
        else:
            save_camera_image(camera_image, capture_path)
            liveness_check = run_static_liveness_check(capture_path)
            if not liveness_check.allowed_to_match:
                add_verification_log(
                    student_id=int(selected_student["id"]),
                    result="SPOOF DETECTED",
                    score=None,
                    backend="MediaPipe Face Mesh",
                    captured_image_path=capture_path,
                )
                log_audit_event(
                    "SPOOF_DETECTED",
                    actor=user_role(),
                    details=liveness_check.liveness.message,
                )
                st.error(f"Spoof detected: {liveness_check.liveness.message}")
                if liveness_check.liveness.spoof_reasons:
                    st.caption(", ".join(liveness_check.liveness.spoof_reasons))
                return
        start_time = perf_counter()
        backend_preference = {
            "Auto": "auto",
            "FaceNet only": "facenet",
            "OpenCV fallback": "opencv",
        }[backend_choice]
        result = verify_faces(
            reference_photo,
            capture_path,
            reference_embedding=selected_student["face_embedding"],
            facenet_threshold=facenet_threshold,
            lightweight_threshold=lightweight_threshold,
            backend_preference=backend_preference,
        )
        identity_matched = result.is_match
        if identity_matched and selected_student.get("face_embedding"):
            global_embedded_students = [
                row for row in list_students(active_only=True) if row.get("face_embedding")
            ]
            database_match = identify_face_from_embeddings(
                capture_path,
                global_embedded_students,
                facenet_threshold=facenet_threshold,
                min_distance_gap=0.08,
            )
            identity_matched = (
                database_match.status == "VERIFIED"
                and int(database_match.student_id or 0) == int(selected_student["id"])
            )
            if not identity_matched:
                st.error(
                    "ACCESS DENIED: the selected student is not the closest safe "
                    "database-wide face match."
                )
        duration_ms = (perf_counter() - start_time) * 1000
        entry_decision = evaluate_local_exam_entry(
            int(session["id"]),
            int(selected_student["id"]),
            True,
            identity_matched,
        )
        status = "VERIFIED" if entry_decision["decision"] == "VERIFIED" else "NOT VERIFIED"
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

        if entry_decision["decision"] == "VERIFIED":
            st.success(
                f"VERIFIED for {session['course_code']}: "
                f"{entry_decision.get('eligibility_type', 'regular')} student."
            )
        elif entry_decision["decision"] == "ALREADY_VERIFIED":
            st.warning(entry_decision["reason"])
        elif identity_matched:
            st.error(f"ACCESS DENIED: {entry_decision['reason']}")
        else:
            st.error(f"{status}: face did not match.")

        metric_label = "Distance" if "FaceNet" in result.backend else "Similarity"
        score_col, time_col = st.columns(2)
        score_col.metric(metric_label, f"{result.score:.4f}")
        time_col.metric("Response time", f"{duration_ms / 1000:.2f}s")
        st.caption(f"Threshold used: {match_threshold:.2f}")
        st.caption(f"Backend: {result.backend}. {result.message}")
        st.session_state.pop(challenge_key, None)
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
        accent="#a78bfa",
    )
    session = selected_active_exam_session("auto_active_session")
    if session is None:
        st.error("Activate an exam session before Auto Identify can approve exam entry.")
        return
    st.info(
        f"Active exam: {session['course_code']} - {session['course_name']} | "
        f"{session['program']} Level {session['level']} | {session['venue']}"
    )

    students = [dict(row) for row in list_students(active_only=True)]
    roster = list_exam_session_students(int(session["id"]))
    eligible_ids = {
        int(row["student_id"])
        for row in roster
        if row["eligibility_status"] == "eligible"
        and row["biometric_status"] == "face_enrolled"
    }
    global_embedded_students = [row for row in students if row.get("face_embedding")]
    embedded_students = [
        row for row in global_embedded_students if int(row["id"]) in eligible_ids
    ]

    section_header("Recognition Readiness", "FaceNet compares the live capture against stored student embeddings.")
    col1, col2, col3 = st.columns(3)
    col1.metric("Session roster", len(roster))
    col2.metric("Eligible and face-enrolled", len(embedded_students))
    col3.metric("Roster not scan-ready", len(roster) - len(embedded_students))

    if not students:
        st.info("No active students are registered yet.")
        return

    if not embedded_students:
        st.warning(
            "This session has no eligible students with stored FaceNet embeddings. "
            "Import or add eligible students after completing biometric enrollment."
        )
        return

    with st.expander("Identification settings"):
        facenet_threshold, min_distance_gap = admin_threshold_controls(
            0.48,
            default_gap=0.08,
        )
        st.info(
            "This mode L2-normalizes FaceNet embeddings, calculates approval distances "
            "against the full biometric database, and returns Unknown unless the closest distance is below "
            "the threshold and clearly better than the next closest student. Exam-session eligibility is checked afterward."
        )

    left, right = st.columns([1, 1])
    with left:
        section_header("Live Camera Scan", "Capture one clear face for automatic identity search.")
        camera_note("Capture one face only. Approval compares only with the selected session roster.")
        camera_image = st.camera_input("Capture face for automatic identification")

    with right:
        section_header("Identification Result", "The closest matching student appears here after processing.")
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
                global_embedded_students,
                facenet_threshold=facenet_threshold,
                min_distance_gap=min_distance_gap,
            )
            duration_ms = (perf_counter() - start_time) * 1000

        matched_student = find_student_by_id(global_embedded_students, result.student_id)
        if result.status == "UNKNOWN":
            render_html(unknown_badge())
            st.error("ACCESS DENIED: Face not recognized with sufficient confidence.")
            render_result_card(
                "Unknown",
                None,
                result.score,
                facenet_threshold,
                duration_ms,
                result.suggested_threshold,
                result.second_best_score,
            )
            distance_frame = ranked_distance_frame(global_embedded_students, result.ranked_matches)
            if not distance_frame.empty:
                st.caption("Closest stored student distances")
                st.dataframe(distance_frame, use_container_width=True, hide_index=True)
            return

        if matched_student is None:
            st.error("A matching result was returned, but the student record could not be loaded.")
            return

        entry_decision = evaluate_local_exam_entry(
            int(session["id"]),
            int(matched_student["id"]),
            True,
            result.status == "VERIFIED",
        )
        log_status = (
            "VERIFIED" if entry_decision["decision"] == "VERIFIED" else "NOT VERIFIED"
        )
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
            render_html(low_confidence_badge())
            st.warning(result.message)
        else:
            render_html(eligibility_badge(bool(matched_student["exam_eligible"])))

        if entry_decision["decision"] == "VERIFIED":
            st.success(
                f"Student identified and approved for {session['course_code']} "
                f"as {entry_decision.get('eligibility_type', 'regular')}."
            )
        elif entry_decision["decision"] == "ALREADY_VERIFIED":
            st.warning(entry_decision["reason"])
        elif result.status == "VERIFIED":
            st.error(f"ACCESS DENIED: {entry_decision['reason']}")

        result_left, result_right = st.columns([1, 1])
        with result_left:
            section_header("Matched Identity", "Stored photo for the best candidate.")
            matched_photo = Path(matched_student["photo_path"])
            if matched_photo.exists():
                st.image(str(matched_photo), caption="Matched student photo", width=280)
            else:
                st.warning("The stored photo for this matched student is missing.")
        with result_right:
            section_header("Candidate Details", "Review the returned student before allowing exam entry.")
            mini_card("Student number", matched_student["student_number"])
            mini_card("Name", matched_student["full_name"])
            mini_card("Program", matched_student["program"] or "Not recorded")
            if matched_student["eligibility_note"]:
                st.caption(f"Eligibility note: {matched_student['eligibility_note']}")
            render_result_card(
                result.status.replace("_", " ").title(),
                matched_student,
                result.score,
                facenet_threshold,
                duration_ms,
                result.suggested_threshold,
                result.second_best_score,
            )
            distance_frame = ranked_distance_frame(global_embedded_students, result.ranked_matches)
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
        accent="#fb923c",
    )

    students = [dict(row) for row in list_students(active_only=True)]
    embedded_students = [row for row in students if row.get("face_embedding")]

    section_header("Scanner Readiness", "The real-time scanner waits for a stable face before running recognition.")
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
        threshold, min_gap = admin_threshold_controls(0.48, default_gap=0.08)
        if is_admin():
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
        else:
            stable_seconds = 0.8
            cooldown_seconds = 2.5
            scan_seconds = 45

    auto_scan_enabled = st.toggle("Automatic scanner enabled", value=True)
    section_header("Live Scanner Feed", "Keep the face centered and steady until recognition starts.")
    camera_note("The scanner waits for a stable face, then runs identification after the cooldown window.")
    status_slot = st.empty()
    frame_slot = st.empty()
    result_slot = st.empty()

    if not auto_scan_enabled:
        status_slot.info("Automatic scanning is paused.")
        return

    camera = cv2.VideoCapture(0)
    if not camera.isOpened():
        st.error("Could not open the webcam. Close other camera apps and try again.")
        return

    previous_box = None
    stable_start = None
    last_recognition_time = 0.0
    scanner_started = perf_counter()
    liveness_pipeline = LivenessPipeline(timeout_seconds=float(scan_seconds))

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
                        live_result = liveness_pipeline.process(frame)
                        if not live_result.passed:
                            status_slot.info(
                                f"{live_result.message} | Blinks: {live_result.blink_count}/2 | Challenge: {live_result.challenge}"
                            )
                            previous_box = face_box
                            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                            frame_slot.image(frame_rgb, channels="RGB", use_container_width=True)
                            sleep(0.08)
                            continue
                        status_slot.info("Processing face recognition...")
                        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
                        capture_path = CAPTURE_DIR / f"face_unlock_{timestamp}.jpg"
                        cv2.imwrite(str(capture_path), frame)
                        log_audit_event(
                            "LIVENESS_PASSED",
                            actor=user_role(),
                            details=live_result.message,
                        )

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
                                render_html(eligibility_badge(bool(matched_student["exam_eligible"])))
                                if matched_student["exam_eligible"]:
                                    st.success("Verified. Student identified and eligible.")
                                else:
                                    st.warning("Verified identity, but student is not eligible.")
                                info_col, photo_col = st.columns([1, 1])
                                with info_col:
                                    mini_card("Full name", matched_student["full_name"])
                                    mini_card("Student number", matched_student["student_number"])
                                    mini_card("Program", matched_student["program"] or "Not recorded")
                                with photo_col:
                                    stored_photo = Path(matched_student["photo_path"])
                                    if stored_photo.exists():
                                        st.image(str(stored_photo), caption="Stored student image", width=240)
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
                                render_html(low_confidence_badge())
                                st.warning("Low confidence match. Manual review recommended.")
                                info_col, photo_col = st.columns([1, 1])
                                with info_col:
                                    mini_card("Full name", matched_student["full_name"])
                                    mini_card("Student number", matched_student["student_number"])
                                    mini_card("Program", matched_student["program"] or "Not recorded")
                                with photo_col:
                                    stored_photo = Path(matched_student["photo_path"])
                                    if stored_photo.exists():
                                        st.image(str(stored_photo), caption="Stored student image", width=240)
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
                                render_html(unknown_badge())
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
                        liveness_pipeline.close()
                        liveness_pipeline = LivenessPipeline(timeout_seconds=float(scan_seconds))
                    else:
                        remaining = cooldown_seconds - (now - last_recognition_time)
                        status_slot.info(f"Cooldown active: {remaining:.1f}s")
                else:
                    stable_start = None
                    status_slot.info("Hold still...")
                previous_box = face_box

            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            frame_slot.image(frame_rgb, channels="RGB", use_container_width=True)
            sleep(0.08)
    finally:
        camera.release()
        liveness_pipeline.close()
        status_slot.success("Scanner stopped.")


def logs_page() -> None:
    page_header(
        "Verification Logs",
        "Review captured attempts, outcomes, thresholds, and exported evidence.",
        accent="#94a3b8",
    )
    logs = list_logs()
    integrity = audit_log_integrity()
    if integrity["tampered"]:
        st.error(
            f"Audit integrity needs attention. {integrity['tampered']} log record(s) did not match the stored chain."
        )
    elif integrity["unsigned"]:
        st.info(
            f"Audit chain active. {integrity['checked']} signed record(s), {integrity['unsigned']} legacy unsigned record(s)."
        )
    else:
        st.success(f"Audit chain verified for {integrity['checked']} record(s).")
    if not logs:
        st.info("No verification attempts have been recorded yet.")
        return

    frame = prepare_log_frame(logs)

    # Summary stat chips
    _total  = len(logs)
    _ok     = sum(1 for r in logs if r.get("result") == "VERIFIED")
    _fail   = sum(1 for r in logs if r.get("result") == "NOT VERIFIED")
    _err    = sum(1 for r in logs if r.get("result") == "ERROR")
    _err_chip = f'<span class="evs-log-chip evs-log-chip-err">ERR {_err} errors</span>' if _err else ""
    render_html(
        f'<div class="evs-log-chips">'
        f'<span class="evs-log-chip evs-log-chip-total">TOTAL {_total}</span>'
        f'<span class="evs-log-chip evs-log-chip-ok">VERIFIED {_ok}</span>'
        f'<span class="evs-log-chip evs-log-chip-fail">DENIED {_fail}</span>'
        f'{_err_chip}</div>',
    )

    section_header("Audit Trail", "Exportable evidence for verification attempts and evaluation records.")
    render_log_cards(logs, limit=12)

    st.download_button(
        "Export logs as CSV",
        data=frame.to_csv(index=False).encode("utf-8"),
        file_name=f"verification_logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        mime="text/csv",
    )
    with st.expander("Detailed export table"):
        st.dataframe(
            frame[
                [
                    "verified_at",
                    "student_number_masked",
                    "student_id_hash",
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

    audit_events = list_audit_events(limit=100)
    if audit_events:
        section_header("Security Audit Events", "Login, liveness, spoof, and administrative security events.")
        st.dataframe(
            pd.DataFrame(audit_events),
            use_container_width=True,
            hide_index=True,
        )

    preview_options = {
        f"{row['verified_at']} | {mask_student_identifier(str(row['student_number']))} | {row['result']}": row
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
                f"{mask_student_identifier(str(selected_log['student_number']))} - {selected_log['full_name']} "
                f"({selected_log['result']})"
            ),
            width=300,
        )
    else:
        st.warning("The captured image file for this log entry is no longer available.")


def exam_sessions_page() -> None:
    page_header(
        "Exam Sessions",
        "Link already-enrolled students to the specific examination they are authorized to write.",
    )
    with st.form("create_exam_session"):
        course_code = st.text_input("Course code")
        course_name = st.text_input("Course name")
        program = st.text_input("Program")
        level = st.text_input("Exam level")
        exam_date = st.text_input("Exam date", placeholder="YYYY-MM-DD")
        start_time = st.text_input("Start time", placeholder="HH:MM")
        end_time = st.text_input("End time", placeholder="HH:MM")
        venue = st.text_input("Venue")
        if st.form_submit_button("Create exam session"):
            create_exam_session(
                course_code,
                course_name,
                program,
                level,
                exam_date,
                start_time,
                end_time,
                venue,
                st.session_state.get("username", "admin"),
            )
            st.success("Exam session created.")
            st.rerun()

    sessions = list_exam_sessions()
    students = list_students(active_only=False)
    for session in sessions:
        with st.expander(
            f"{session['course_code']} - {session['course_name']} | {session['status']}"
        ):
            st.write(
                f"{session['program']} Level {session['level']} | "
                f"{session['exam_date']} | {session['venue']}"
            )
            left, middle = st.columns(2)
            if left.button("Activate", key=f"activate_{session['id']}"):
                set_exam_session_status(session["id"], "active")
                st.rerun()
            if middle.button("Complete", key=f"complete_{session['id']}"):
                set_exam_session_status(session["id"], "completed")
                st.rerun()
            invigilators = list_invigilator_users()
            if invigilators:
                selected_invigilator = st.selectbox(
                    "Assign invigilator",
                    invigilators,
                    format_func=lambda row: f"{row['full_name']} ({row['username']})",
                    key=f"invigilator_{session['id']}",
                )
                session_role = st.selectbox(
                    "Session role",
                    ["lead", "support"],
                    key=f"invigilator_role_{session['id']}",
                )
                if st.button("Assign selected invigilator", key=f"assign_{session['id']}"):
                    assign_exam_session_invigilator(
                        session["id"],
                        selected_invigilator["username"],
                        st.session_state.get("username", "admin"),
                        session_role,
                    )
                    st.success("Invigilator assigned.")
            matching_students = [
                row
                for row in students
                if row.get("student_status", "active") == "active"
                and (
                    not session["program"]
                    or row.get("program", "").casefold() == session["program"].casefold()
                )
                and (
                    not session["level"]
                    or str(row.get("level", "")).casefold() == session["level"].casefold()
                )
            ]
            st.caption(
                f"{len(matching_students)} active student(s) match "
                f"{session['program']} Level {session['level']}. "
                "Use exceptions for repeat, deferred, or supplementary students."
            )
            if st.button("Add matching cohort", key=f"cohort_{session['id']}"):
                added = add_matching_exam_cohort(session["id"])
                st.success(f"Added {added} matching student(s).")
                st.rerun()
            uploaded = st.file_uploader(
                "Import Eligible List",
                type=["csv", "xlsx"],
                key=f"import_{session['id']}",
                help=(
                    "Links student numbers to existing biometric profiles. "
                    "It never creates students or face embeddings."
                ),
            )
            if uploaded is not None and st.button(
                "Review and import list", key=f"run_import_{session['id']}"
            ):
                frame = (
                    pd.read_csv(uploaded)
                    if uploaded.name.lower().endswith(".csv")
                    else pd.read_excel(uploaded)
                )
                frame.columns = [str(column).strip().lower() for column in frame.columns]
                if "student_number" not in frame.columns:
                    st.error("The imported file must include a student_number column.")
                else:
                    report = import_exam_eligibility_rows(
                        session["id"],
                        frame.fillna("").to_dict("records"),
                        uploaded.name,
                        st.session_state.get("username", "admin"),
                    )
                    summary = st.columns(6)
                    summary[0].metric("Rows", report["total_rows"])
                    summary[1].metric("Linked", report["linked_count"])
                    summary[2].metric("Already added", report["already_added_count"])
                    summary[3].metric("Unmatched", report["unmatched_count"])
                    summary[4].metric("No face", report["no_face_count"])
                    summary[5].metric("Invalid", report["invalid_count"] + report["duplicate_count"])
                    if report["review"]:
                        st.subheader("Import Review / Unmatched Students")
                        st.dataframe(report["review"], use_container_width=True, hide_index=True)
            active_students = [
                row for row in students if row.get("student_status", "active") == "active"
            ]
            if active_students:
                selected = st.selectbox(
                    "Add individual exception",
                    active_students,
                    format_func=lambda row: (
                        f"{row['student_number']} - {row['full_name']} "
                        f"({row['program']} Level {row.get('level', '')})"
                    ),
                    key=f"student_{session['id']}",
                )
                eligibility_type = st.selectbox(
                    "Eligibility type",
                    ["regular", "repeat", "deferred", "supplementary", "manual_override"],
                    key=f"type_{session['id']}",
                )
                if st.button("Add eligible student", key=f"add_{session['id']}"):
                    add_exam_session_student(
                        session["id"], selected["id"], eligibility_type
                    )
                    st.rerun()
            roster = list_exam_session_students(session["id"])
            st.subheader("Eligible Student Roster")
            st.dataframe(roster, use_container_width=True, hide_index=True)
            if roster:
                roster_student = st.selectbox(
                    "Roster action",
                    roster,
                    format_func=lambda row: (
                        f"{row['student_number']} - {row['full_name']} | "
                        f"{row['biometric_status']} | {row['eligibility_status']} | "
                        f"{row['attendance_status']}"
                    ),
                    key=f"roster_action_{session['id']}",
                )
                block_col, remove_col = st.columns(2)
                if block_col.button("Block selected", key=f"block_{session['id']}"):
                    set_exam_session_student_status(
                        session["id"], roster_student["student_id"], "blocked"
                    )
                    st.rerun()
                if remove_col.button("Remove selected", key=f"remove_{session['id']}"):
                    remove_exam_session_student(
                        session["id"], roster_student["student_id"]
                    )
                    st.rerun()


def students_page() -> None:
    require_admin()
    page_header(
        "Registered Students",
        "Maintain student details, photos, embeddings, status, and exam eligibility.",
        accent="#2dd4bf",
    )
    section_header("Student Directory", "Search and manage registered students without leaving the console.")
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
    active_count = int(frame["active"].sum()) if "active" in frame else 0
    embedding_count = int(frame["face_embedding"].notna().sum()) if "face_embedding" in frame else 0
    directory_cols = st.columns(4)
    directory_cols[0].metric("Visible students", len(frame))
    directory_cols[1].metric("Active", active_count)
    directory_cols[2].metric("With embeddings", embedding_count)
    directory_cols[3].metric("Eligible", int(frame["exam_eligible"].sum()))
    render_html(
        '<div class="evs-table-note">Directory records are filtered by the search field and active-status setting above.</div>',
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

    section_header("Student Management", "Update details, refresh FaceNet embeddings, or change active status.")
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
        section_header("Stored Identity", "Current photo and embedding state.")
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
        section_header("Edit Record", "Changes are saved to the local student database.")
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
        accent="#facc15",
    )
    summary = evaluation_summary()

    section_header("Evaluation Controls", "Prepare repeatable test runs for your project demonstration.")
    with st.expander("Demo and testing guide", expanded=True):
        st.markdown(
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
        st.markdown(
            "Clear old verification attempts before a new test run. Student records and "
            "registered photos will stay saved."
        )
        if is_admin():
            confirm_clear = st.checkbox("I want to clear all verification logs")
            if st.button(
                "Clear verification logs",
                disabled=not confirm_clear,
                type="secondary",
            ):
                deleted_count = clear_verification_logs()
                st.success(f"Cleared {deleted_count} verification log(s).")
                st.rerun()
        else:
            st.info("Only administrator accounts can clear verification logs.")

    section_header("Evaluation Metrics", "Accuracy, decision distribution, and response-time indicators.")
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

    section_header("Report Notes", "Editable text you can use when writing the evaluation section.")
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
        section_header("Evaluation Source Records", "Underlying log entries used for the summary above.")
        st.dataframe(
            frame[
                [
                    "verified_at",
                    "student_number_masked",
                    "student_id_hash",
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


NAV_ITEMS = {
    "Dashboard": {"icon": "\u2302", "page": dashboard_page},
    "Register Student": {"icon": "+", "page": register_student_page},
    "Verify Student": {"icon": "\u2713", "page": verify_student_page},
    "Auto Identify": {"icon": "\u25ce", "page": auto_identify_page},
    "Face Unlock Scanner": {"icon": "\u25a3", "page": face_unlock_scanner_page},
    "Students": {"icon": "ID", "page": students_page},
    "Exam Sessions": {"icon": "EX", "page": exam_sessions_page},
    "System Evaluation": {"icon": "\u03a3", "page": evaluation_page},
    "Verification Logs": {"icon": "\u2261", "page": logs_page},
}


def nav_label(page_name: str) -> str:
    return f"{NAV_ITEMS[page_name]['icon']}  {page_name}"

enforce_login()
render_sidebar_brand()
render_user_panel()
st.sidebar.markdown('<div class="evs-nav-label">NAVIGATION</div>', unsafe_allow_html=True)
allowed_pages = authorized_pages()
selected_page = st.sidebar.radio(
    "Navigation",
    allowed_pages,
    format_func=nav_label,
    label_visibility="collapsed",
)
render_sidebar_footer()
NAV_ITEMS[selected_page]["page"]()
