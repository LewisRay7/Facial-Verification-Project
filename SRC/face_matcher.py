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


@dataclass
class IdentificationResult:
    student_id: int | None
    is_match: bool
    status: str
    score: float
    second_best_score: float | None
    suggested_threshold: float
    ranked_matches: list[tuple[int, float]]
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
    facenet_threshold: float = FACE_MATCH_THRESHOLD,
    lightweight_threshold: float = LIGHTWEIGHT_MATCH_THRESHOLD,
    backend_preference: str = "auto",
) -> MatchResult:
    if backend_preference in ("auto", "facenet"):
        deepface_result = _verify_with_stored_embedding(
            reference_embedding,
            live_image,
            facenet_threshold,
        )
        if deepface_result is None:
            deepface_result = _verify_with_deepface(
                reference_image,
                live_image,
                facenet_threshold,
            )
        if deepface_result is not None:
            return deepface_result
        if backend_preference == "facenet":
            raise FaceMatchError(
                "FaceNet could not complete verification. Capture a clearer front-facing "
                "image with better lighting, or use Auto so the system can fall back to "
                "OpenCV for the demo."
            )
    return _verify_with_opencv(reference_image, live_image, lightweight_threshold)


def identify_face_from_embeddings(
    live_image: Path,
    candidates: list[dict],
    facenet_threshold: float = 0.60,
    min_distance_gap: float = 0.08,
    low_confidence_margin: float = 0.12,
) -> IdentificationResult:
    usable_candidates = [
        candidate for candidate in candidates if candidate.get("face_embedding")
    ]
    if not usable_candidates:
        raise FaceMatchError(
            "No active students have stored FaceNet embeddings yet. Generate embeddings "
            "from the Students page after installing the optional FaceNet backend."
        )

    live_embedding = _generate_deepface_embedding(live_image)
    if live_embedding is None:
        raise FaceMatchError(
            "FaceNet could not create an embedding from the live camera image. Capture "
            "a clearer front-facing image with better lighting."
        )

    live_vector = _l2_normalize(np.array(live_embedding, dtype=np.float32))
    ranked_matches: list[tuple[float, int]] = []

    for candidate in usable_candidates:
        try:
            reference_vector = _l2_normalize(
                np.array(
                    json.loads(candidate["face_embedding"]),
                    dtype=np.float32,
                )
            )
        except (TypeError, ValueError, json.JSONDecodeError):
            continue

        distance = _euclidean_distance(reference_vector, live_vector)
        ranked_matches.append((distance, int(candidate["id"])))

    if not ranked_matches:
        raise FaceMatchError(
            "No valid stored FaceNet embeddings were found. Refresh student embeddings "
            "from the Students page."
        )

    ranked_matches.sort(key=lambda match: match[0])
    best_distance, best_student_id = ranked_matches[0]
    second_best_distance = ranked_matches[1][0] if len(ranked_matches) > 1 else None
    ranked_result = [
        (student_id, distance) for distance, student_id in ranked_matches[:5]
    ]
    suggested_threshold = _suggest_identification_threshold(
        best_distance,
        second_best_distance,
        facenet_threshold,
    )

    has_clear_gap = (
        second_best_distance is None
        or second_best_distance - best_distance >= min_distance_gap
    )

    if best_distance <= facenet_threshold and has_clear_gap:
        return IdentificationResult(
            student_id=best_student_id,
            is_match=True,
            status="VERIFIED",
            score=best_distance,
            second_best_score=second_best_distance,
            suggested_threshold=suggested_threshold,
            ranked_matches=ranked_result,
            backend="Stored FaceNet embedding search",
            message=(
                "Compared L2-normalized live and stored FaceNet embeddings. Lower distance "
                "means the faces are more similar."
            ),
        )

    low_confidence_limit = facenet_threshold + low_confidence_margin
    if best_distance <= low_confidence_limit and has_clear_gap:
        return IdentificationResult(
            student_id=best_student_id,
            is_match=False,
            status="LOW_CONFIDENCE",
            score=best_distance,
            second_best_score=second_best_distance,
            suggested_threshold=suggested_threshold,
            ranked_matches=ranked_result,
            backend="Stored FaceNet embedding search",
            message=(
                "The closest face is slightly above the threshold. Review the live image, "
                "lighting, and stored student photo before allowing exam entry."
            ),
        )

    return IdentificationResult(
        student_id=None,
        is_match=False,
        status="UNKNOWN",
        score=best_distance,
        second_best_score=second_best_distance,
        suggested_threshold=suggested_threshold,
        ranked_matches=ranked_result,
        backend="Stored FaceNet embedding search",
        message=(
            "Unknown student. The closest face was too far from the threshold or too "
            "close to another registered student."
        ),
    )


def _generate_deepface_embedding(image_path: Path) -> list[float] | None:
    try:
        from deepface import DeepFace
    except Exception:
        return None

    for enforce_detection in (True, False):
        try:
            representations = DeepFace.represent(
                img_path=str(image_path),
                model_name="Facenet",
                detector_backend="opencv",
                enforce_detection=enforce_detection,
                align=True,
            )
        except Exception:
            continue

        if not representations:
            continue
        embedding = representations[0].get("embedding")
        if embedding:
            return [float(value) for value in embedding]
    return None


def _verify_with_stored_embedding(
    reference_embedding: str | None,
    live_image: Path,
    facenet_threshold: float,
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
    is_match = distance <= facenet_threshold
    return MatchResult(
        is_match=is_match,
        score=distance,
        backend="Stored FaceNet embedding",
        message=(
            "Compared the live face with the stored student embedding. "
            "Lower score means the faces are more similar."
        ),
    )


def _verify_with_deepface(
    reference_image: Path,
    live_image: Path,
    facenet_threshold: float,
) -> MatchResult | None:
    try:
        from deepface import DeepFace
    except Exception:
        return None

    result = None
    for enforce_detection in (True, False):
        try:
            result = DeepFace.verify(
                img1_path=str(reference_image),
                img2_path=str(live_image),
                model_name="Facenet",
                detector_backend="opencv",
                distance_metric="cosine",
                enforce_detection=enforce_detection,
                align=True,
            )
            break
        except Exception:
            continue
    if result is None:
        return None

    distance = float(result.get("distance", 1.0))
    is_match = distance <= facenet_threshold
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


def _l2_normalize(vector: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(vector)
    if norm == 0:
        return vector
    return vector / norm


def _euclidean_distance(vector_a: np.ndarray, vector_b: np.ndarray) -> float:
    return float(np.linalg.norm(vector_a - vector_b))


def _suggest_identification_threshold(
    best_distance: float,
    second_best_distance: float | None,
    current_threshold: float,
) -> float:
    if second_best_distance is None:
        return round(max(current_threshold, best_distance + 0.03), 2)
    midpoint = (best_distance + second_best_distance) / 2
    suggested = min(max(best_distance + 0.03, current_threshold), midpoint)
    return round(float(suggested), 2)
