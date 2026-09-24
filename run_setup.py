
"""
run_setup.py — Standalone Setup Runner (independent of the main app).

Use this to develop and test the WBL login flow, API key sync,
and resume fetch WITHOUT running the full audio/LLM pipeline.

Usage:
    .\\venv\\Scripts\\python.exe run_setup.py           # fresh start (clears session)
    .\\venv\\Scripts\\python.exe run_setup.py --keep    # keep existing session (re-open wizard)

What it does:
    1. Clears .session.json (unless --keep)
    2. Opens SetupWizard starting at the Selection page
       (choose: "Login with Whitebox Learning" OR "Setup Manually")
    3. Prints verbose debug output for every API call made during WBL sync
    4. On completion shows a summary of what was synced to .env
    5. Exits cleanly — ready for main app to run

Debug output printed to console:
    [WBL Sync] Token received ...
    [Wbox Backend] GET <endpoint> ...
    [WBL Sync] Extraction results: OpenAI/Gemini/Claude/Resume
"""

from __future__ import annotations

import sys
import os
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
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("whitebox.wboxai.setup.v1")
    except Exception:
        pass

# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    keep_session = "--keep" in sys.argv

    # ── Session management ────────────────────────────────────────────────────
    from login_dialog import clear_session, is_logged_in, load_session, _session_path

    session_file = _session_path()
    if keep_session:
        if is_logged_in():
            print(f"\n[run_setup] Existing session found → re-opening wizard to update config.")
        else:
            print(f"\n[run_setup] No session found → starting fresh.")
    else:
        clear_session()
        print(f"\n[run_setup] Session cleared — starting fresh login flow.")

    print(f"[run_setup] Session file: {session_file}")
    print(f"[run_setup] Config .env:  {_ROOT / 'wboxai_app' / '.env'}\n")

    # ── Qt app ────────────────────────────────────────────────────────────────
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import QEventLoop
    from installer import SetupWizard, THEME_CSS

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("WboxAI Setup")
    app.setStyleSheet(THEME_CSS)

    # ── Wizard ────────────────────────────────────────────────────────────────
    wizard = SetupWizard(first_time_setup=True)
    # Start directly at the "Choose Setup Method" selection page (index 6)
    wizard.pages.setCurrentIndex(6)
    wizard.update_navigation()

    # Spin a proper nested event loop — no busy-wait
    loop = QEventLoop()
    wizard.closed.connect(loop.quit)
    wizard.show()
    loop.exec()

    # ── Post-run summary ──────────────────────────────────────────────────────
    print("\n" + "═" * 60)
    print("  SETUP COMPLETE — Summary")
    print("═" * 60)

    session = load_session()
    if session.get("logged_in"):
        method = session.get("method", "unknown")
        print(f"  ✅ Session:   logged_in=True  (method={method})")
    else:
        print(f"  ❌ Session:   NOT logged in (wizard was closed without completing)")

    # Read .env to show what was synced
    env_file = _ROOT / "wboxai_app" / ".env"
    if not env_file.is_file():
        env_file = _ROOT / ".env"

    if env_file.is_file():
        try:
            from dotenv import dotenv_values
            env = dotenv_values(env_file)
            openai_key = env.get("OPENAI_API_KEY", "")
            gemini_key = env.get("GEMINI_API_KEY", "")
            claude_key = env.get("CLAUDE_API_KEY", "")
            job_role   = env.get("JOB_ROLE", "")

            print(f"  OpenAI key:  {'✅ ' + openai_key[:12] + '...' if openai_key and openai_key.startswith('sk-') else '❌ not set'}")
            print(f"  Gemini key:  {'✅ set' if gemini_key else '❌ not set'}")
            print(f"  Claude key:  {'✅ set' if claude_key else '❌ not set'}")
            print(f"  Job role:    {job_role or '(not set)'}")
        except Exception as e:
            print(f"  (could not read .env: {e})")

    resume_file = _ROOT / "wboxai_app" / "resume_context.txt"
    if resume_file.is_file():
        size = resume_file.stat().st_size
        print(f"  Resume:      ✅ {size} bytes  ({resume_file})")
    else:
        print(f"  Resume:      ❌ not found")

    print("═" * 60)
    print(f"\n  Run the main app with:")
    print(f"    .\\venv\\Scripts\\python.exe run_app.py\n")


if __name__ == "__main__":
    main()
