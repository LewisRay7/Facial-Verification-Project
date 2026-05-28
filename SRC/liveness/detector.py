from __future__ import annotations

from dataclasses import dataclass, field
import math
import random
import time
from typing import Iterable

import cv2
import mediapipe as mp
import numpy as np
from scipy.spatial import distance


LEFT_EYE = [33, 160, 158, 133, 153, 144]
RIGHT_EYE = [362, 385, 387, 263, 373, 380]
FACE_OVAL = [10, 152, 234, 454]
NOSE_TIP = 1
LEFT_CHEEK = 234
RIGHT_CHEEK = 454
FOREHEAD = 10
CHIN = 152


@dataclass
class LivenessResult:
    passed: bool
    status: str
    message: str
    blink_count: int = 0
    challenge: str = ""
    geometry_score: float = 0.0
    spoof_reasons: list[str] = field(default_factory=list)


@dataclass
class LivenessState:
    started_at: float
    challenge: str
    blink_count: int = 0
    eyes_closed: bool = False
    challenge_passed: bool = False
    geometry_passed: bool = False
    best_frame: np.ndarray | None = None
    status: str = "Position your face in the frame"
    spoof_reasons: list[str] = field(default_factory=list)


class LivenessPipeline:
    """MediaPipe Face Mesh liveness pipeline for real-time webcam frames."""

    def __init__(self, required_blinks: int = 2, timeout_seconds: float = 25.0) -> None:
        self.required_blinks = required_blinks
        self.timeout_seconds = timeout_seconds
        self.face_mesh = mp.solutions.face_mesh.FaceMesh(
            static_image_mode=False,
            max_num_faces=1,
            refine_landmarks=True,
            min_detection_confidence=0.55,
            min_tracking_confidence=0.55,
        )
        self.state = LivenessState(
            started_at=time.perf_counter(),
            challenge=random.choice(["turn left", "turn right", "look up"]),
        )

    def close(self) -> None:
        self.face_mesh.close()

    def process(self, frame_bgr: np.ndarray) -> LivenessResult:
        elapsed = time.perf_counter() - self.state.started_at
        if elapsed > self.timeout_seconds:
            return LivenessResult(
                passed=False,
                status="TIMEOUT",
                message="Liveness challenge timed out. Try again with better lighting.",
                blink_count=self.state.blink_count,
                challenge=self.state.challenge,
                geometry_score=0.0,
                spoof_reasons=self.state.spoof_reasons,
            )

        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        results = self.face_mesh.process(rgb)
        if not results.multi_face_landmarks:
            self.state.status = "No face detected"
            return self._result(False, "SCANNING", self.state.status)

        landmarks = results.multi_face_landmarks[0].landmark
        height, width = frame_bgr.shape[:2]
        points = _landmark_points(landmarks, width, height)

        ear = (_eye_aspect_ratio(points, LEFT_EYE) + _eye_aspect_ratio(points, RIGHT_EYE)) / 2
        if ear < 0.19 and not self.state.eyes_closed:
            self.state.eyes_closed = True
        elif ear > 0.24 and self.state.eyes_closed:
            self.state.eyes_closed = False
            self.state.blink_count += 1

        pose = _estimate_pose(points)
        self.state.challenge_passed = self.state.challenge_passed or _challenge_met(
            self.state.challenge,
            pose,
        )

        geometry_score, geometry_reasons = _geometry_score(points)
        self.state.geometry_passed = geometry_score >= 0.58
        self.state.spoof_reasons = geometry_reasons

        if self.state.blink_count < self.required_blinks:
            self.state.status = f"Blink twice ({self.state.blink_count}/{self.required_blinks})"
        elif not self.state.challenge_passed:
            self.state.status = f"Challenge: {self.state.challenge}"
        elif not self.state.geometry_passed:
            self.state.status = "Checking facial depth consistency"
        else:
            self.state.best_frame = frame_bgr.copy()
            return self._result(
                True,
                "LIVE",
                "Liveness verified. Face movement and 3D geometry checks passed.",
                geometry_score,
            )

        return self._result(False, "SCANNING", self.state.status, geometry_score)

    def _result(
        self,
        passed: bool,
        status: str,
        message: str,
        geometry_score: float = 0.0,
    ) -> LivenessResult:
        return LivenessResult(
            passed=passed,
            status=status,
            message=message,
            blink_count=self.state.blink_count,
            challenge=self.state.challenge,
            geometry_score=geometry_score,
            spoof_reasons=self.state.spoof_reasons,
        )


