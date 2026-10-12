"""Hide overlay from screen share — Windows (WDA_EXCLUDEFROMCAPTURE)."""

from __future__ import annotations

from typing import Any, Tuple

import config


def _native_id(widget: Any) -> int:
    handle = widget.windowHandle()
    if handle is not None:
        wid = int(handle.winId())
        if wid:
            return wid
    return int(widget.winId())


def apply_to_window(widget: Any) -> Tuple[bool, str]:
    """
    Apply capture exclusion on Windows. Returns (success, status_message).
    Main thread only.
    """
    if widget is None or not widget.isVisible():
        return False, ""

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


def restore_window(widget: Any) -> Tuple[bool, str]:
    """
    Remove capture exclusion on Windows. Returns (success, status_message).
    Main thread only.
    """
    if widget is None or not widget.isVisible():
        return False, ""

    hwnd = _native_id(widget)
    if not hwnd:
        return False, "Share restore: no window handle"

    try:
        from win_capture_exclude import restore_top_level_window

        ok = restore_top_level_window(hwnd)
        if ok:
            return True, "Visible in share"
        return False, "Share restore failed"
    except Exception as exc:
        return False, f"Share restore error: {exc}"
