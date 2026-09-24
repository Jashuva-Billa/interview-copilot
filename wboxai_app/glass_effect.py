"""Frosted glass backdrop — Windows acrylic/blur via SetWindowCompositionAttribute."""

from __future__ import annotations

import sys
from typing import Any


def _native_hwnd(widget: Any) -> int:
    handle = widget.windowHandle()
    if handle is not None:
        wid = int(handle.winId())
        if wid:
            return wid
    return int(widget.winId())


def _abgr_tint(percent: float) -> int:
    """Windows blur tint — below 2% use blur-only (no white wash)."""
    if percent <= 0:
        return 0
    # Minimal blur: soften edge vs desktop, no milky overlay
    if percent < 2.0:
        return 0
    alpha = int(10 + (245 * (percent - 2.0) / 98.0))
    alpha = max(10, min(255, alpha))
    return (alpha << 24) | 0x00FFFFFF


def _apply_windows_blur(hwnd: int, blur_percent: float) -> bool:
    if not hwnd:
        return False
    try:
        import ctypes
        from ctypes import Structure, byref, c_int, c_void_p, sizeof, windll
        from ctypes import wintypes

        class ACCENT_POLICY(Structure):
            _fields_ = [
                ("AccentState", c_int),
                ("AccentFlags", c_int),
                ("GradientColor", c_int),
                ("AnimationId", c_int),
            ]

        class WINDOWCOMPOSITIONATTRIBDATA(Structure):
            _fields_ = [
                ("Attribute", c_int),
                ("Data", c_void_p),
                ("SizeOfData", c_int),
            ]

        accent = ACCENT_POLICY()
        if blur_percent <= 0:
            accent.AccentState = 0  # ACCENT_DISABLED
            accent.GradientColor = 0
        else:
            accent.AccentState = 3  # ACCENT_ENABLE_BLURBEHIND
            accent.GradientColor = _abgr_tint(blur_percent)
        accent.AccentFlags = 0

        data = WINDOWCOMPOSITIONATTRIBDATA()
        data.Attribute = 19  # WCA_ACCENT_POLICY
        data.SizeOfData = sizeof(accent)
        data.Data = ctypes.addressof(accent)
        set_attr = windll.user32.SetWindowCompositionAttribute
        set_attr.argtypes = [wintypes.HWND, ctypes.POINTER(WINDOWCOMPOSITIONATTRIBDATA)]
        set_attr.restype = wintypes.BOOL
        return bool(set_attr(hwnd, byref(data)))
    except Exception:
        return False


def apply_glass_backdrop(widget: Any, blur_percent: float | None = None) -> bool:
    """Enable Windows OS-level blur; blur_percent 0–100 (default from config, e.g. 0.5)."""
    import config

    pct = config.GLASS_BLUR_PERCENT if blur_percent is None else blur_percent
    hwnd = _native_hwnd(widget)
    return _apply_windows_blur(hwnd, pct)
