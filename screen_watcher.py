"""Auto-detect screen changes (background-thread safe)."""

from __future__ import annotations

import hashlib
import io
from typing import Callable, Optional, Tuple

from PIL import Image

import config
from screen_capture import capture_screen_jpeg


class ScreenWatcher:
    def __init__(self, on_change: Callable[[bytes], None]):
        self.on_change = on_change
        self._last_hash: Optional[str] = None
        self.enabled = False

    def reset(self) -> None:
        self._last_hash = None

    @staticmethod
    def _fingerprint(jpeg_bytes: bytes) -> str:
        img = Image.open(io.BytesIO(jpeg_bytes))
        img = img.convert("L").resize((48, 27), Image.Resampling.NEAREST)
        return hashlib.md5(img.tobytes()).hexdigest()

    def capture_and_check(self) -> Tuple[bool, bytes]:
        """
        Capture screen and return (changed, jpeg).
        Run in worker thread — no Qt calls.
        """
        if not self.enabled:
            return False, b""

        jpeg = capture_screen_jpeg(quality=65)
        fp = self._fingerprint(jpeg)
        if self._last_hash is None:
            self._last_hash = fp
            return False, jpeg
        if fp != self._last_hash:
            self._last_hash = fp
            return True, jpeg
        return False, jpeg
