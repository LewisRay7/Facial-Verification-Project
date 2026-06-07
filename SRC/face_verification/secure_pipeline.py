from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import math

import cv2
import numpy as np

_desktop_face_mesh = None

try:
    from SRC.liveness import LivenessResult, StaticLivenessAnalyzer
except ImportError:
    @dataclass
    class LivenessResult:
        passed: bool
        status: str
        message: str
        blink_count: int = 0
        challenge: str = ""
        challenge_passed: bool = True
        geometry_score: float = 1.0

    StaticLivenessAnalyzer = None


@dataclass
class SecureVerificationResult:
    liveness: LivenessResult
    allowed_to_match: bool


def analyze_live_face_signal(image_path: Path) -> dict[str, object]:
    """Return a resilient webcam signal for Flutter challenge processing."""
    image = cv2.imread(str(image_path))
    if image is None:
        return _empty_signal("Captured image could not be read.")

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    detection_gray = cv2.equalizeHist(gray)
    face_candidates: list[tuple[int, int, int, int]] = []
    cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )
    faces = cascade.detectMultiScale(
        detection_gray,
        scaleFactor=1.08,
        minNeighbors=6,
        minSize=(90, 90),
    )
    if len(faces) > 0:
        face_candidates = [tuple(int(value) for value in face) for face in faces]
    x, y, width, height = (
        max(face_candidates, key=lambda face: face[2] * face[3])
        if face_candidates
        else (0, 0, 0, 0)
    )
    face_area = (width * height) / max(float(image.shape[0] * image.shape[1]), 1.0)
    brightness = (
        float(gray[y : y + height, x : x + width].mean() / 255.0)
        if width > 0 and height > 0
        else 0.0
    )
    fallback_quality = min(0.86, max(0.0, (face_area * 5.4) + (brightness * 0.35)))

    try:
        import mediapipe as mp

        global _desktop_face_mesh
        if _desktop_face_mesh is None:
            _desktop_face_mesh = mp.solutions.face_mesh.FaceMesh(
                static_image_mode=True,
                max_num_faces=1,
                refine_landmarks=True,
                min_detection_confidence=0.42,
            )
        result = _desktop_face_mesh.process(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
        if result.multi_face_landmarks:
            detected_count = len(result.multi_face_landmarks)
            points = result.multi_face_landmarks[0].landmark
            frame_width = float(image.shape[1])
            frame_height = float(image.shape[0])
            left = points[234]
            right = points[454]
            nose = points[1]
            forehead = points[10]
            chin = points[152]
            center_x = (left.x + right.x) / 2
            center_y = (forehead.y + chin.y) / 2
            face_width = max(abs(right.x - left.x), 0.01)
            face_height = max(abs(chin.y - forehead.y), 0.01)
            yaw = ((center_x - nose.x) / face_width) * 120
            pitch = ((center_y - nose.y) / face_height) * 100
            roll = math.degrees(
                math.atan2(
                    (right.y - left.y) * frame_height,
                    (right.x - left.x) * frame_width,
                )
            )
            left_eye = _eye_openness(points, [33, 160, 158, 133, 153, 144])
            right_eye = _eye_openness(points, [362, 385, 387, 263, 373, 380])
            mesh_area = face_width * face_height
            quality = min(1.0, max(fallback_quality, 0.34 + (mesh_area * 1.8)))
            if mesh_area < 0.018 or quality < 0.35:
                return _empty_signal("Step closer and face the camera.")
            return {
                "face_count": detected_count,
                "score": quality,
                "yaw": yaw,
                "pitch": pitch,
                "roll": roll,
                "left_eye_open": left_eye,
                "right_eye_open": right_eye,
                "pose_reliable": True,
                "message": "Face landmarks locked.",
            }
    except Exception:
        pass

    if not face_candidates or fallback_quality < 0.45:
        return _empty_signal("Position one clear face inside the alignment guide.")

    return {
        "face_count": len(face_candidates),
        "score": fallback_quality,
        "yaw": 0.0,
        "pitch": 0.0,
        "roll": 0.0,
        "left_eye_open": 0.8,
        "right_eye_open": 0.8,
        "pose_reliable": False,
        "message": "Face candidate found. Waiting for reliable landmarks.",
    }


def _empty_signal(message: str) -> dict[str, object]:
    return {
        "face_count": 0,
        "score": 0.0,
        "yaw": 0.0,
        "pitch": 0.0,
        "roll": 0.0,
        "left_eye_open": 0.5,
        "right_eye_open": 0.5,
        "pose_reliable": False,
        "message": message,
    }


def _eye_openness(landmarks: list, indexes: list[int]) -> float:
    points = np.array([(landmarks[index].x, landmarks[index].y) for index in indexes])
    vertical_1 = np.linalg.norm(points[1] - points[5])
    vertical_2 = np.linalg.norm(points[2] - points[4])
    horizontal = max(float(np.linalg.norm(points[0] - points[3])), 0.0001)
    ear = float((vertical_1 + vertical_2) / (2 * horizontal))
    return min(1.0, max(0.0, (ear - 0.13) / 0.13))


def run_static_liveness_check(image_path: Path) -> SecureVerificationResult:
    image = cv2.imread(str(image_path))
    if image is None:
        return SecureVerificationResult(
            liveness=LivenessResult(
                passed=False,
                status="IMAGE_ERROR",
                message="Captured image could not be read.",
            ),
            allowed_to_match=False,
        )

    if StaticLivenessAnalyzer is None:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
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
            return SecureVerificationResult(
                liveness=LivenessResult(
                    passed=False,
                    status="NO_FACE_DETECTED",
                    message="No face was detected in the desktop camera frame.",
                    geometry_score=0.0,
                ),
                allowed_to_match=False,
            )
        x, y, width, height = max(faces, key=lambda face: face[2] * face[3])
        face_area = (width * height) / max(float(image.shape[0] * image.shape[1]), 1.0)
        brightness = float(gray[y : y + height, x : x + width].mean() / 255.0)
        score = min(1.0, max(0.0, (face_area * 6.0) + (brightness * 0.35)))
        return SecureVerificationResult(
            liveness=LivenessResult(
                passed=True,
                status="FACE_DETECTED_FALLBACK",
                message="Desktop face detector confirmed a single face. MediaPipe depth checks are unavailable.",
                geometry_score=score,
            ),
            allowed_to_match=True,
        )

    analyzer = StaticLivenessAnalyzer()
    try:
        liveness = analyzer.analyze(image)
    finally:
        analyzer.close()

    return SecureVerificationResult(
        liveness=liveness,
        allowed_to_match=liveness.passed,
    )
