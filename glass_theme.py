"""Frosted white glass theme (Qt stylesheets)."""

from __future__ import annotations

import config

TEXT = "rgba(255, 255, 255, 250)"
TEXT_MUTED = "rgba(255, 255, 255, 220)"
TEXT_HINT = "rgba(255, 255, 255, 180)"
BORDER = "rgba(255, 255, 255, 70)"
BORDER_SOFT = "rgba(255, 255, 255, 45)"

GLASS_PANEL_SOLID = "rgba(255, 255, 255, 200)"


def _white_alpha(percent: float) -> int:
    return max(0, min(255, int(255 * percent / 100)))


def _rgba_white(percent: float) -> str:
    return f"rgba(255, 255, 255, {_white_alpha(percent)}"


def _see_through_mode() -> bool:
    if not config.GLASS_SEE_THROUGH:
        return False
    return config.GLASS_PANEL_TINT_PERCENT <= 1.0


def _glass_colors() -> dict[str, str]:
    if _see_through_mode():
        return {
            "panel": "transparent",
            "strip": "transparent",
            "input": "transparent",
            "hover": "rgba(255, 255, 255, 25)",
            "border": BORDER_SOFT,
        }
    tint = config.GLASS_PANEL_TINT_PERCENT
    return {
        "panel": _rgba_white(tint),
        "strip": _rgba_white(max(1.0, tint * 0.5)),
        "input": "transparent" if tint <= 3 else _rgba_white(tint * 0.4),
        "hover": _rgba_white(min(20.0, tint * 1.2)),
        "border": _rgba_white(min(18.0, tint)),
    }


def stylesheet(*, transparent: bool = True) -> str:
    c = _glass_colors()
    panel = c["panel"] if transparent else GLASS_PANEL_SOLID
    strip = c["strip"] if transparent else "rgba(255, 255, 255, 180)"
    input_bg = c["input"] if transparent else "rgba(255, 255, 255, 120)"
    return f"""
    QMainWindow, QWidget {{ background: transparent; }}
    #drag_strip {{
        background-color: {strip};
        border: 1px solid {c["border"]};
        border-radius: 10px;
    }}
    #drag_strip:hover {{ background-color: {c["hover"]}; }}
    #drag_grip {{ color: {TEXT}; font-size: 11px; background: transparent; }}
    #resize_grip {{ background: transparent; border: none; }}
    #panel {{
        background-color: {panel};
        border: 1px solid {c["border"]};
        border-radius: 16px;
    }}
    #title {{
        color: {TEXT}; font-size: 18px; font-weight: 700; background: transparent;
    }}
    #status {{ color: {TEXT_MUTED}; font-size: 13px; background: transparent; }}
    #section {{ color: {TEXT}; font-size: 12px; font-weight: 600; background: transparent; }}
    #hint {{ color: {TEXT_HINT}; font-size: 11px; background: transparent; }}
    QLabel {{ color: {TEXT}; font-size: 13px; background: transparent; }}
    QTextEdit, QPlainTextEdit {{
        background: transparent;
        background-color: transparent;
        color: {TEXT};
        font-size: 14px;
        border: 1px solid {c["border"]};
        border-radius: 10px;
        padding: 10px;
        selection-background-color: rgba(80, 120, 255, 120);
        selection-color: {TEXT};
    }}
    QPushButton#primary {{
        background-color: rgba(0, 0, 0, 120);
        color: {TEXT};
        border: 1px solid {c["border"]};
        border-radius: 18px;
        padding: 8px 16px;
        font-size: 12px;
        font-weight: 600;
    }}
    QPushButton#primary:hover {{ background-color: rgba(0, 0, 0, 160); }}
    QPushButton#ghost {{
        background-color: rgba(0, 0, 0, 80);
        color: {TEXT};
        border: 1px solid {c["border"]};
        border-radius: 18px;
        padding: 8px 14px;
        font-size: 12px;
    }}
    QPushButton#ghost:hover {{ background-color: rgba(0, 0, 0, 120); }}
    QPushButton#ghost:checked {{
        background-color: rgba(0, 0, 0, 140);
        color: {TEXT};
        border: 1px solid {BORDER};
    }}
    QPushButton#close {{
        background: transparent;
        color: {TEXT};
        border: none;
        border-radius: 14px;
        font-size: 17px;
        font-weight: bold;
        padding: 0;
    }}
    QPushButton#close:hover {{ background-color: {c["hover"]}; color: {TEXT}; }}
    """
