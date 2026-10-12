"""Capture screen for CoderPad / HackerRank (Windows 10/11)."""

from __future__ import annotations

import io
import mss
from PIL import Image

import config


def _grab_desktop(screen_info: dict | None = None) -> Image.Image:
    # MSS handles are thread-affine on Windows. A short-lived instance avoids
    # sharing one native handle across executor workers.
    with mss.mss() as sct:
        monitor = sct.monitors[0]
        if screen_info and len(sct.monitors) > 1:
            # Calculate the screen's logical center point coordinates
            cx = screen_info.get("x", 0) + screen_info.get("width", 0) // 2
            cy = screen_info.get("y", 0) + screen_info.get("height", 0) // 2
            
            # Find the physical monitor that contains this logical center point
            for m in sct.monitors[1:]:
                if (m["left"] <= cx < m["left"] + m["width"] and
                    m["top"] <= cy < m["top"] + m["height"]):
                    monitor = m
                    break
        try:
            shot = sct.grab(monitor)
            return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        except Exception:
            from PyQt6.QtGui import QGuiApplication, QImage
            app = QGuiApplication.instance()
            screen = app.primaryScreen() if app is not None else None
            if app is not None and screen_info:
                cx = screen_info.get("x", 0) + screen_info.get("width", 0) // 2
                cy = screen_info.get("y", 0) + screen_info.get("height", 0) // 2
                screen = next(
                    (item for item in app.screens() if item.geometry().contains(cx, cy)),
                    screen,
                )
            if screen is None:
                raise
            pixmap = screen.grabWindow(0)
            if pixmap.isNull():
                raise RuntimeError("MSS capture failed and Qt screen capture returned an empty image.")
            qimage = pixmap.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
            bits = qimage.bits()
            bits.setsize(qimage.sizeInBytes())
            return Image.frombytes(
                "RGBA",
                (qimage.width(), qimage.height()),
                bytes(bits),
                "raw",
                "RGBA",
            ).convert("RGB")


def capture_screen_jpeg(
    max_width: int | None = None,
    quality: int | None = None,
    screen_info: dict | None = None,
    crop: bool = True,
) -> bytes:
    """Capture desktop JPEG — call from background thread only (no Qt).
    
    When crop=False (e.g. for coding mode / multi-file assessments), full workspace
    is captured to preserve IDE file explorers, tab bars, and split editor windows.
    """
    max_width = max_width or config.SCREEN_CAPTURE_MAX_WIDTH
    quality = quality or config.SCREEN_CAPTURE_QUALITY

    img = _grab_desktop(screen_info)
    
    if crop:
        # Crop the image for standard browser / single window assessments:
        # - Exclude Chrome tabs/address bar (top 14%)
        # - Exclude Windows taskbar (bottom 7%)
        # - Exclude right 20% of screen width (where webcams or chat lists typically float)
        w, h = img.size
        top = int(h * 0.14)
        bottom = int(h * 0.93)
        right = int(w * 0.80)
        if bottom > top and right > 0:
            img = img.crop((0, top, right, bottom))
    else:
        # Light bottom crop only (exclude taskbar, preserve full top/left/right IDE workspace)
        w, h = img.size
        bottom = int(h * 0.96)
        if bottom > 0:
            img = img.crop((0, 0, w, bottom))

    if max_width and img.width > max_width:
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
