from __future__ import annotations

import argparse
from functools import wraps
import json
import secrets
import sys
import traceback
from datetime import datetime
from pathlib import Path

import cv2
from flask import Flask, jsonify, request
import numpy as np

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from SRC.authentication import generate_email_otp, send_email_otp
from SRC.config import CAPTURE_DIR, PHOTO_DIR, ensure_directories
from SRC.database import (
    add_student,
    add_verification_log,
    get_student,
    init_db,
    list_audit_events,
    list_logs,
    list_students,
    log_audit_event,
    store_pending_email_otp,
    verify_email_otp,
    verify_password_for_email_otp,
)
from SRC.face_matcher import (
    FaceMatchError,
    generate_face_embedding,
    identify_face_from_embeddings,
    save_uploaded_image,
    verify_faces,
)
from SRC.face_verification import analyze_live_face_signal, run_static_liveness_check


app = Flask(__name__)
ensure_directories()
init_db()
API_SESSIONS: dict[str, dict] = {}
MOBILEFACENET_INPUT_SIZE = 112
MOBILEFACENET_MODEL_PATHS = (
    ROOT_DIR / "Flutter" / "examverify_app" / "assets" / "models" / "mobilefacenet.tflite",
    ROOT_DIR / "data" / "flutter_assets" / "assets" / "models" / "mobilefacenet.tflite",
)
_mobilefacenet_interpreter = None


