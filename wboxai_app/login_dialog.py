"""
LoginDialog — shown at startup when no valid session exists.
Provides:
  • "Login with Whitebox Learning" — browser OAuth via local callback server
  • "Setup Manually" — opens existing SetupWizard (config_only mode)
Session state is persisted in wboxai_app/.session.json.
"""

from __future__ import annotations

import json
import sys
import threading
import webbrowser
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject, QThread
from PyQt6.QtGui import QColor, QFont, QIcon, QLinearGradient, QPainter, QPalette
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

# --------------------------------------------------------------------------- #
# Session helpers
# --------------------------------------------------------------------------- #

_SESSION_FILE: Path | None = None


def _session_path() -> Path:
    global _SESSION_FILE
    if _SESSION_FILE is None:
        frozen = getattr(sys, "frozen", False)
        if frozen:
            root = Path(sys.executable).resolve().parent
        else:
            root = Path(__file__).resolve().parent
        _SESSION_FILE = root / ".session.json"
    return _SESSION_FILE


def load_session() -> dict:
    """Return persisted session or empty dict."""
    p = _session_path()
    try:
        if p.is_file():
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def save_session(data: dict) -> None:
    """Persist session data."""
    try:
        _session_path().write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[login] Could not save session: {e}", flush=True)


def clear_session() -> None:
    """Delete the session file (logout)."""
    try:
        p = _session_path()
        if p.is_file():
            p.unlink()
    except Exception as e:
        print(f"[login] Could not clear session: {e}", flush=True)


def is_logged_in() -> bool:
    s = load_session()
    return bool(s.get("logged_in"))


def get_auth_mode() -> str:
    """Return 'WHITEBOX', 'MANUAL', or '' from the current session."""
    return load_session().get("auth_mode", "")


def get_candidate_mode() -> str:
    """Return 'WHITEBOX', 'MANUAL', or '' from the current session."""
    return load_session().get("candidate_mode", "")


# --------------------------------------------------------------------------- #
# Qt signal bridge (for cross-thread communication from HTTP server thread)
# --------------------------------------------------------------------------- #

class _SignalBridge(QObject):
    auth_completed = pyqtSignal(object)


# --------------------------------------------------------------------------- #
# OAuth local server helpers  (mirrors installer.py logic)
# --------------------------------------------------------------------------- #

def _detect_wbl_base_url() -> str:
    import urllib.request
    try:
        urllib.request.urlopen("http://localhost:3000", timeout=0.4)
        return "http://localhost:3000"
    except Exception:
        return "https://www.whitebox-learning.com"


