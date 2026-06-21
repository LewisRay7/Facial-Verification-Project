from __future__ import annotations

import json
from pathlib import Path
import unittest
from unittest.mock import patch

from SRC.face_matcher import _verify_with_stored_embedding


class FaceMatcherProfileTests(unittest.TestCase):
    def test_selected_student_uses_closest_approved_embedding_sample(self) -> None:
        stored = json.dumps(
            [
                [1.0, 0.0, 0.0],
                [0.0, 1.0, 0.0],
            ]
        )
        with patch(
            "SRC.face_matcher._generate_deepface_embedding",
            return_value=[0.0, 1.0, 0.0],
        ):
            result = _verify_with_stored_embedding(
                stored,
                Path("live.jpg"),
                facenet_threshold=0.20,
            )

        self.assertIsNotNone(result)
        self.assertTrue(result.is_match)
        self.assertAlmostEqual(result.score, 0.0)


if __name__ == "__main__":
    unittest.main()
