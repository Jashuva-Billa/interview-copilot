"""
All settings loaded ONLY from interview-copilot/.env (not Outreach, not OS env).
"""

from __future__ import annotations

import sys
from pathlib import Path

from dotenv import dotenv_values

FROZEN = getattr(sys, "frozen", False)

if FROZEN:
    ROOT = Path(sys.executable).resolve().parent
else:
    ROOT = Path(__file__).resolve().parent

ENV_FILE = ROOT / ".env"
if not ENV_FILE.is_file() and (ROOT.parent / ".env").is_file():
    ENV_FILE = ROOT.parent / ".env"


# Single source of truth — this file only
_FILE_ENV: dict[str, str | None] = (
    dotenv_values(ENV_FILE) if ENV_FILE.is_file() else {}
)


def _env(name: str, default: str = "") -> str:
    raw = _FILE_ENV.get(name)
    if raw is None or raw == "":
        return default.strip()
    return str(raw).strip().strip('"').strip("'")


def _env_bool(name: str, default: str = "true") -> bool:
    return _env(name, default).lower() in ("1", "true", "yes")


if sys.platform != "win32":
    raise SystemExit("Error: WboxAI is designed and supported exclusively for Windows (10/11).")

IS_WINDOWS = True
IS_MAC = False
PLATFORM_NAME = "Windows"

OPENAI_API_KEY = _env("OPENAI_API_KEY")
OPENAI_TRANSCRIBE_MODEL = _env("OPENAI_TRANSCRIBE_MODEL", "whisper-1")
OPENAI_CHAT_MODEL = _env("OPENAI_CHAT_MODEL", "gpt-4o-mini")
CODING_MAX_TOKENS = max(600, int(_env("CODING_MAX_TOKENS", "1400")))
AUDIO_SOURCE = _env("AUDIO_SOURCE", "loopback").lower()
ENTERPRISE_AUDIO = _env_bool("ENTERPRISE_AUDIO", "true")
AUDIO_STT_PROVIDER = _env("AUDIO_STT_PROVIDER", "sensevoice").lower()
AUDIO_STT_MODEL = _env("AUDIO_STT_MODEL", "iic/SenseVoiceSmall")
AUDIO_LANGUAGE = _env("AUDIO_LANGUAGE", "auto")
AUDIO_VAD_MODEL_PATH = _env("AUDIO_VAD_MODEL_PATH", "")
AUDIO_ALLOW_FALLBACK = _env_bool("AUDIO_ALLOW_FALLBACK", "true")
# If false, audio-to-text will never use OpenAI fallback.
AUDIO_ALLOW_OPENAI_STT = _env_bool("AUDIO_ALLOW_OPENAI_STT", "false")
AUDIO_DIARIZATION_PROVIDER = _env("AUDIO_DIARIZATION_PROVIDER", "source_metadata").lower()
AUDIO_DIARIZATION_MODEL = _env("AUDIO_DIARIZATION_MODEL", "")
PYANNOTE_AUTH_TOKEN = _env("PYANNOTE_AUTH_TOKEN", "")
QUESTION_CONFIDENCE_THRESHOLD = float(_env("QUESTION_CONFIDENCE_THRESHOLD", "0.55"))
ROLE_CONFIDENCE_THRESHOLD = float(_env("ROLE_CONFIDENCE_THRESHOLD", "0.58"))
QUESTION_DEDUP_THRESHOLD = float(_env("QUESTION_DEDUP_THRESHOLD", "0.86"))
LLM_TRIGGER_CONFIDENCE_THRESHOLD = float(_env("LLM_TRIGGER_CONFIDENCE_THRESHOLD", "0.45"))
LLM_CONTEXT_TURN_COUNT = int(_env("LLM_CONTEXT_TURN_COUNT", "5"))
SPEECH_TO_TEXT_SERVER_URL = _env("AUDIO_PROCESSING_SERVER_URL", _env("SPEECH_TO_TEXT_SERVER_URL", _env("DHWANI_SERVER_URL", "ws://127.0.0.1:8000")))
SPEECH_TO_TEXT_PROVIDER = _env("AUDIO_PROCESSING_PROVIDER", _env("SPEECH_TO_TEXT_PROVIDER", _env("DHWANI_PROVIDER", "openai"))).lower()
USE_LOCAL_LLM = _env_bool("USE_LOCAL_LLM", "false")
DISABLE_LLM_CLEANING = _env_bool("DISABLE_LLM_CLEANING", "true")
SPEECH_TO_TEXT_OPENAI_KEY = _env("AUDIO_PROCESSING_OPENAI_KEY", _env("SPEECH_TO_TEXT_OPENAI_KEY", _env("DHWANI_OPENAI_KEY")))
SPEECH_TO_TEXT_DEEPGRAM_KEY = _env("AUDIO_PROCESSING_DEEPGRAM_KEY", _env("SPEECH_TO_TEXT_DEEPGRAM_KEY", _env("DHWANI_DEEPGRAM_KEY")))
JOB_ROLE = _env("JOB_ROLE", "Software Engineer")
JOB_DESCRIPTION = _env("JOB_DESCRIPTION", "")
CODE_LANGUAGE = _env("CODE_LANGUAGE", "python").lower()
CODING_MODE = _env("CODING_MODE", "auto").lower()
OPENAI_VISION_MODEL = _env("OPENAI_VISION_MODEL", "gpt-4o")
LIGHTWEIGHT_MODE = _env_bool("LIGHTWEIGHT_MODE", "true")
SCREEN_CAPTURE_MAX_WIDTH = int(
    _env("SCREEN_CAPTURE_MAX_WIDTH", "1280" if LIGHTWEIGHT_MODE else "1920")
)
SCREEN_CAPTURE_QUALITY = int(_env("SCREEN_CAPTURE_QUALITY", "72"))
SCREEN_WATCH_INTERVAL_SEC = int(
    _env("SCREEN_WATCH_INTERVAL_SEC", "30" if LIGHTWEIGHT_MODE else "18")
)
SCREEN_WATCH_ENABLED = _env_bool("SCREEN_WATCH_ENABLED", "false")
EXCLUDE_REFRESH_SEC = int(_env("EXCLUDE_REFRESH_SEC", "8"))
MAX_WORKERS = int(_env("MAX_WORKERS", "1" if LIGHTWEIGHT_MODE else "2"))