class StaticLivenessAnalyzer:
    """Fallback pseudo-3D geometry analyzer for captured still images."""

    def __init__(self) -> None:
        self.face_mesh = mp.solutions.face_mesh.FaceMesh(
            static_image_mode=True,
            max_num_faces=1,
            refine_landmarks=True,
            min_detection_confidence=0.55,
        )

    def close(self) -> None:
        self.face_mesh.close()

    def analyze(self, image_bgr: np.ndarray) -> LivenessResult:
        rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
        results = self.face_mesh.process(rgb)
        if not results.multi_face_landmarks:
            return LivenessResult(
                passed=False,
                status="NO_FACE",
                message="No face mesh was detected.",
                spoof_reasons=["No 468-point face mesh detected"],
            )
        height, width = image_bgr.shape[:2]
        points = _landmark_points(results.multi_face_landmarks[0].landmark, width, height)
        score, reasons = _geometry_score(points)
        passed = score >= 0.58
        return LivenessResult(
            passed=passed,
            status="LIVE" if passed else "SPOOF_DETECTED",
            message=(
                "Pseudo-3D facial geometry is consistent."
                if passed
                else "Flat or inconsistent face geometry detected."
            ),
            geometry_score=score,
            spoof_reasons=reasons,
        )


def _landmark_points(landmarks: Iterable, width: int, height: int) -> dict[int, tuple[float, float, float]]:
    return {
        index: (landmark.x * width, landmark.y * height, landmark.z * width)
        for index, landmark in enumerate(landmarks)
    }


def _eye_aspect_ratio(points: dict[int, tuple[float, float, float]], indexes: list[int]) -> float:
    p = [points[index] for index in indexes]
    vertical_1 = distance.euclidean(p[1][:2], p[5][:2])
    vertical_2 = distance.euclidean(p[2][:2], p[4][:2])
    horizontal = distance.euclidean(p[0][:2], p[3][:2])
    return float((vertical_1 + vertical_2) / (2.0 * max(horizontal, 1.0)))


def _estimate_pose(points: dict[int, tuple[float, float, float]]) -> dict[str, float]:
    nose_x, nose_y, _ = points[NOSE_TIP]
    left_x, _, _ = points[LEFT_CHEEK]
    right_x, _, _ = points[RIGHT_CHEEK]
    forehead_y = points[FOREHEAD][1]
    chin_y = points[CHIN][1]
    face_width = max(abs(right_x - left_x), 1.0)
    face_height = max(abs(chin_y - forehead_y), 1.0)
    center_x = (left_x + right_x) / 2
    center_y = (forehead_y + chin_y) / 2
    return {
        "yaw": (nose_x - center_x) / face_width,
        "pitch": (nose_y - center_y) / face_height,
    }


def _challenge_met(challenge: str, pose: dict[str, float]) -> bool:
    if challenge == "turn left":
        return pose["yaw"] < -0.075
    if challenge == "turn right":
        return pose["yaw"] > 0.075
    if challenge == "look up":
        return pose["pitch"] < -0.08
    return False


def _geometry_score(points: dict[int, tuple[float, float, float]]) -> tuple[float, list[str]]:
    nose_z = points[NOSE_TIP][2]
    cheek_z = (points[LEFT_CHEEK][2] + points[RIGHT_CHEEK][2]) / 2
    forehead_z = points[FOREHEAD][2]
    chin_z = points[CHIN][2]
    depth_range = max(point[2] for point in points.values()) - min(point[2] for point in points.values())
    face_width = abs(points[RIGHT_CHEEK][0] - points[LEFT_CHEEK][0])

    normalized_depth = depth_range / max(face_width, 1.0)
    nose_prominence = abs(nose_z - cheek_z) / max(face_width, 1.0)
    vertical_depth = abs(forehead_z - chin_z) / max(face_width, 1.0)

    components = [
        min(normalized_depth / 0.18, 1.0),
        min(nose_prominence / 0.045, 1.0),
        min(vertical_depth / 0.025, 1.0),
    ]
    score = float(sum(components) / len(components))
    reasons: list[str] = []
    if normalized_depth < 0.10:
        reasons.append("Low landmark depth variation")
    if nose_prominence < 0.025:
        reasons.append("Weak nose-to-cheek depth relationship")
    if math.isnan(score) or score < 0.58:
        reasons.append("Facial geometry resembles a flat image")
    return score, reasons
