"""
Ensure Interview Copilot runs only inside its own folder.
- Working directory: interview-copilot/
- Config: interview-copilot/.env only (not Outreach or OS env)
- Python: interview-copilot/venv only
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENV_FILE = ROOT / ".env"
VENV_DIR = ROOT / "venv"


def ensure_project_root() -> None:
    os.chdir(ROOT)


def expected_python() -> Path:
    if sys.platform == "win32":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def assert_local_venv() -> None:
    """Refuse to run with Outreach or global Python."""
    expected = expected_python().resolve()
    actual = Path(sys.executable).resolve()

    if actual == expected:
        return

    # Allow `python main.py` when cwd is correct and venv is activated by path match
    try:
        if expected.exists() and actual.samefile(expected):
            return
    except OSError:
        pass

    msg = (
        "\n[Interview Copilot] Wrong Python environment.\n"
        f"  Expected: {expected}\n"
        f"  Got:      {actual}\n\n"
        "This project is isolated from Outreach and other folders.\n"
        "Start it with:\n"
        "  Windows:  .\\scripts\\run.ps1\n"
        "  macOS:    ./scripts/run.sh\n"
    )
    raise SystemExit(msg)


def assert_env_file() -> None:
    if not ENV_FILE.is_file():
        example = ROOT / ".env.example"
        hint = f"Copy {example.name} to .env" if example.exists() else "Create .env"
        raise SystemExit(
            f"\n[Interview Copilot] Missing {ENV_FILE}\n  {hint} and set OPENAI_API_KEY.\n"
        )


def bootstrap() -> Path:
    """Call once at startup before other project imports use config."""
    ensure_project_root()
    assert_env_file()
    assert_local_venv()
    return ROOT
