"""
run_app.py — Standalone Product Runner (independent of setup).

Use this to run the WboxAI overlay WITHOUT running the setup wizard,
useful while iterating on the product separately from the setup flow.

Usage:
    .\\venv\\Scripts\\python.exe run_app.py              # normal run (checks session)
    .\\venv\\Scripts\\python.exe run_app.py --no-login   # skip login gate entirely
    .\\venv\\Scripts\\python.exe run_app.py --no-resume  # skip candidate picker

Behaviour:
    - If session exists (.session.json) → goes straight to candidate picker + overlay
    - If no session and NOT --no-login  → shows SetupWizard first
    - --no-login                        → skips all login/setup checks (dev shortcut)
"""

from __future__ import annotations

import sys
from pathlib import Path

# ── enforce/auto-switch venv ──────────────────────────────────────────────────
expected_venv = Path(__file__).resolve().parent / "venv" / "Scripts" / "python.exe"
if expected_venv.is_file() and Path(sys.executable).resolve() != expected_venv.resolve():
    import subprocess
    sys.exit(subprocess.call([str(expected_venv)] + sys.argv))

# ── inject package paths ──────────────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parent
for _p in (_ROOT, _ROOT / "wboxai_app", _ROOT / "audio_processing", _ROOT / "llm_project"):
    _s = str(_p)
    if _s not in sys.path:
        sys.path.insert(0, _s)

# ── Windows app ID ────────────────────────────────────────────────────────────
if sys.platform == "win32":
    import ctypes
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("whitebox.wboxai.v1")
    except Exception:
        pass

# ── flags ─────────────────────────────────────────────────────────────────────
_NO_LOGIN  = "--no-login"  in sys.argv
_NO_RESUME = "--no-resume" in sys.argv

# ─────────────────────────────────────────────────────────────────────────────
# Bootstrap (venv + .env checks — same as main.py)
# ─────────────────────────────────────────────────────────────────────────────
try:
    from project_bootstrap import bootstrap
    bootstrap()
except Exception as e:
    from PyQt6.QtWidgets import QApplication, QMessageBox
    _app = QApplication.instance() or QApplication(sys.argv)
    QMessageBox.critical(None, "Bootstrap Error", f"Failed to start WboxAI:\n{e}")
    sys.exit(1)

# ── now safe to import everything ─────────────────────────────────────────────
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor

from PyQt6.QtCore import QObject, QTimer, QEventLoop, pyqtSignal
from PyQt6.QtWidgets import QApplication

import config
from audio_processing.audio_stt import AudioEvent, AudioSTTConfig, AudioToTextPipeline, EventKind
from audio_processing.audio_capture import AudioChunk, SpeechRecorder
from llm_project.openai_service import (
    close_client,
    format_api_error,
    generate_answer,
    solve_from_screenshot,
    transcribe,
)
from overlay import OverlayWindow
from screen_capture import capture_screen_jpeg
from screen_watcher import ScreenWatcher

# ─────────────────────────────────────────────────────────────────────────────
# Re-use InterviewApp from main.py but with a custom run() that respects flags
# ─────────────────────────────────────────────────────────────────────────────
# We import the whole InterviewApp class and override only run()
from main import InterviewApp as _BaseInterviewApp


class AppRunner(_BaseInterviewApp):
    """
    Thin subclass of InterviewApp that supports --no-login and --no-resume flags
    for development iteration without the full setup overhead.
    """

    def run(self) -> int:
        self.app.setQuitOnLastWindowClosed(False)

        # ── Login gate ────────────────────────────────────────────────────────
        if _NO_LOGIN:
            print("[run_app] --no-login: skipping session check and setup wizard.", flush=True)
        else:
            from login_dialog import is_logged_in, get_candidate_mode
            if not is_logged_in():
                print("[run_app] No session found → launching LoginDialog.", flush=True)
                from login_dialog import LoginDialog
                from PyQt6.QtCore import QEventLoop
                dlg = LoginDialog()
                loop = QEventLoop()
                dlg.finished.connect(loop.quit)
                dlg.show()
                loop.exec()

                if not is_logged_in():
                    print("[run_app] Login not completed — exiting.", flush=True)
                    return 0

                # Reload config so freshly-written .env keys are active
                try:
                    import importlib
                    importlib.reload(config)
                except Exception:
                    pass
            else:
                print("[run_app] Session valid → skipping login dialog.", flush=True)

        # ── Candidate picker ──────────────────────────────────────────────────
        if _NO_RESUME:
            print("[run_app] --no-resume: skipping candidate picker.", flush=True)
            import time as _time
            config.SELECTED_CANDIDATE_NAME = "TestCandidate"
            config.SESSION_TIMESTAMP = _time.strftime("%Y%m%d_%H%M%S")
        else:
            from login_dialog import get_candidate_mode
            from overlay import show_resume_dialog
            candidate_mode = get_candidate_mode()
            if candidate_mode == "WHITEBOX":
                show_resume_dialog(whitebox_mode=True)
            elif candidate_mode == "MANUAL":
                show_resume_dialog(whitebox_mode=False)
            else:
                # Legacy session without mode — use generic picker
                show_resume_dialog()

        self.app.setQuitOnLastWindowClosed(True)

        # ── Overlay window ────────────────────────────────────────────────────
        import time as _time
        candidate_name = getattr(config, "SELECTED_CANDIDATE_NAME", "UnknownCandidate")
        timestamp = getattr(config, "SESSION_TIMESTAMP", _time.strftime("%Y%m%d_%H%M%S"))
        from latency_tracker import tracker
        tracker.set_dynamic_filepaths(candidate_name, timestamp)

        plat = "Windows"
        self.window.show()
        self.window.move(80, 80)
        self.window.raise_()
        if not config.STEALTH_FOCUS:
            self.window.activateWindow()
        QTimer.singleShot(300, self.window._apply_exclude_once)

        msg = f"Ready ({plat})"
        active_providers = config.get_active_providers()
        if active_providers:
            msg += f" · Providers: {', '.join(p.upper() for p in active_providers)}"
        else:
            msg += " · Configure OpenAI, Gemini, or Claude in .env"
        if config.use_transparent_overlay():
            msg += " · transparent"
        if config.INVISIBLE_IN_SHARE:
            msg += " · share-hide on"
        if config.STEALTH_FOCUS:
            msg += " · stealth"
        if config.load_resume_context():
            msg += " · resume loaded"
        self.window.status_changed.emit(msg)

        if self._watcher.enabled:
            self.window.set_watch_checked(True)

        return self.app.exec()


def main() -> None:
    runner = AppRunner()
    sys.exit(runner.run())


if __name__ == "__main__":
    main()
