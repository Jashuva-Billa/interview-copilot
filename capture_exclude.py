"""Hide overlay from screen share — Windows + macOS."""

from __future__ import annotations

import sys
from typing import Any, Tuple

import config


def apply_to_window(widget: Any) -> Tuple[bool, str]:
    """
    Apply capture exclusion. Returns (success, status_message).
    Main thread only.
    """
    if widget is None or not widget.isVisible():
        return False, ""

    if sys.platform == "win32":
        return _apply_windows(widget)
    if sys.platform == "darwin":
        ok = _apply_macos(widget)
        return ok, "Hidden from share" if ok else "Share-hide unavailable (install pyobjc)"
    return False, ""


def _native_id(widget: Any) -> int:
    handle = widget.windowHandle()
    if handle is not None:
        wid = int(handle.winId())
        if wid:
            return wid
    return int(widget.winId())


def _apply_windows(widget: Any) -> Tuple[bool, str]:
    hwnd = _native_id(widget)
    if not hwnd:
        return False, "Share-hide: no window handle"

    try:
        from win_capture_exclude import exclude_top_level_window, is_excluded_from_capture

        keep_layered = config.use_transparent_overlay()
        ok = exclude_top_level_window(hwnd, keep_layered=keep_layered)
        verified = is_excluded_from_capture(hwnd)
        if ok or verified:
            if keep_layered:
                return True, "Hidden from share (transparent)"
            return True, "Hidden from share"
        if keep_layered:
            return False, "Share-hide failed — set OVERLAY_TRANSPARENT=false in .env"
        return False, "Share-hide failed"
    except Exception as exc:
        return False, f"Share-hide error: {exc}"


def _apply_macos(widget: Any) -> bool:
    wid = _native_id(widget)
    if not wid:
        return False
    try:
        from ctypes import c_void_p

        import objc
        from Cocoa import NSWindowSharingNone

        obj = objc.objc_object(c_void_p=wid)
        ns_window = obj.window()
        if ns_window is None:
            return False
        ns_window.setSharingType_(NSWindowSharingNone)
        return True
    except ImportError:
        return False
    except Exception:
        return False