def require_token(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        token = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
        user = API_SESSIONS.get(token)
        if not user:
            return _error("Unauthorized", 401)
        request.examverify_user = user
        return fn(*args, **kwargs)

    return wrapper


@app.get("/health")
def health():
    return jsonify({"ok": True, "service": "ExamVerify Face Backend"})


@app.post("/auth/login")
def auth_login():
    payload = request.get_json(force=True) or {}
    username = str(payload.get("username") or "")
    password = str(payload.get("password") or "")
    user = verify_password_for_email_otp(username, password)
    if user is None:
        return _error("Invalid credentials or locked account.", 401)
    code = generate_email_otp()
    store_pending_email_otp(user["username"], code)
    try:
        result = send_email_otp(user.get("email", ""), code)
    except Exception as exc:
        result = type("EmailResult", (), {"sent": False, "message": str(exc)})()
    response = {
        "ok": True,
        "username": user["username"],
        "message": result.message,
        "email_sent": bool(result.sent),
    }
    if not result.sent:
        response["demo_code"] = code
    return jsonify(response)


@app.post("/auth/verify-otp")
def auth_verify_otp():
    payload = request.get_json(force=True) or {}
    username = str(payload.get("username") or "")
    otp = str(payload.get("otp") or "")
    user = verify_email_otp(username, otp)
    if user is None:
        return _error("Invalid or expired OTP.", 401)
    token = secrets.token_urlsafe(32)
    API_SESSIONS[token] = user
    return jsonify({"ok": True, "token": token, "user": user})


@app.get("/students")
@require_token
def api_students():
    return jsonify({"ok": True, "students": list_students(active_only=True)})


@app.post("/students")
@require_token
def api_register_student():
    photo = request.files.get("photo")
    student_number = request.form.get("student_number", "").strip()
    full_name = request.form.get("full_name", "").strip()
    program = request.form.get("program", "").strip()
    eligible = request.form.get("eligible", "true").lower() in {"1", "true", "yes"}
    note = request.form.get("note", "").strip()
    if not photo or not student_number or not full_name:
        return _error("Student number, full name, and photo are required.", 400)
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    photo_path = PHOTO_DIR / f"{_safe_file_part(student_number)}_{timestamp}.jpg"
    save_uploaded_image(photo, photo_path)
    embedding, backend = generate_face_embedding(photo_path) or (None, None)
    student_id = add_student(
        student_number,
        full_name,
        program,
        photo_path,
        face_embedding=embedding,
        embedding_backend=backend,
        exam_eligible=eligible,
        eligibility_note=note,
    )
    log_audit_event(
        "ADMIN_ACTION",
        actor=request.examverify_user["username"],
        details=f"Registered student {student_number}",
    )
    return jsonify({"ok": True, "student_id": student_id, "embedding_backend": backend})


@app.get("/logs")
@require_token
def api_logs():
    return jsonify({"ok": True, "logs": list_logs(limit=200)})


@app.get("/audit-events")
@require_token
def api_audit_events():
    return jsonify({"ok": True, "events": list_audit_events(limit=200)})


@app.post("/embedding")
def embedding():
    payload = request.get_json(force=True) or {}
    image_path = _required_path(payload, "image_path")
    result = generate_face_embedding(image_path)
    if result is None:
        return _error("FaceNet could not create an embedding for this image.", 422)
    embedding_json, backend = result
    return jsonify(
        {
            "ok": True,
            "embedding": embedding_json,
            "backend": backend,
        }
    )


@app.post("/mobilefacenet-signature")
def mobilefacenet_signature():
    payload = request.get_json(force=True) or {}
    image_path = _required_path(payload, "image_path")
    cropped_face = _crop_largest_face(image_path)
    if cropped_face is None:
        return _error("No face was detected in the desktop camera frame.", 422)
    signature = _generate_mobilefacenet_signature(cropped_face)
    return jsonify(
        {
            "ok": True,
            "signature": signature,
            "backend": "MobileFaceNet TFLite / Desktop runtime",
        }
    )


@app.post("/liveness")
def liveness():
    payload = request.get_json(force=True) or {}
    image_path = _required_path(payload, "image_path")
    return jsonify({"ok": True, **analyze_live_face_signal(image_path)})


@app.post("/face-crop")
def face_crop():
    payload = request.get_json(force=True) or {}
    image_path = _required_path(payload, "image_path")
    cropped = _crop_largest_face(image_path)
    if cropped is None:
        return _error("No face was detected in the desktop camera frame.", 422)
    crop_path = CAPTURE_DIR / f"crop_{datetime.now().strftime('%Y%m%d%H%M%S%f')}.jpg"
    cv2.imwrite(str(crop_path), cropped)
    return jsonify({"ok": True, "image_path": str(crop_path)})


@app.post("/verify")
def verify():
    if request.files:
        return _verify_uploaded()
    payload = request.get_json(force=True) or {}
    reference_image = _required_path(payload, "reference_image_path")
    live_image = _required_path(payload, "live_image_path")
    result = verify_faces(
        reference_image,
        live_image,
        reference_embedding=payload.get("reference_embedding"),
        backend_preference=payload.get("backend_preference", "auto"),
    )
    return jsonify(
        {
            "ok": True,
            "is_match": result.is_match,
            "score": result.score,
            "backend": result.backend,
            "message": result.message,
        }
    )


@app.post("/identify")
def identify():
    if request.files:
        return _identify_uploaded()
    payload = request.get_json(force=True) or {}
    live_image = _required_path(payload, "live_image_path")
    candidates = payload.get("candidates") or []
    result = identify_face_from_embeddings(live_image, candidates)
    return jsonify(
        {
            "ok": True,
            "student_id": result.student_id,
            "is_match": result.is_match,
            "status": result.status,
            "score": result.score,
            "second_best_score": result.second_best_score,
            "backend": result.backend,
            "message": result.message,
            "ranked_matches": result.ranked_matches,
        }
    )


def _verify_uploaded():
    token = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    user = API_SESSIONS.get(token)
    if not user:
        return _error("Unauthorized", 401)
    live_photo = request.files.get("live_photo")
    student_id = int(request.form.get("student_id", "0"))
    student = get_student(student_id)
    if not live_photo or not student:
        return _error("Student and live photo are required.", 400)
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    capture_path = CAPTURE_DIR / f"online_{student_id}_{timestamp}.jpg"
    save_uploaded_image(live_photo, capture_path)
    liveness = run_static_liveness_check(capture_path)
    if not liveness.allowed_to_match:
        add_verification_log(
            student_id=student_id,
            result="SPOOF DETECTED",
            score=liveness.liveness.geometry_score,
            backend="MediaPipe Face Mesh",
            captured_image_path=capture_path,
        )
        log_audit_event(
            "SPOOF_DETECTED",
            actor=user["username"],
            details=liveness.liveness.message,
        )
        return jsonify(
            {
                "ok": True,
                "status": "SPOOF DETECTED",
                "is_match": False,
                "score": liveness.liveness.geometry_score,
                "backend": "MediaPipe Face Mesh",
                "message": liveness.liveness.message,
            }
        )
    result = verify_faces(
        Path(student["photo_path"]),
        capture_path,
        reference_embedding=student.get("face_embedding"),
        backend_preference="auto",
    )
    status = "VERIFIED" if result.is_match and student.get("exam_eligible") else "NOT VERIFIED"
    add_verification_log(
        student_id=student_id,
        result=status,
        score=result.score,
        backend=result.backend,
        captured_image_path=capture_path,
    )
    return jsonify(
        {
            "ok": True,
            "status": status,
            "is_match": status == "VERIFIED",
            "score": result.score,
            "backend": result.backend,
            "message": result.message,
            "student": student,
        }
    )


def _identify_uploaded():
    token = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    user = API_SESSIONS.get(token)
    if not user:
        return _error("Unauthorized", 401)
    live_photo = request.files.get("live_photo")
    if not live_photo:
        return _error("Live photo is required.", 400)
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    capture_path = CAPTURE_DIR / f"online_identify_{timestamp}.jpg"
    save_uploaded_image(live_photo, capture_path)
    liveness = run_static_liveness_check(capture_path)
    if not liveness.allowed_to_match:
        log_audit_event(
            "SPOOF_DETECTED",
            actor=user["username"],
            details=liveness.liveness.message,
        )
        return jsonify(
            {
                "ok": True,
                "status": "SPOOF DETECTED",
                "is_match": False,
                "score": liveness.liveness.geometry_score,
                "backend": "MediaPipe Face Mesh",
                "message": liveness.liveness.message,
            }
        )
    candidates = list_students(active_only=True)
    result = identify_face_from_embeddings(capture_path, candidates)
    student = get_student(result.student_id) if result.student_id else None
    if student and result.status == "VERIFIED":
        add_verification_log(
            student_id=int(student["id"]),
            result="VERIFIED",
            score=result.score,
            backend=result.backend,
            captured_image_path=capture_path,
        )
    return jsonify(
        {
            "ok": True,
            "student_id": result.student_id,
            "is_match": result.is_match,
            "status": result.status,
            "score": result.score,
            "second_best_score": result.second_best_score,
            "backend": result.backend,
            "message": result.message,
            "ranked_matches": result.ranked_matches,
            "student": student,
        }
    )


@app.errorhandler(FaceMatchError)
def face_match_error(error):
    return _error(str(error), 422)


@app.errorhandler(Exception)
def unexpected_error(error):
    traceback.print_exc()
    return _error("The local face service could not complete the request.", 500)


def _required_path(payload: dict, key: str) -> Path:
    value = payload.get(key)
    if not value:
        raise FaceMatchError(f"Missing required field: {key}")
    path = Path(value)
    if not path.exists():
        raise FaceMatchError(f"Image path does not exist: {path}")
    return path


def _crop_largest_face(image_path: Path) -> np.ndarray | None:
    image = cv2.imread(str(image_path))
    if image is None:
        return None
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )
    faces = cascade.detectMultiScale(
        gray,
        scaleFactor=1.06,
        minNeighbors=4,
        minSize=(54, 54),
    )
    if len(faces) == 0:
        return None
    x, y, width, height = max(faces, key=lambda face: face[2] * face[3])
    pad_x = int(width * 0.20)
    pad_y = int(height * 0.22)
    left = max(0, x - pad_x)
    top = max(0, y - pad_y)
    right = min(image.shape[1], x + width + pad_x)
    bottom = min(image.shape[0], y + height + pad_y)
    return image[top:bottom, left:right]


