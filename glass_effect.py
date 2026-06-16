"""Frosted glass backdrop — Windows acrylic / macOS vibrancy when available."""

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
    alpha = max(0, min(32, int(255 * percent / 100)))
    return (alpha << 24) | 0x00FFFFFF


def _apply_windows_blur(hwnd: int, blur_percent: float) -> bool:
    if sys.platform != "win32" or not hwnd or blur_percent <= 0:
        return False
    try:
        import ctypes
        from ctypes import Structure, byref, c_int, c_void_p, sizeof, windll

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
        accent.AccentState = 3  # ACCENT_ENABLE_BLURBEHIND
        accent.AccentFlags = 0
        accent.GradientColor = _abgr_tint(blur_percent)

        data = WINDOWCOMPOSITIONATTRIBDATA()
        data.Attribute = 19  # WCA_ACCENT_POLICY
        data.SizeOfData = sizeof(accent)
        data.Data = ctypes.addressof(accent)
        set_attr = windll.user32.SetWindowCompositionAttribute
        return bool(set_attr(hwnd, byref(data)))
    except Exception:
        return False


def _apply_macos_vibrancy(widget: Any, blur_percent: float) -> bool:
    if sys.platform != "darwin" or blur_percent <= 0:
        return False
    try:
        import objc
        from ctypes import c_void_p

        from Cocoa import NSVisualEffectMaterialHUDWindow, NSVisualEffectStateActive

        wid = _native_hwnd(widget)
        if not wid:
            return False
        obj = objc.objc_object(c_void_p=wid)
        ns_window = obj.window()
        if ns_window is None:
            return False
        content = ns_window.contentView()
        if content is None:
            return False
        from AppKit import NSVisualEffectView

        effect = NSVisualEffectView.alloc().initWithFrame_(content.bounds())
        effect.setMaterial_(NSVisualEffectMaterialHUDWindow)
        effect.setState_(NSVisualEffectStateActive)
        effect.setBlendingMode_(0)
        effect.setAlphaValue_(max(0.05, min(1.0, blur_percent / 100.0)))
        content.addSubview_positioned_relativeTo_(effect, 0, None)
        return True
    except Exception:
        return False


def apply_glass_backdrop(widget: Any, blur_percent: float | None = None) -> bool:
    """Enable OS-level blur; blur_percent 0–100 (default from config, e.g. 0.5)."""
    import config

    pct = config.GLASS_BLUR_PERCENT if blur_percent is None else blur_percent
    if pct <= 0:
        return False
    hwnd = _native_hwnd(widget)
    if sys.platform == "win32":
        return _apply_windows_blur(hwnd, pct)
    if sys.platform == "darwin":
        return _apply_macos_vibrancy(widget, pct)
    return False
