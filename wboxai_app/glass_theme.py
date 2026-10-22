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
    return f"rgba(255, 255, 255, {_white_alpha(percent)})"


def _see_through_mode() -> bool:
    if not config.GLASS_SEE_THROUGH:
        return False
    return config.GLASS_PANEL_TINT_PERCENT <= 1.0


def _glass_colors() -> dict[str, str]:
    if _see_through_mode():
        return {
            "panel": "rgba(255, 255, 255, 0)",
            "strip": "rgba(255, 255, 255, 0)",
            "input": "rgba(255, 255, 255, 0)",
            "hover": "rgba(255, 255, 255, 25)",
            "border": BORDER_SOFT,
        }
    tint = config.GLASS_PANEL_TINT_PERCENT
    return {
        "panel": _rgba_white(tint),
        "strip": _rgba_white(max(1.0, tint * 0.5)),
        "input": "transparent" if tint <= 3 else _rgba_white(min(100.0, tint * 0.4)),
        "hover": _rgba_white(min(35.0, max(8.0, tint * 0.35))),
        "border": _rgba_white(min(40.0, max(10.0, tint * 0.4))),
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
        border: 2px solid #000000;
        border-radius: 10px;
    }}
    #drag_strip:hover {{ background-color: {c["hover"]}; }}
    #drag_grip {{ color: {TEXT}; font-size: 13px; background: transparent; }}
    #resize_grip {{ background: transparent; border: none; }}
    #panel {{
        background-color: {panel};
        border: 1px solid {c["border"]};
        border-radius: 16px;
    }}
    #title {{
        color: {TEXT}; font-size: 21px; font-weight: 700; background: transparent;
    }}
    #status {{ color: {TEXT_MUTED}; font-size: 15px; background: transparent; }}
    #section {{ color: {TEXT}; font-size: 14px; font-weight: 600; background: transparent; }}
    #hint {{ color: {TEXT_HINT}; font-size: 13px; background: transparent; }}
    QLabel {{ color: {TEXT}; font-size: 15px; background: transparent; }}
    QTextEdit, QPlainTextEdit {{
        background: {input_bg};
        background-color: {input_bg};
        color: {TEXT};
        font-size: 17px;
        border: 1px solid rgba(255, 255, 255, 45);
        border-radius: 10px;
        padding: 10px;
        selection-background-color: rgba(80, 120, 255, 120);
        selection-color: {TEXT};
    }}
    QPushButton#primary, QToolButton#primary {{
        background-color: rgba(0, 0, 0, 120);
        color: {TEXT};
        border: 1px solid {c["border"]};
        height: 30px;
        border-radius: 15px;
        padding: 0px 16px;
        margin: 0px;
        font-size: 12px;
        font-weight: normal;
    }}
    QPushButton#primary:hover, QToolButton#primary:hover {{ background-color: rgba(0, 0, 0, 160); }}
    QPushButton#primary:checked, QToolButton#primary:checked {{
        background-color: rgba(59, 130, 246, 180);
        color: #FFFFFF;
        border: 1px solid rgba(59, 130, 246, 240);
    }}
    QPushButton#ghost, QToolButton#ghost {{
        background-color: rgba(0, 0, 0, 80);
        color: {TEXT};
        border: 1px solid {c["border"]};
        height: 30px;
        border-radius: 15px;
        padding: 0px 14px;
        margin: 0px;
        font-size: 12px;
    }}
    QPushButton#ghost:hover, QToolButton#ghost:hover {{ background-color: rgba(0, 0, 0, 120); }}
    QPushButton#ghost:checked, QToolButton#ghost:checked {{
        background-color: rgba(0, 0, 0, 140);
        color: {TEXT};
        border: 1px solid {BORDER};
    }}
    QPushButton#close, QToolButton#close {{
        background: transparent;
        color: {TEXT};
        border: none;
        height: 30px;
        width: 30px;
        border-radius: 15px;
        font-size: 17px;
        font-weight: normal;
        padding: 0;
        margin: 0px;
    }}
    QPushButton#close:hover, QToolButton#close:hover {{ background-color: {c["hover"]}; color: {TEXT}; }}
    QPushButton#refresh, QToolButton#refresh {{
        background-color: rgba(0, 0, 0, 90);
        color: {TEXT};
        border: 1px solid {c["border"]};
        height: 30px;
        width: 30px;
        border-radius: 15px;
        font-size: 17px;
        font-weight: normal;
        padding: 0;
        margin: 0px;
    }}
    QPushButton#refresh:hover, QToolButton#refresh:hover {{
        background-color: rgba(0, 0, 0, 140);
        color: {TEXT};
    }}
    QToolButton {{
        padding: 8px 14px;
    }}
    QToolButton::menu-button {{
        border-left: 1px solid {c["border"]};
        border-top-right-radius: 18px;
        border-bottom-right-radius: 18px;
        width: 16px;
    }}
    QMenu {{
        background-color: rgba(20, 20, 20, 230);
        border: 1px solid {c["border"]};
        border-radius: 10px;
        padding: 5px;
    }}
    QMenu::item {{
        background: transparent;
        padding: 6px 24px;
        margin: 2px;
        border-radius: 6px;
        color: {TEXT};
        font-size: 14px;
    }}
    QMenu::item:selected {{
        background-color: rgba(255, 255, 255, 35);
    }}
    QMenu::item:checked {{
        font-weight: bold;
    }}
    QSlider#blur_slider {{
        height: 12px;
        background: transparent;
        margin: 4px 0px;
    }}
    QSlider#blur_slider::groove:horizontal {{
        height: 4px;
        background: rgba(255, 255, 255, 30);
        border-radius: 2px;
    }}
    QSlider#blur_slider::sub-page:horizontal {{
        background: rgba(255, 255, 255, 100);
        border-radius: 2px;
    }}
    QSlider#blur_slider::handle:horizontal {{
        width: 12px;
        height: 12px;
        margin-top: -4px;
        margin-bottom: -4px;
        border-radius: 6px;
        background: {TEXT};
    }}
    QSlider#blur_slider::handle:horizontal:hover {{
        background: #3b82f6;
    }}
    """
