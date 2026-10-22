"""Unit tests for Assessment mode and multi-screenshot handling."""

from __future__ import annotations

import sys
from pathlib import Path

# Bootstrap paths before importing packages
_root = Path(__file__).resolve().parents[2]
for _p in (_root, _root / "wboxai_app", _root / "audio_processing", _root / "llm_project"):
    _p_str = str(_p.resolve())
    if _p_str not in sys.path:
        sys.path.insert(0, _p_str)

import unittest
from unittest.mock import MagicMock, patch
from llm_project.openai_service import solve_assessment_multi_image, ASSESSMENT_MODE_SYSTEM_PROMPT


class TestAssessmentMode(unittest.TestCase):
    def test_assessment_prompt_identity(self):
        self.assertIn("You are a coding expert helping me in my project", ASSESSMENT_MODE_SYSTEM_PROMPT)
        self.assertIn("I need ONLY the code in assessment mode and NO explanations", ASSESSMENT_MODE_SYSTEM_PROMPT)

    def test_solve_assessment_empty_images(self):
        problem, parsed = solve_assessment_multi_image([])
        self.assertEqual(problem, "No screenshots provided.")
        self.assertTrue(parsed.is_coding)
        self.assertIn("No screenshots captured", parsed.approach)

    @patch("llm_project.openai_service._client")
    def test_solve_assessment_multi_image_mock(self, mock_client_fn):
        mock_client = MagicMock()
        mock_client_fn.return_value = mock_client

        # Mock streaming response
        mock_chunk = MagicMock()
        mock_chunk.choices = [MagicMock()]
        mock_chunk.choices[0].delta.content = "```python\n# === FILE: main.py ===\nprint('Hello World')\n```"
        mock_client.chat.completions.create.return_value = [mock_chunk]

        fake_images = [b"fake_jpeg_1", b"fake_jpeg_2"]
        problem, parsed = solve_assessment_multi_image(fake_images)

        self.assertTrue(parsed.is_coding)
        self.assertIn("# === FILE: main.py ===", parsed.code)
        self.assertIn("print('Hello World')", parsed.code)
        self.assertIn("2 captured screenshot(s)", parsed.problem_text)


if __name__ == "__main__":
    unittest.main()