def _generate_mobilefacenet_signature(cropped_face: np.ndarray) -> list[float]:
    global _mobilefacenet_interpreter
    if _mobilefacenet_interpreter is None:
        model_path = next((path for path in MOBILEFACENET_MODEL_PATHS if path.exists()), None)
        if model_path is None:
            raise FaceMatchError("The bundled MobileFaceNet model is unavailable.")
        import tensorflow as tf

        _mobilefacenet_interpreter = tf.lite.Interpreter(model_path=str(model_path))
        _mobilefacenet_interpreter.allocate_tensors()

    resized = cv2.resize(cropped_face, (MOBILEFACENET_INPUT_SIZE, MOBILEFACENET_INPUT_SIZE))
    rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB).astype(np.float32)
    input_tensor = np.expand_dims((rgb - 127.5) / 128.0, axis=0)
    input_details = _mobilefacenet_interpreter.get_input_details()[0]
    output_details = _mobilefacenet_interpreter.get_output_details()[0]
    _mobilefacenet_interpreter.set_tensor(input_details["index"], input_tensor)
    _mobilefacenet_interpreter.invoke()
    raw = _mobilefacenet_interpreter.get_tensor(output_details["index"]).flatten()
    norm = np.linalg.norm(raw)
    if norm == 0:
        raise FaceMatchError("MobileFaceNet could not generate a biometric signature.")
    return [float(value) for value in raw / norm]


def _error(message: str, status_code: int):
    response = jsonify({"ok": False, "error": message})
    response.status_code = status_code
    return response


def _safe_file_part(value: str) -> str:
    cleaned = "".join(char for char in value.strip() if char.isalnum() or char in ("-", "_"))
    return cleaned or "student"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    app.run(host=args.host, port=args.port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
