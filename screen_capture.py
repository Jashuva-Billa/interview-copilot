"""Capture screen for CoderPad / HackerRank (Windows + macOS)."""

from __future__ import annotations

import io

import mss
from PIL import Image

import config

_mss = None


def _get_mss():
    global _mss
    if _mss is None:
        _mss = mss.mss()
    return _mss


def _grab_desktop() -> Image.Image:
    sct = _get_mss()
    monitor = sct.monitors[0]
    shot = sct.grab(monitor)
    return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")


def capture_screen_jpeg(
    max_width: int | None = None,
    quality: int | None = None,
) -> bytes:
    """Capture desktop JPEG — call from background thread only (no Qt)."""
    max_width = max_width or config.SCREEN_CAPTURE_MAX_WIDTH
    quality = quality or config.SCREEN_CAPTURE_QUALITY

    img = _grab_desktop()
    if img.width > max_width:
        h = max(1, int(img.height * max_width / img.width))
        resample = (
            Image.Resampling.BILINEAR
            if config.LIGHTWEIGHT_MODE
            else Image.Resampling.LANCZOS
        )
        img = img.resize((max_width, h), resample)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()
