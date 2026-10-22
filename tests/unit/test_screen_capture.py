"""Unit tests for screenshot crop, resize, and JPEG encoding."""
from __future__ import annotations

import io
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
for entry in (ROOT, ROOT / "wboxai_app", ROOT / "audio_processing", ROOT / "llm_project"):
    value = str(entry.resolve())
    if value not in sys.path:
        sys.path.insert(0, value)

import screen_capture


class ScreenCaptureTests(unittest.TestCase):
    def test_capture_returns_valid_jpeg_and_respects_width_limit(self):
        source = Image.new("RGB", (1600, 900), "navy")
        with patch.object(screen_capture, "_grab_desktop", return_value=source), patch.object(
            screen_capture.config, "LIGHTWEIGHT_MODE", True
        ):
            data = screen_capture.capture_screen_jpeg(max_width=640, quality=70, crop=False)
        decoded = Image.open(io.BytesIO(data))
        self.assertEqual(decoded.format, "JPEG")
        self.assertEqual(decoded.width, 640)
        self.assertGreater(decoded.height, 0)

    def test_crop_false_preserves_more_workspace_than_default_crop(self):
        source = Image.new("RGB", (1000, 800), "navy")
        with patch.object(screen_capture, "_grab_desktop", return_value=source), patch.object(
            screen_capture.config, "LIGHTWEIGHT_MODE", True
        ):
            cropped = Image.open(io.BytesIO(screen_capture.capture_screen_jpeg(max_width=2000, crop=True)))
            full = Image.open(io.BytesIO(screen_capture.capture_screen_jpeg(max_width=2000, crop=False)))
        self.assertLess(cropped.width, full.width)
        self.assertLess(cropped.height, full.height)


if __name__ == "__main__":
    unittest.main()
