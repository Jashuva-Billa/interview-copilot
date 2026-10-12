"""Keep overlay from stealing focus from HackerRank / CoderPad / LeetCode."""

from __future__ import annotations

import sys

WS_EX_NOACTIVATE = 0x08000000
GWL_EXSTYLE = -20


def _user32():
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongW.restype = wintypes.LONG
    user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.LONG]
    user32.SetWindowLongW.restype = wintypes.LONG
    return user32


def prevent_activation_steal(hwnd: int) -> bool:
    """
    WS_EX_NOACTIVATE: mouse over overlay + scroll does not blur the coding tab.
    Buttons still receive clicks on Windows.
    """
    if sys.platform != "win32" or not hwnd:
        return False
    try:
        user32 = _user32()
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_NOACTIVATE)
        return True
    except Exception:
        return False
