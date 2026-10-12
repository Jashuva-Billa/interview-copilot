"""Auto-detect screen changes (background-thread safe)."""

from __future__ import annotations

import io
from typing import Callable, Optional, Tuple

import numpy as np

from PIL import Image

import config
from screen_capture import capture_screen_jpeg


class ScreenWatcher:
    def __init__(self, on_change: Callable[[bytes], None]):
        self.on_change = on_change
        self._last_frame: Optional[np.ndarray] = None
        self.enabled = False

    def reset(self) -> None:
        self._last_frame = None


    @staticmethod
    def _fingerprint(jpeg_bytes: bytes) -> np.ndarray:
        img = Image.open(io.BytesIO(jpeg_bytes))
        img = img.convert("L").resize((48, 27), Image.Resampling.NEAREST)
        return np.asarray(img, dtype=np.int16)

    def capture_and_check(self, screen_info: dict | None = None) -> Tuple[bool, bytes]:
        """
        Capture screen and return (changed, jpeg).
        Run in worker thread — no Qt calls.
        """
        if not self.enabled:
            return False, b""

        jpeg = capture_screen_jpeg(quality=65, screen_info=screen_info)
        frame = self._fingerprint(jpeg)
        if self._last_frame is None:
            self._last_frame = frame
            return False, jpeg
        # Ignore cursors, carets, clocks, and compression noise. A meaningful
        # change must affect either 4% of the thumbnail or its average value.
        delta = np.abs(frame - self._last_frame)
        changed = float(np.mean(delta > 18)) >= 0.04 or float(np.mean(delta)) >= 5.0
        if changed:
            self._last_frame = frame
            return True, jpeg
        return False, jpeg
