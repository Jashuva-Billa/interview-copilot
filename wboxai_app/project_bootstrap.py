"""
Ensure WboxAI runs only inside its own folder.
- Working directory: interview-copilot/
- Config: interview-copilot/.env only (not Outreach or OS env)
- Python: interview-copilot/venv only
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

FROZEN = getattr(sys, "frozen", False)

if FROZEN:
    ROOT = Path(sys.executable).resolve().parent
else:
    ROOT = Path(__file__).resolve().parent

ENV_FILE = ROOT / ".env"
VENV_DIR = ROOT.parent / "venv" if not FROZEN else None


def ensure_project_root() -> None:
    os.chdir(ROOT)


def expected_python() -> Path:
    if FROZEN:
        return Path(sys.executable)
    return VENV_DIR / "Scripts" / "python.exe"


def assert_local_venv() -> None:
    """Refuse to run with Outreach or global Python."""
    if FROZEN:
        return

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
        "\n[WboxAI] Wrong Python environment.\n"
        f"  Expected: {expected}\n"
        f"  Got:      {actual}\n\n"
        "This project is isolated to its local Windows virtual environment.\n"
        "Start it with:\n"
        "  run.bat\n"
        "  or: .\\venv\\Scripts\\python.exe run_app.py\n"
    )
    raise SystemExit(msg)


def assert_env_file() -> None:
    if not ENV_FILE.is_file() and not (ROOT.parent / ".env").is_file():
        example = ROOT / ".env.example"
        hint = f"Copy {example.name} to .env" if example.exists() else "Create .env"
        raise FileNotFoundError(
            f"Missing configuration file: {ENV_FILE}\n{hint}"
        )


def bootstrap() -> Path:
    """Call once at startup before other project imports use config."""
    ensure_project_root()
    assert_env_file()
    assert_local_venv()

    # Configure path references for the reorganized codebase
    workspace_root = ROOT.parent if not FROZEN else ROOT
    wboxai_path = ROOT
    audio_path = workspace_root / "audio_processing"
    llm_path = workspace_root / "llm_project"

    for path in (workspace_root, wboxai_path, audio_path, llm_path):
        if path.exists():
            path_str = str(path.resolve())
            if path_str not in sys.path:
                sys.path.insert(0, path_str)

    return ROOT