def _start_auth_server(port: int, bridge: _SignalBridge, auth_request, auth_settings) -> tuple[list, int]:
    """
    Start IPv4 + IPv6 local HTTP callback servers.
    Returns (server_list, actual_port).
    """
    import socket
    import urllib.parse
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass  # suppress console spam

        def do_GET(self):
            self._handle()

        def do_POST(self):
            self._handle()

        def do_OPTIONS(self):
            self.send_response(200)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
            self.end_headers()

        def _handle(self):
            from whitebox_auth import (
                complete_browser_callback,
                error_html,
                success_html,
            )
            parsed = urllib.parse.urlparse(self.path)
            body = b""
            if self.command == "POST":
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    body = self.rfile.read(length)
                except Exception:
                    body = b""

            result = complete_browser_callback(
                method=self.command,
                path=self.path,
                headers={k: v for k, v in self.headers.items()},
                body=body,
                settings=auth_settings,
                request=auth_request,
            )
            html = success_html() if result.authenticated else error_html(
                "We couldn't sign you in with Whitebox Learning. Please return to WboxAI and try again."
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            origin = self.headers.get("Origin") or ""
            if origin.startswith(auth_settings.base_url):
                self.send_header("Access-Control-Allow-Origin", origin)
            self.end_headers()
            self.wfile.write(html)

            bridge.auth_completed.emit(result)

    class _IPv6Server(HTTPServer):
        address_family = socket.AF_INET6

    actual_port = port
    for p in range(port, port + 10):
        try:
            s4 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s4.bind(("127.0.0.1", p))
            s4.close()
            s6 = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
            s6.bind(("::1", p))
            s6.close()
            actual_port = p
            break
        except Exception:
            pass

    servers: list = []
    try:
        srv4 = HTTPServer(("127.0.0.1", actual_port), _Handler)
        threading.Thread(target=srv4.serve_forever, daemon=True).start()
        servers.append(srv4)
    except Exception as e:
        print(f"[login] IPv4 listen failed: {e}", flush=True)
    try:
        srv6 = _IPv6Server(("::1", actual_port), _Handler)
        threading.Thread(target=srv6.serve_forever, daemon=True).start()
        servers.append(srv6)
    except Exception as e:
        print(f"[login] IPv6 listen failed: {e}", flush=True)

    return servers, actual_port


def _stop_servers(servers: list) -> None:
    for s in servers:
        try:
            s.shutdown()
            s.server_close()
        except Exception:
            pass


# --------------------------------------------------------------------------- #
# LoginDialog
# --------------------------------------------------------------------------- #

_DIALOG_CSS = """
QDialog {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #0f1724, stop:0.5 #131e2e, stop:1 #0a1628);
    border-radius: 20px;
}
QWidget#card {
    background: rgba(30, 41, 59, 0.92);
    border: 1px solid rgba(56, 189, 248, 0.18);
    border-radius: 18px;
}
QLabel#logo_title {
    color: #ffffff;
    font-size: 28px;
    font-weight: 700;
    letter-spacing: -0.5px;
}
QLabel#logo_sub {
    color: #38bdf8;
    font-size: 13px;
    font-weight: 600;
    letter-spacing: 2px;
}
QLabel#tagline {
    color: #94a3b8;
    font-size: 14px;
}
QLabel#status_lbl {
    color: #38bdf8;
    font-size: 13px;
    font-weight: 600;
    min-height: 36px;
    padding: 0 8px;
}
QPushButton#wbl_btn {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #0ea5e9, stop:1 #2563eb);
    color: #ffffff;
    border: none;
    border-radius: 12px;
    font-size: 15px;
    font-weight: 700;
    padding: 14px 28px;
    min-height: 52px;
}
QPushButton#wbl_btn:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #38bdf8, stop:1 #3b82f6);
}
QPushButton#wbl_btn:disabled {
    background: rgba(30, 41, 59, 0.7);
    color: #475569;
    border: 1px solid #334155;
}
QPushButton#manual_btn {
    background: transparent;
    color: #64748b;
    border: 1px solid #334155;
    border-radius: 10px;
    font-size: 13px;
    font-weight: 600;
    padding: 10px 20px;
    min-height: 40px;
}
QPushButton#manual_btn:hover {
    background: rgba(51, 65, 85, 0.6);
    color: #94a3b8;
    border-color: #475569;
}
QPushButton#skip_btn {
    background: transparent;
    color: #475569;
    border: none;
    font-size: 12px;
    padding: 4px 8px;
}
QPushButton#skip_btn:hover {
    color: #64748b;
}
"""


class LoginDialog(QDialog):
    """
    Shown at app startup when no valid session is found.
    Emits accepted() on successful login/setup.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("WboxAI — Login")
        self.setModal(True)
        self.setMinimumSize(480, 560)
        self.setFixedSize(480, 580)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)

        # Load icon
        frozen = getattr(sys, "frozen", False)
        if frozen:
            logo_path = Path(sys._MEIPASS) / "wboxai_app" / "logo.png"
        else:
            logo_path = Path(__file__).resolve().parent / "logo.png"
        if logo_path.is_file():
            self.setWindowIcon(QIcon(str(logo_path)))

        self.setStyleSheet(_DIALOG_CSS)
        self._servers: list = []
        self._actual_port: int = 12180
        self._auth_request = None
        self._auth_settings = None
        self._bridge = _SignalBridge()
        self._bridge.auth_completed.connect(self._on_auth_completed)

        self._build_ui()

    # ------------------------------------------------------------------ #
    # UI construction
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(0)

        card = QWidget()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(36, 40, 36, 36)
        card_layout.setSpacing(0)

        # ---- Logo / branding ----
        logo_row = QHBoxLayout()
        logo_row.setContentsMargins(0, 0, 0, 0)

        # Load logo image if available
        frozen = getattr(sys, "frozen", False)
        if frozen:
            logo_path = Path(sys._MEIPASS) / "wboxai_app" / "logo.png"
        else:
            logo_path = Path(__file__).resolve().parent / "logo.png"

        if logo_path.is_file():
            from PyQt6.QtGui import QPixmap
            from PyQt6.QtWidgets import QLabel as _QLabel
            logo_img = _QLabel()
            pix = QPixmap(str(logo_path)).scaled(
                52, 52, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            logo_img.setPixmap(pix)
            logo_img.setFixedSize(52, 52)
            logo_row.addWidget(logo_img)
            logo_row.addSpacing(14)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        lbl_title = QLabel("WboxAI")
        lbl_title.setObjectName("logo_title")
        lbl_sub = QLabel("INTERVIEW COPILOT")
        lbl_sub.setObjectName("logo_sub")
        title_col.addWidget(lbl_title)
        title_col.addWidget(lbl_sub)
        logo_row.addLayout(title_col)
        logo_row.addStretch()
        card_layout.addLayout(logo_row)
        card_layout.addSpacing(28)

        # ---- Divider ----
        div = QWidget()
        div.setFixedHeight(1)
        div.setStyleSheet("background: rgba(56, 189, 248, 0.15);")
        card_layout.addWidget(div)
        card_layout.addSpacing(28)

        # ---- Tagline ----
        tagline = QLabel("Sign in to get started with your personalized AI interview copilot.")
        tagline.setObjectName("tagline")
        tagline.setWordWrap(True)
        tagline.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(tagline)
        card_layout.addSpacing(32)

        # ---- Primary CTA: Login with Whitebox Learning ----
        self.btn_wbl = QPushButton("🌐  Login with Whitebox Learning")
        self.btn_wbl.setObjectName("wbl_btn")
        self.btn_wbl.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_wbl.clicked.connect(self._on_wbl_login_clicked)
        card_layout.addWidget(self.btn_wbl)
        card_layout.addSpacing(12)

        # ---- Secondary: Setup Manually ----
        self.btn_manual = QPushButton("⚙  Setup Manually")
        self.btn_manual.setObjectName("manual_btn")
        self.btn_manual.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_manual.clicked.connect(self._on_manual_clicked)
        card_layout.addWidget(self.btn_manual)
        card_layout.addSpacing(24)

        # ---- Status label ----
        self.status_lbl = QLabel("")
        self.status_lbl.setObjectName("status_lbl")
        self.status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_lbl.setWordWrap(True)
        card_layout.addWidget(self.status_lbl)

        card_layout.addStretch()

        # ---- Footer: skip if already configured ----
        skip_row = QHBoxLayout()
        skip_row.addStretch()
        self.btn_skip = QPushButton("Skip — already configured")
        self.btn_skip.setObjectName("skip_btn")
        self.btn_skip.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_skip.clicked.connect(self._on_skip)
        skip_row.addWidget(self.btn_skip)
        card_layout.addLayout(skip_row)

        outer.addWidget(card)

        # Drop shadow on dialog
        shadow = QGraphicsDropShadowEffect(card)
        shadow.setBlurRadius(40)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(0, 0, 0, 130))
        card.setGraphicsEffect(shadow)

    # ------------------------------------------------------------------ #
    # Actions
    # ------------------------------------------------------------------ #

    def _set_status(self, msg: str, color: str = "#38bdf8") -> None:
        self.status_lbl.setText(msg)
        self.status_lbl.setStyleSheet(
            f"QLabel#status_lbl {{ color: {color}; font-size: 13px; "
            f"font-weight: 600; min-height: 36px; padding: 0 8px; }}"
        )

    def _on_wbl_login_clicked(self) -> None:
        from whitebox_auth import build_auth_request, load_settings

        # Immediately establish the chosen mode so it survives any navigation
        # or restart between now and when OAuth completes.
        save_session({
            "logged_in": False,
            "auth_mode": "WHITEBOX",
            "candidate_mode": "WHITEBOX",
            "method": "whitebox_learning",
        })

        self.btn_wbl.setEnabled(False)
        self.btn_manual.setEnabled(False)
        self._set_status("Starting local callback server…")

        self._auth_settings = load_settings()
        port = self._auth_settings.callback_port
        self._actual_port = port
        redirect_url = f"http://127.0.0.1:{self._actual_port}/callback"
        self._auth_request = build_auth_request(self._auth_settings, redirect_url)

        # Start servers after the request is created so callback validation can
        # compare state/code_verifier against this exact login attempt.
        self._servers, self._actual_port = _start_auth_server(
            port,
            self._bridge,
            self._auth_request,
            self._auth_settings,
        )
        if self._actual_port != port:
            redirect_url = f"http://127.0.0.1:{self._actual_port}/callback"
            self._auth_request = build_auth_request(self._auth_settings, redirect_url)

        webbrowser.open(self._auth_request.login_url)
        self._set_status(
            f"Browser opened — please log in to Whitebox Learning.\n"
            f"Listening on port {self._actual_port}…"
        )

    def _on_auth_completed(self, result) -> None:
        """Called on the main thread when the browser callback arrives."""
        _stop_servers(self._servers)
        self._servers = []
        if not getattr(result, "authenticated", False):
            self._set_status(
                "We couldn't sign you in with Whitebox Learning. Please try again.",
                "#ef4444",
            )
            self.btn_wbl.setEnabled(True)
            self.btn_manual.setEnabled(True)
            print(
                f"[login] Whitebox auth failed: {getattr(result, 'error', '')} "
                f"{getattr(result, 'error_description', '')}",
                flush=True,
            )
            return

        self._set_status("Login successful! Syncing your profile…", "#10b981")

        # Save session
        save_session(result.session_payload())

        # Use the access token only for this sync. Do not persist Whitebox tokens.
        if getattr(result, "access_token", ""):
            self._sync_profile_to_env(result.access_token, result.base_url, result.user)

        # Small delay so the user can read the success message
        QTimer.singleShot(800, self.accept)

    def _sync_profile_to_env(self, token: str, base_url: str, user: dict | None = None) -> None:
        """
        Optionally syncs WBL backend data to .env.
        Gracefully no-ops if the API is unreachable.
        """
        try:
            import sys as _sys
            frozen = getattr(_sys, "frozen", False)
            root = Path(_sys.executable).resolve().parent if frozen else Path(__file__).resolve().parent
            env_file = root / ".env"

            # Try to fetch backend data (best-effort)
            try:
                from whitebox_auth import fetch_profile_sync_data

                combined = fetch_profile_sync_data(token, base_url)
                if user:
                    combined.setdefault("user", user)

                if combined:
                    openai_key = ""
                    gemini_key = ""
                    claude_key = ""
                    candidate_name = ""
                    email = ""
                    resume_text = ""
                    for field in ("openai_api_key", "openai_key", "OPENAI_API_KEY"):
                        v = combined.get(field, "")
                        if v and str(v).startswith("sk-"):
                            openai_key = str(v).strip()
                            break
                    for field in ("gemini_api_key", "gemini_key", "GEMINI_API_KEY"):
                        v = combined.get(field, "")
                        if v:
                            gemini_key = str(v).strip()
                            break
                    for field in ("claude_api_key", "claude_key", "CLAUDE_API_KEY", "anthropic_api_key"):
                        v = combined.get(field, "")
                        if v:
                            claude_key = str(v).strip()
                            break
                    identity = combined.get("user") if isinstance(combined.get("user"), dict) else combined
                    if isinstance(identity, dict):
                        candidate_name = str(identity.get("name") or identity.get("full_name") or "").strip()
                        email = str(identity.get("email") or "").strip()
                    for field in ("resume", "resume_text", "candidate_resume"):
                        v = combined.get(field, "")
                        if isinstance(v, (dict, list)):
                            resume_text = json.dumps(v, indent=2)
                            break
                        if isinstance(v, str) and len(v.strip()) > len(resume_text):
                            resume_text = v.strip()

                    if openai_key or gemini_key or claude_key or candidate_name or email:
                        lines = env_file.read_text(encoding="utf-8").splitlines(keepends=True) if env_file.is_file() else []
                        updated: dict[str, str] = {}
                        if openai_key:
                            updated["OPENAI_API_KEY"] = openai_key
                        if gemini_key:
                            updated["GEMINI_API_KEY"] = gemini_key
                        if claude_key:
                            updated["CLAUDE_API_KEY"] = claude_key
                        if candidate_name:
                            updated["WHITEBOX_USER_NAME"] = candidate_name
                        if email:
                            updated["WHITEBOX_USER_EMAIL"] = email

                        new_lines = []
                        replaced_keys: set[str] = set()
                        for line in lines:
                            stripped = line.rstrip("\r\n")
                            matched = False
                            for k in list(updated.keys()):
                                if stripped.startswith(f"{k}=") or stripped.startswith(f"{k} ="):
                                    new_lines.append(f"{k}={updated[k]}\n")
                                    replaced_keys.add(k)
                                    matched = True
                                    break
                            if not matched:
                                new_lines.append(line if line.endswith("\n") else line + "\n")

                        for k, v in updated.items():
                            if k not in replaced_keys:
                                new_lines.append(f"{k}={v}\n")

                        env_file.write_text("".join(new_lines), encoding="utf-8")
                        print(f"[login] .env updated with WBL sync data: {list(updated.keys())}", flush=True)
                    if resume_text:
                        resume_path = root / "resume_context.txt"
                        resume_path.write_text(resume_text, encoding="utf-8")
                        print(f"[login] Resume synced to {resume_path}", flush=True)
            except Exception as sync_err:
                print(f"[login] WBL backend sync skipped: {sync_err}", flush=True)

        except Exception as e:
            print(f"[login] profile sync error: {e}", flush=True)

    def _on_manual_clicked(self) -> None:
        """Open the existing SetupWizard in config-only mode."""
        try:
            from installer import SetupWizard
            self._set_status("Opening manual setup wizard…")
            self.btn_wbl.setEnabled(False)
            self.btn_manual.setEnabled(False)

            # Record the chosen mode before wizard opens so it survives navigation.
            save_session({
                "logged_in": False,
                "auth_mode": "MANUAL",
                "candidate_mode": "MANUAL",
                "method": "manual",
            })

            wizard = SetupWizard(config_only=True)
            wizard.setWindowFlags(
                wizard.windowFlags() | Qt.WindowType.WindowStaysOnTopHint
            )

            def _on_wizard_closed():
                # If wizard closed without saving, re-enable buttons
                if not is_logged_in():
                    self.btn_wbl.setEnabled(True)
                    self.btn_manual.setEnabled(True)
                    self._set_status("")
                else:
                    # Ensure manual mode is preserved regardless of what installer wrote
                    session = load_session()
                    if not session.get("auth_mode"):
                        session["auth_mode"] = "MANUAL"
                    if not session.get("candidate_mode"):
                        session["candidate_mode"] = "MANUAL"
                    save_session(session)
                    self.accept()

            wizard.closed.connect(_on_wizard_closed)
            wizard.show()
        except Exception as e:
            self._set_status(f"Error: {e}", "#ef4444")
            self.btn_wbl.setEnabled(True)
            self.btn_manual.setEnabled(True)

    def _on_skip(self) -> None:
        """Skip login — user already has .env configured."""
        # Preserve any existing auth_mode/candidate_mode; default to MANUAL for skipped.
        session = load_session()
        session["logged_in"] = True
        session["method"] = "skipped"
        session.setdefault("auth_mode", "MANUAL")
        session.setdefault("candidate_mode", "MANUAL")
        save_session(session)
        self.accept()

    def closeEvent(self, event) -> None:
        _stop_servers(self._servers)
        super().closeEvent(event)

    def reject(self) -> None:
        _stop_servers(self._servers)
        super().reject()
