"""
Bootstrap WboxAI in its own project folder.

The application uses whichever Python interpreter launched it. A repository-local
virtual environment is not required.
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


def ensure_project_root() -> None:
    os.chdir(ROOT)


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

    # Configure path references for the reorganized codebase.
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
