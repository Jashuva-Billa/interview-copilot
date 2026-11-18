"""Packaged desktop entry point for Interview Copilot."""

from __future__ import annotations

import os
import sys
from pathlib import Path

_WINDOWS_PACKAGE_TEST = sys.platform == "win32" and "--package-e2e-test" in sys.argv
if _WINDOWS_PACKAGE_TEST:
    profile = os.environ.get("COPILOT_PACKAGE_TEST_PROFILE")
    if not profile:
        sys.exit(2)
    os.environ["LOCALAPPDATA"] = profile

# ── configure import paths ────────────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parents[1]
_APP = _ROOT / "app"
for _p in (
    _ROOT, _APP, _APP / "core", _APP / "services", _APP / "ui",
    _APP / "screen", _APP / "monitoring",
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
    if _WINDOWS_PACKAGE_TEST:
        import faulthandler
        import traceback

        with Path("package-diagnostics.log").open("w", encoding="utf-8") as diagnostics:
            faulthandler.dump_traceback_later(20, repeat=True, file=diagnostics)
            try:
                from app.windows_package_smoke import run

                return run(AppRunner)
            except Exception:
                traceback.print_exc(file=diagnostics)
                return 1
            finally:
                faulthandler.cancel_dump_traceback_later()
    if "--package-smoke-test" in sys.argv:
        if "--expect-saved-key" in sys.argv and not config.openai_key_configured():
            return 3
        runner = AppRunner()
        runner.window.close()
        return 0
    if not config.openai_key_configured() and not configure_openai():
        return 0
    return AppRunner().run()


if __name__ == "__main__":
    sys.exit(main())
