"""Packaged desktop entry point for Interview Copilot."""

from __future__ import annotations

import sys
from pathlib import Path

# ── configure import paths ────────────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parents[1]
_APP = _ROOT / "app"
for _p in (
    _ROOT, _APP, _APP / "core", _APP / "services", _APP / "ui",
    _APP / "screen", _APP / "monitoring", _APP / "setup",
    _ROOT / "wboxai_app", _ROOT / "audio_processing", _ROOT / "llm_project",
):
    _s = str(_p)
    if _s in sys.path:
        sys.path.remove(_s)
    sys.path.insert(0, _s)

# ── Windows app ID ────────────────────────────────────────────────────────────
if sys.platform == "win32":
    import ctypes
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("whitebox.wboxai.v1")
    except Exception:
        pass

# ─────────────────────────────────────────────────────────────────────────────
# Bootstrap (.env checks)
# ─────────────────────────────────────────────────────────────────────────────
try:
    from project_bootstrap import bootstrap
    bootstrap()
except (Exception, SystemExit) as e:
    from PyQt6.QtWidgets import QApplication, QMessageBox
    _app = QApplication.instance() or QApplication(sys.argv)
    QMessageBox.critical(None, "Bootstrap Error", f"Failed to start WboxAI:\n{e}")
    sys.exit(1)

# ── now safe to import everything ─────────────────────────────────────────────
from PyQt6.QtWidgets import QApplication
import config
from main import InterviewApp as _BaseInterviewApp


AppRunner = _BaseInterviewApp


def main() -> int:
    from app.credentials import configure_openai

    qt_app = QApplication(sys.argv)
    qt_app.setApplicationName("Interview Copilot")
    if "--package-smoke-test" in sys.argv:
        runner = AppRunner()
        runner.window.close()
        return 0
    if not config.openai_key_configured() and not configure_openai():
        return 0
    return AppRunner().run()


if __name__ == "__main__":
    sys.exit(main())
