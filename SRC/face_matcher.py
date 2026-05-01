from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from .config import FACE_MATCH_THRESHOLD, LIGHTWEIGHT_MATCH_THRESHOLD, MAX_IMAGE_SIZE


@dataclass
class MatchResult:
    is_match: bool
    score: float
    backend: str
    message: str


class FaceMatchError(RuntimeError):
    pass


def save_uploaded_image(uploaded_file, destination: Path) -> Path:
    destination.parent.mkdir(exist_ok=True)
    image = Image.open(uploaded_file).convert("RGB")
    image.thumbnail((MAX_IMAGE_SIZE, MAX_IMAGE_SIZE))
    image.save(destination, format="JPEG", quality=88)
    return destination


def save_camera_image(image_file, destination: Path) -> Path:
    destination.parent.mkdir(exist_ok=True)
    image = Image.open(image_file).convert("RGB")
    image.thumbnail((MAX_IMAGE_SIZE, MAX_IMAGE_SIZE))
    image.save(destination, format="JPEG", quality=88)
    return destination


def verify_faces(
    reference_image: Path,
    live_image: Path,
    lightweight_threshold: float = LIGHTWEIGHT_MATCH_THRESHOLD,
    backend_preference: str = "auto",
) -> MatchResult:
    if backend_preference in ("auto", "facenet"):
        deepface_result = _verify_with_deepface(reference_image, live_image)
        if deepface_result is not None:
            return deepface_result
        if backend_preference == "facenet":
            raise FaceMatchError(
                "FaceNet could not complete verification. Use OpenCV fallback for demo, "
                "or close other apps and try FaceNet again."
            )
    return _verify_with_opencv(reference_image, live_image, lightweight_threshold)


def _verify_with_deepface(reference_image: Path, live_image: Path) -> MatchResult | None:
    try:
        from deepface import DeepFace
    except Exception:
        return None

    try:
        result = DeepFace.verify(
            img1_path=str(reference_image),
            img2_path=str(live_image),
            model_name="Facenet",
            detector_backend="opencv",
            distance_metric="cosine",
            enforce_detection=True,
            align=True,
        )
    except Exception:
        return None

    distance = float(result.get("distance", 1.0))
    is_match = distance <= FACE_MATCH_THRESHOLD
    return MatchResult(
        is_match=is_match,
        score=distance,
        backend="DeepFace FaceNet",
        message="Lower score means the faces are more similar.",
    )


def _verify_with_opencv(
    reference_image: Path,
    live_image: Path,
    lightweight_threshold: float,
) -> MatchResult:
    reference_face = _read_largest_face(reference_image)
    live_face = _read_largest_face(live_image)

    if reference_face is None:
        raise FaceMatchError("No face was detected in the registered student photo.")
    if live_face is None:
        raise FaceMatchError("No face was detected in the live camera image.")

    reference_vector = _histogram_embedding(reference_face)
    live_vector = _histogram_embedding(live_face)
    similarity = float(cv2.compareHist(reference_vector, live_vector, cv2.HISTCMP_CORREL))
    is_match = similarity >= lightweight_threshold

    return MatchResult(
        is_match=is_match,
        score=similarity,
        backend="OpenCV lightweight fallback",
        message="Higher score means the faces are more similar.",
    )


def _read_largest_face(path: Path) -> np.ndarray | None:
    image = cv2.imread(str(path))
    if image is None:
        raise FaceMatchError(f"Could not read image: {path}")

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    face_cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )
    faces = face_cascade.detectMultiScale(
        gray,
        scaleFactor=1.1,
        minNeighbors=5,
        minSize=(70, 70),
    )
    if len(faces) == 0:
        return None

    x, y, width, height = max(faces, key=lambda face: face[2] * face[3])
    face = image[y : y + height, x : x + width]
    return cv2.resize(face, (160, 160))


def _histogram_embedding(face_image: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(face_image, cv2.COLOR_BGR2HSV)
    histogram = cv2.calcHist([hsv], [0, 1], None, [48, 48], [0, 180, 0, 256])
    cv2.normalize(histogram, histogram, alpha=0, beta=1, norm_type=cv2.NORM_MINMAX)
    return histogram
