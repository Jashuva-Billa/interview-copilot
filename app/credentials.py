"""First-run setup and credit-exhaustion recovery."""

from pathlib import Path

from dotenv import set_key
from PyQt6.QtWidgets import QInputDialog, QLineEdit, QMessageBox

import config

_KEY_NAMES = {"openai": "OPENAI_API_KEY", "gemini": "GEMINI_API_KEY", "claude": "CLAUDE_API_KEY"}
_REPORTED: set[tuple[str, str]] = set()


def configure_key(provider: str, parent=None, *, exhausted: bool = False) -> bool:
    name = _KEY_NAMES[provider]
    old_key = getattr(config, name, "")
    if exhausted:
        if (provider, old_key) in _REPORTED:
            return False
        _REPORTED.add((provider, old_key))
    title = "Update API key" if exhausted else "Interview Copilot setup"
    reason = "Credits exhausted. Enter a replacement API key." if exhausted else "Enter your OpenAI API key to enable transcription and answers."
    while True:
        value, accepted = QInputDialog.getText(parent, title, reason, QLineEdit.EchoMode.Password)
        if not accepted:
            return False
        key = value.strip()
        if not key or (provider == "openai" and not key.startswith("sk-")):
            QMessageBox.warning(parent, title, "Enter a valid API key.")
            continue
        path = Path(config.env_file_path())
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            set_key(str(path), name, key)
        except OSError as exc:
            QMessageBox.warning(parent, title, f"Could not save the API key: {exc}")
            return False
        setattr(config, name, key)
        return True


def configure_openai() -> bool:
    return configure_key("openai")
