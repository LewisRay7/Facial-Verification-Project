from dataclasses import dataclass
import json
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


def generate_face_embedding(image_path: Path) -> tuple[str, str] | None:
    embedding = _generate_deepface_embedding(image_path)
    if embedding is None:
        return None
    return json.dumps(embedding), "DeepFace FaceNet embedding"


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
    reference_embedding: str | None = None,
    lightweight_threshold: float = LIGHTWEIGHT_MATCH_THRESHOLD,
    backend_preference: str = "auto",
) -> MatchResult:
    if backend_preference in ("auto", "facenet"):
        deepface_result = _verify_with_stored_embedding(reference_embedding, live_image)
        if deepface_result is None:
            deepface_result = _verify_with_deepface(reference_image, live_image)
        if deepface_result is not None:
            return deepface_result
        if backend_preference == "facenet":
            raise FaceMatchError(
                "FaceNet could not complete verification. Use OpenCV fallback for demo, "
                "or close other apps and try FaceNet again."
            )
    return _verify_with_opencv(reference_image, live_image, lightweight_threshold)


def _generate_deepface_embedding(image_path: Path) -> list[float] | None:
    try:
        from deepface import DeepFace
    except Exception:
        return None

    try:
        representations = DeepFace.represent(
            img_path=str(image_path),
            model_name="Facenet",
            detector_backend="opencv",
            enforce_detection=True,
            align=True,
        )
    except Exception:
        return None

    if not representations:
        return None
    embedding = representations[0].get("embedding")
    if not embedding:
        return None
    return [float(value) for value in embedding]


def _verify_with_stored_embedding(
    reference_embedding: str | None,
    live_image: Path,
) -> MatchResult | None:
    if not reference_embedding:
        return None

    try:
        reference_vector = np.array(json.loads(reference_embedding), dtype=np.float32)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None

    live_embedding = _generate_deepface_embedding(live_image)
    if live_embedding is None:
        return None

    live_vector = np.array(live_embedding, dtype=np.float32)
    distance = _cosine_distance(reference_vector, live_vector)
    is_match = distance <= FACE_MATCH_THRESHOLD
    return MatchResult(
        is_match=is_match,
        score=distance,
        backend="Stored FaceNet embedding",
        message=(
            "Compared the live face with the stored student embedding. "
            "Lower score means the faces are more similar."
        ),
    )


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


def _cosine_distance(vector_a: np.ndarray, vector_b: np.ndarray) -> float:
    denominator = np.linalg.norm(vector_a) * np.linalg.norm(vector_b)
    if denominator == 0:
        return 1.0
    similarity = float(np.dot(vector_a, vector_b) / denominator)
    return 1 - similarity
