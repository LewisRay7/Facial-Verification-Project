from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "Data"
PHOTO_DIR = DATA_DIR / "student_photos"
CAPTURE_DIR = DATA_DIR / "captures"
DB_PATH = DATA_DIR / "exam_verification.db"

FACE_MATCH_THRESHOLD = 0.45
LIGHTWEIGHT_MATCH_THRESHOLD = 0.05
MAX_IMAGE_SIZE = 900


def ensure_directories() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    PHOTO_DIR.mkdir(exist_ok=True)
    CAPTURE_DIR.mkdir(exist_ok=True)
