from __future__ import annotations

from pathlib import Path
import unittest
from unittest.mock import Mock, patch

import numpy as np

from SRC.face_verification.secure_pipeline import run_static_liveness_check


class LivenessSafetyTests(unittest.TestCase):
    def test_static_liveness_pauses_when_multiple_faces_are_detected(self) -> None:
        detector = Mock()
        detector.detectMultiScale.return_value = np.array(
            [[10, 10, 100, 100], [150, 10, 100, 100]]
        )
        with (
            patch(
                "SRC.face_verification.secure_pipeline.cv2.imread",
                return_value=np.zeros((300, 300, 3), dtype=np.uint8),
            ),
            patch(
                "SRC.face_verification.secure_pipeline.cv2.CascadeClassifier",
                return_value=detector,
            ),
        ):
            result = run_static_liveness_check(Path("crowd.jpg"))

        self.assertFalse(result.allowed_to_match)
        self.assertEqual(result.liveness.status, "MULTIPLE_FACES")


if __name__ == "__main__":
    unittest.main()
