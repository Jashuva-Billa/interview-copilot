"""Windows SetWindowDisplayAffinity — hide from screen share."""

from __future__ import annotations

import sys

WDA_EXCLUDEFROMCAPTURE = 0x00000011
GA_ROOT = 2
GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
SWP_FRAMECHANGED = 0x0020
SWP_NOMOVE = 0x0001
SWP_NOSIZE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010


def _user32():
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongW.restype = wintypes.LONG
    user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.LONG]
    user32.SetWindowLongW.restype = wintypes.LONG
    user32.SetWindowPos.argtypes = [
        wintypes.HWND,
        wintypes.HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
    ]
    user32.SetWindowPos.restype = wintypes.BOOL
    user32.GetWindowDisplayAffinity.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(wintypes.DWORD),
    ]
    user32.GetWindowDisplayAffinity.restype = wintypes.BOOL
    user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
    user32.SetWindowDisplayAffinity.restype = wintypes.BOOL
    user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetAncestor.restype = wintypes.HWND
    return user32


def _clear_layered_style(hwnd: int) -> None:
    if not hwnd:
        return
    try:
        user32 = _user32()
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        if style & WS_EX_LAYERED:
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style & ~WS_EX_LAYERED)
            user32.SetWindowPos(
                hwnd, 0, 0, 0, 0, 0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED | SWP_NOACTIVATE,
            )
    except Exception:
        pass


def is_excluded_from_capture(hwnd: int) -> bool:
    if sys.platform != "win32" or not hwnd:
        return False
    try:
        import ctypes
        from ctypes import wintypes

        affinity = wintypes.DWORD()
        ok = _user32().GetWindowDisplayAffinity(hwnd, ctypes.byref(affinity))
        return bool(ok) and affinity.value == WDA_EXCLUDEFROMCAPTURE
    except Exception:
        return False


def exclude_top_level_window(hwnd: int, *, keep_layered: bool = False) -> bool:
    """Apply affinity only — do NOT call SetWindowPos after (causes event loop crash)."""
    if sys.platform != "win32" or not hwnd:
        return False
    try:
        user32 = _user32()
        if not keep_layered:
            _clear_layered_style(hwnd)
        root = user32.GetAncestor(hwnd, GA_ROOT) or hwnd
        ok = False
        for h in {hwnd, root}:
            if not h:
                continue
            if bool(user32.SetWindowDisplayAffinity(h, WDA_EXCLUDEFROMCAPTURE)):
                ok = True
        return ok or is_excluded_from_capture(hwnd) or is_excluded_from_capture(root)
    except Exception:
        return False


def exclude_window_tree(hwnd: int) -> int:
    return 1 if exclude_top_level_window(hwnd, keep_layered=False) else 0


def restore_top_level_window(hwnd: int) -> bool:
    if sys.platform != "win32" or not hwnd:
        return False
    try:
        user32 = _user32()
        root = user32.GetAncestor(hwnd, GA_ROOT) or hwnd
        ok = False
        for h in {hwnd, root}:
            if not h:
                continue
            if bool(user32.SetWindowDisplayAffinity(h, 0)):  # WDA_NONE = 0
                ok = True
        return ok or not (is_excluded_from_capture(hwnd) or is_excluded_from_capture(root))
    except Exception:
        return False
