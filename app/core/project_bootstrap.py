"""
Ensure Interview Copilot runs only inside its own folder.
- Working directory: interview-copilot/
- Config: interview-copilot/.env only (not Outreach or OS env)
- Python: use the interpreter that launches the app (no forced local venv)
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = ROOT / ".env"


def ensure_project_root() -> None:
    os.chdir(ROOT)


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
    return ROOT
