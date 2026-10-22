"""Standalone product runner for WboxAI.

The Wbox web login/session flow is intentionally disabled during development.
API credentials are loaded directly from this repository's .env by config.py.

Usage:
    python app/run_app.py
    python app/run_app.py --no-resume
"""

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

# ── flags ─────────────────────────────────────────────────────────────────────
_NO_RESUME = "--no-resume" in sys.argv

# ─────────────────────────────────────────────────────────────────────────────
# Bootstrap (.env checks)
# ─────────────────────────────────────────────────────────────────────────────
try:
    from project_bootstrap import bootstrap
    bootstrap()
except Exception as e:
    from PyQt6.QtWidgets import QApplication, QMessageBox
    _app = QApplication.instance() or QApplication(sys.argv)
    QMessageBox.critical(None, "Bootstrap Error", f"Failed to start WboxAI:\\n{e}")
    sys.exit(1)

# ── now safe to import everything ─────────────────────────────────────────────
from PyQt6.QtCore import QTimer
import config
from main import InterviewApp as _BaseInterviewApp


class AppRunner(_BaseInterviewApp):
    """Thin runner that bypasses web login and uses local .env credentials."""

    def run(self) -> int:
        self.app.setQuitOnLastWindowClosed(False)
        print("[run_app] Login/session flow disabled; using credentials from this repository's .env.", flush=True)

        if _NO_RESUME:
            print("[run_app] --no-resume: skipping candidate picker.", flush=True)
            import time as _time
            config.SELECTED_CANDIDATE_NAME = "TestCandidate"
            config.SESSION_TIMESTAMP = _time.strftime("%Y%m%d_%H%M%S")
        else:
            # Resume context selection is independent of authentication.
            from overlay import show_resume_dialog
            show_resume_dialog()

        self.app.setQuitOnLastWindowClosed(True)

        import time as _time
        candidate_name = getattr(config, "SELECTED_CANDIDATE_NAME", "UnknownCandidate")
        timestamp = getattr(config, "SESSION_TIMESTAMP", _time.strftime("%Y%m%d_%H%M%S"))
        from latency_tracker import tracker
        tracker.set_dynamic_filepaths(candidate_name, timestamp)

        self.window.show()
        self.window.move(80, 80)
        self.window.raise_()
        if not config.STEALTH_FOCUS:
            self.window.activateWindow()
        QTimer.singleShot(300, self.window._apply_exclude_once)

        msg = "Ready (Windows)"
        active_providers = config.get_active_providers()
        if active_providers:
            msg += f" | Providers: {', '.join(p.upper() for p in active_providers)}"
        else:
            msg += " | Configure OpenAI, Gemini, or Claude in .env"
        if config.use_transparent_overlay():
            msg += " | transparent"
        if config.INVISIBLE_IN_SHARE:
            msg += " | share-hide on"
        if config.STEALTH_FOCUS:
            msg += " | stealth"
        if config.load_resume_context():
            msg += " | resume loaded"
        self.window.status_changed.emit(msg)

        if self._watcher.enabled:
            self.window.set_watch_checked(True)

        return self.app.exec()


if __name__ == "__main__":
    sys.exit(AppRunner().run())
