"""Unit tests for screen-change detection without real desktop capture."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
for entry in (ROOT, ROOT / "wboxai_app", ROOT / "audio_processing", ROOT / "llm_project"):
    value = str(entry.resolve())
    if value not in sys.path:
        sys.path.insert(0, value)

import screen_watcher


class ScreenWatcherTests(unittest.TestCase):
    def test_disabled_watcher_does_not_capture(self):
        watcher = screen_watcher.ScreenWatcher(on_change=lambda _: None)
        with patch.object(screen_watcher, "capture_screen_jpeg") as capture:
            changed, jpeg = watcher.capture_and_check()
        self.assertFalse(changed)
        self.assertEqual(jpeg, b"")
        capture.assert_not_called()

    def test_first_frame_establishes_baseline(self):
        watcher = screen_watcher.ScreenWatcher(on_change=lambda _: None)
        watcher.enabled = True
        frame = np.zeros((27, 48), dtype=np.int16)
        with patch.object(screen_watcher, "capture_screen_jpeg", return_value=b"jpeg"), patch.object(
            screen_watcher.ScreenWatcher, "_fingerprint", return_value=frame
        ):
            changed, jpeg = watcher.capture_and_check()
        self.assertFalse(changed)
        self.assertEqual(jpeg, b"jpeg")

    def test_large_visual_change_is_detected(self):
        watcher = screen_watcher.ScreenWatcher(on_change=lambda _: None)
        watcher.enabled = True
        baseline = np.zeros((27, 48), dtype=np.int16)
        changed_frame = np.full((27, 48), 100, dtype=np.int16)
        with patch.object(screen_watcher, "capture_screen_jpeg", return_value=b"jpeg"), patch.object(
            screen_watcher.ScreenWatcher,
            "_fingerprint",
            side_effect=[baseline, changed_frame],
        ):
            self.assertFalse(watcher.capture_and_check()[0])
            self.assertTrue(watcher.capture_and_check()[0])

    def test_small_change_below_threshold_is_ignored(self):
        watcher = screen_watcher.ScreenWatcher(on_change=lambda _: None)
        watcher.enabled = True
        baseline = np.zeros((27, 48), dtype=np.int16)
        slight_change = np.zeros((27, 48), dtype=np.int16)
        slight_change[0, 0] = 10
        with patch.object(screen_watcher, "capture_screen_jpeg", return_value=b"jpeg"), patch.object(
            screen_watcher.ScreenWatcher,
            "_fingerprint",
            side_effect=[baseline, slight_change],
        ):
            self.assertFalse(watcher.capture_and_check()[0])
            self.assertFalse(watcher.capture_and_check()[0])


if __name__ == "__main__":
    unittest.main()
