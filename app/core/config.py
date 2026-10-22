"""
All settings loaded ONLY from interview-copilot/.env (not Outreach, not OS env).
"""

from __future__ import annotations

import sys
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = ROOT / ".env"
_FILE_ENV: dict[str, str | None] = dotenv_values(ENV_FILE) if ENV_FILE.is_file() else {}


def _env(name: str, default: str = "") -> str:
    raw = _FILE_ENV.get(name)
    if raw is None or raw == "":
        return default.strip()
    return str(raw).strip().strip('"').strip("'")


def _env_bool(name: str, default: str = "true") -> bool:
    return _env(name, default).lower() in ("1", "true", "yes")


IS_WINDOWS = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
PLATFORM_NAME = "macOS" if IS_MAC else "Windows" if IS_WINDOWS else sys.platform

OPENAI_API_KEY = _env("OPENAI_API_KEY")
OPENAI_TRANSCRIBE_MODEL = _env("OPENAI_TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe")
OPENAI_CHAT_MODEL = _env("OPENAI_CHAT_MODEL", "gpt-4o-mini")
AUDIO_SOURCE = _env("AUDIO_SOURCE", "loopback").lower()
# "auto" uses WebSocket streaming when both the optional SDK and key are present;
# otherwise the app falls back to incremental OpenAI snapshot transcription.
AUDIO_STT_MODE = _env("AUDIO_STT_MODE", "auto").lower()
DEEPGRAM_API_KEY = _env("DEEPGRAM_API_KEY")
JOB_ROLE = _env("JOB_ROLE", "Software Engineer")
JOB_DESCRIPTION = _env("JOB_DESCRIPTION", "")
CODE_LANGUAGE = _env("CODE_LANGUAGE", "python").lower()
CODING_MODE = _env("CODING_MODE", "auto").lower()
OPENAI_VISION_MODEL = _env("OPENAI_VISION_MODEL", "gpt-4o")
LIGHTWEIGHT_MODE = _env_bool("LIGHTWEIGHT_MODE", "true")
SCREEN_CAPTURE_MAX_WIDTH = int(_env("SCREEN_CAPTURE_MAX_WIDTH", "1280" if LIGHTWEIGHT_MODE else "1920"))
SCREEN_CAPTURE_QUALITY = int(_env("SCREEN_CAPTURE_QUALITY", "72"))
SCREEN_WATCH_INTERVAL_SEC = int(_env("SCREEN_WATCH_INTERVAL_SEC", "30" if LIGHTWEIGHT_MODE else "18"))
SCREEN_WATCH_ENABLED = _env_bool("SCREEN_WATCH_ENABLED", "false")
EXCLUDE_REFRESH_SEC = int(_env("EXCLUDE_REFRESH_SEC", "8"))
MAX_WORKERS = int(_env("MAX_WORKERS", "1" if LIGHTWEIGHT_MODE else "2"))

# Default to visible in screen-sharing captures on every launch. The UI toggle
# can still enable capture exclusion for the current session.
INVISIBLE_IN_SHARE = False
OVERLAY_TRANSPARENT = _env_bool("OVERLAY_TRANSPARENT", "true")
STEALTH_FOCUS = _env_bool("STEALTH_FOCUS", "true")
_blur_pct = _env("GLASS_BLUR_PERCENT", "")
if _blur_pct:
    GLASS_BLUR_PERCENT = max(0.0, min(100.0, float(_blur_pct)))
elif _env_bool("GLASS_OS_BLUR", "false"):
    GLASS_BLUR_PERCENT = 24.0
else:
    GLASS_BLUR_PERCENT = 0.4

_panel_tint = _env("GLASS_PANEL_TINT_PERCENT", "")
GLASS_PANEL_TINT_PERCENT = max(0.0, min(30.0, float(_panel_tint))) if _panel_tint else 0.0
GLASS_SEE_THROUGH = _env_bool("GLASS_SEE_THROUGH", "true")
SSL_VERIFY = _env_bool("SSL_VERIFY", "true")
SSL_CA_FILE = _env("SSL_CA_FILE", "")


def use_transparent_overlay() -> bool:
    return OVERLAY_TRANSPARENT


def openai_key_configured() -> bool:
    return bool(OPENAI_API_KEY) and OPENAI_API_KEY.startswith("sk-")


def env_file_path() -> Path:
    return ENV_FILE


def resume_path() -> Path:
    p = Path(_env("RESUME_CONTEXT_PATH", str(ROOT / "local_data" / "resume_context.txt")))
    if not p.is_absolute():
        p = ROOT / p
    try:
        p.resolve().relative_to(ROOT.resolve())
    except ValueError:
        p = ROOT / "local_data" / "resume_context.txt"
    if not p.is_file() and p.name == "resume_context.txt":
        local_resume = ROOT / "local_data" / "resume_context.txt"
        if local_resume.is_file():
            p = local_resume
    return p


RESUME_PATH = resume_path()


def load_resume_context() -> str:
    if RESUME_PATH.exists():
        return RESUME_PATH.read_text(encoding="utf-8").strip()
    return ""