INVISIBLE_IN_SHARE = _env_bool("INVISIBLE_IN_SHARE", "true")
OVERLAY_TRANSPARENT = _env_bool("OVERLAY_TRANSPARENT", "true")
# Do not steal focus from HackerRank/CoderPad (hover+scroll, WS_EX_NOACTIVATE on Windows)
STEALTH_FOCUS = _env_bool("STEALTH_FOCUS", "true")
# Backdrop blur strength 0–100 (supports decimals, e.g. 0.5). Legacy: GLASS_OS_BLUR=true → 24
_blur_pct = _env("GLASS_BLUR_PERCENT", "")
if _blur_pct:
    GLASS_BLUR_PERCENT = max(0.0, min(100.0, float(_blur_pct)))
elif _env_bool("GLASS_OS_BLUR", "false"):
    GLASS_BLUR_PERCENT = 24.0
else:
    GLASS_BLUR_PERCENT = 0.4

# White tint on panel (0–100). 0 = transparent, see background text through overlay
_panel_tint = _env("GLASS_PANEL_TINT_PERCENT", "")
GLASS_PANEL_TINT_PERCENT = (
    max(0.0, min(100.0, float(_panel_tint))) if _panel_tint else 0.0
)

# True = panel + answer boxes fully transparent (background text partially visible)
GLASS_SEE_THROUGH = _env_bool("GLASS_SEE_THROUGH", "true")

SSL_VERIFY = _env_bool("SSL_VERIFY", "true")
SSL_CA_FILE = _env("SSL_CA_FILE", "")

EMAIL_RECEIVER = _env("EMAIL_RECEIVER", "")
SMTP_SERVER = _env("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(_env("SMTP_PORT", "587"))
SMTP_USERNAME = _env("SMTP_USERNAME", "")
SMTP_PASSWORD = _env("SMTP_PASSWORD", "")
SMTP_USE_TLS = _env_bool("SMTP_USE_TLS", "true")

GEMINI_API_KEY = _env("GEMINI_API_KEY", "")
GEMINI_MODEL = _env("GEMINI_MODEL", "gemini-2.5-flash")

CLAUDE_API_KEY = _env("CLAUDE_API_KEY", _env("ANTHROPIC_API_KEY", ""))
CLAUDE_MODEL = _env("CLAUDE_MODEL", "claude-3-5-sonnet-20241022")

CANDIDATE_API_URL = _env("CANDIDATE_API_URL", "")
SELECTED_CANDIDATE_NAME = "UnknownCandidate"
SESSION_TIMESTAMP = ""



def use_transparent_overlay() -> bool:
    return OVERLAY_TRANSPARENT


def openai_key_configured() -> bool:
    return bool(OPENAI_API_KEY) and OPENAI_API_KEY.startswith("sk-")


def gemini_key_configured() -> bool:
    return bool(GEMINI_API_KEY)


def claude_key_configured() -> bool:
    return bool(CLAUDE_API_KEY)


def get_active_providers() -> list[str]:
    providers = []
    if openai_key_configured() or USE_LOCAL_LLM:
        providers.append("openai")
    if gemini_key_configured():
        providers.append("gemini")
    if claude_key_configured():
        providers.append("claude")
    return providers


def env_file_path() -> Path:
    return ENV_FILE


def resume_path() -> Path:
    env_p = _env("RESUME_CONTEXT_PATH", "")
    if env_p:
        p = Path(env_p)
        if p.is_file():
            return p
    if (ROOT / "resume_context.txt").is_file():
        return ROOT / "resume_context.txt"
    if (ROOT.parent / "resume_context.txt").is_file():
        return ROOT.parent / "resume_context.txt"
    return ROOT / "resume_context.txt"


RESUME_PATH = resume_path()


def load_resume_context() -> str:
    if RESUME_PATH.exists():
        return RESUME_PATH.read_text(encoding="utf-8").strip()
    return ""


def intro_path() -> Path:
    p = Path(_env("INTRO_CONTEXT_PATH", str(ROOT / "intro_context.txt")))
    if not p.is_absolute():
        p = ROOT / p
    try:
        p.resolve().relative_to(ROOT.resolve())
    except ValueError:
        p = ROOT / "intro_context.txt"
    return p


INTRO_PATH = intro_path()


def load_intro_context() -> str:
    if INTRO_PATH.exists():
        return INTRO_PATH.read_text(encoding="utf-8").strip()
    return ""


def project_overview_path() -> Path:
    p = ROOT / "project_overview.txt"
    return p


PROJECT_OVERVIEW_PATH = project_overview_path()


def load_project_overview_context() -> str:
    if PROJECT_OVERVIEW_PATH.exists():
        try:
            return PROJECT_OVERVIEW_PATH.read_text(encoding="utf-8").strip()
        except Exception:
            pass
    return ""
