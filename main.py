"""
Interview Copilot — Windows + macOS.
Isolated project: uses only interview-copilot/.env and interview-copilot/venv.
"""

from __future__ import annotations

# Bootstrap before config (venv + .env checks)
from project_bootstrap import bootstrap

bootstrap()

import sys
import traceback
from concurrent.futures import ThreadPoolExecutor

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtWidgets import QApplication

import config
from audio_capture import AudioChunk, SpeechRecorder
from openai_service import (
    check_ssl_connectivity,
    format_api_error,
    generate_answer,
    solve_from_screenshot,
    transcribe,
)
from overlay import OverlayWindow
from screen_capture import capture_screen_jpeg
from screen_watcher import ScreenWatcher


class WorkerBridge(QObject):
    status = pyqtSignal(str)
    question = pyqtSignal(str)
    answer = pyqtSignal(object)
    error = pyqtSignal(str)
    jpeg_ready = pyqtSignal(bytes, str)
    watch_jpeg_ready = pyqtSignal(bytes, bool)


class InterviewApp:
    def __init__(self):
        self.app = QApplication(sys.argv)
        self.app.setApplicationName("Interview Copilot")
        self.window = OverlayWindow()
        self.bridge = WorkerBridge()
        self.executor = ThreadPoolExecutor(max_workers=config.MAX_WORKERS)
        self.recorder: SpeechRecorder | None = None
        self.conversation: list[dict] = []
        self._busy = False
        self._force_next_coding = False
        self._pending_scan_detail = "high"

        self._watcher = ScreenWatcher(on_change=lambda _: None)
        self._watch_timer = QTimer()
        self._watch_timer.timeout.connect(self._watch_tick_start)

        self.bridge.status.connect(self.window.status_changed.emit)
        self.bridge.question.connect(self.window.set_question)
        self.bridge.answer.connect(self.window.answer_ready.emit)
        self.bridge.error.connect(self._on_error)
        self.bridge.jpeg_ready.connect(self._on_scan_jpeg_ready)
        self.bridge.watch_jpeg_ready.connect(self._on_watch_jpeg_ready)

        self.window.listening_toggled.connect(self._on_listen_toggle)
        self.window.force_coding_requested.connect(self._on_force_coding)
        self.window.scan_screen_requested.connect(self._on_scan_screen)
        self.window.watch_screen_toggled.connect(self._on_watch_toggle)

        if config.SCREEN_WATCH_ENABLED:
            self._watcher.enabled = True
            self._watch_timer.start(config.SCREEN_WATCH_INTERVAL_SEC * 1000)

    def _on_error(self, msg: str) -> None:
        self._busy = False
        self.window.status_changed.emit(f"Error: {msg}")

    def _on_force_coding(self) -> None:
        q = self.window.get_last_question().strip()
        if q:
            self.window.status_changed.emit("Regenerating coding solution...")
            self._busy = True
            self.executor.submit(self._generate_for_question, q, True)
        else:
            self._force_next_coding = True
            self.window.status_changed.emit("Coding mode armed for next question")

    def _on_scan_screen(self) -> None:
        if self._busy:
            self.window.status_changed.emit("Busy — please wait...")
            return
        self._busy = True
        self._pending_scan_detail = "high"
        self.window.status_changed.emit("Capturing screen...")
        self.window.hide_for_screenshot()
        QTimer.singleShot(120, self._scan_step_capture)

    def _scan_step_capture(self) -> None:
        self.executor.submit(self._worker_capture_jpeg, self._pending_scan_detail)

    def _worker_capture_jpeg(self, detail: str) -> None:
        try:
            max_w = 1920 if detail == "high" else None
            quality = 88 if detail == "high" else None
            jpeg = capture_screen_jpeg(max_width=max_w, quality=quality)
            self.bridge.jpeg_ready.emit(jpeg, detail)
        except Exception as e:
            self.bridge.error.emit(format_api_error(e))
            traceback.print_exc()

    def _on_scan_jpeg_ready(self, jpeg: bytes, detail: str) -> None:
        self.window.restore_after_screenshot()
        self.window.status_changed.emit("Reading problem (AI vision)...")
        self.executor.submit(self._worker_solve_jpeg, jpeg, detail)

    def _worker_solve_jpeg(self, jpeg: bytes, detail: str) -> None:
        try:
            problem, response = solve_from_screenshot(jpeg, detail=detail)
            question = problem or response.problem_text or "(from screenshot)"
            self.bridge.question.emit(question)
            self.conversation.append(
                {"role": "user", "content": f"[Screen problem]\n{question}"}
            )
            self.conversation.append(
                {"role": "assistant", "content": response.full_text}
            )
            self.bridge.answer.emit(response)
            if response.is_coding and response.code:
                self.bridge.status.emit("Coding solution ready — Ctrl+Shift+S to rescan")
            else:
                self.bridge.status.emit("Ready — Ctrl+Shift+S to rescan")
        except Exception as e:
            self.bridge.error.emit(format_api_error(e))
            traceback.print_exc()
        finally:
            self._busy = False

    def _on_watch_toggle(self, enabled: bool) -> None:
        self._watcher.enabled = enabled
        if enabled:
            self._watcher.reset()
            self._watch_timer.start(config.SCREEN_WATCH_INTERVAL_SEC * 1000)
            self.window.status_changed.emit(
                f"Watch on (every {config.SCREEN_WATCH_INTERVAL_SEC}s)"
            )
        else:
            self._watch_timer.stop()
            self.window.status_changed.emit("Watch off")

    def _watch_tick_start(self) -> None:
        if self._busy or not self._watcher.enabled:
            return
        self.window.hide_for_screenshot()
        QTimer.singleShot(120, self._watch_step_capture)

    def _watch_step_capture(self) -> None:
        self.executor.submit(self._worker_watch_capture)

    def _worker_watch_capture(self) -> None:
        try:
            changed, jpeg = self._watcher.capture_and_check()
            self.bridge.watch_jpeg_ready.emit(jpeg, changed)
        except Exception as e:
            self.bridge.watch_jpeg_ready.emit(b"", False)
            traceback.print_exc()

    def _on_watch_jpeg_ready(self, jpeg: bytes, changed: bool) -> None:
        self.window.restore_after_screenshot()
        if changed and jpeg and not self._busy:
            self._busy = True
            self.window.status_changed.emit("Screen changed — analyzing...")
            self.executor.submit(self._worker_solve_jpeg, jpeg, "low")

    def _on_listen_toggle(self, listening: bool) -> None:
        if listening:
            self._start_listening()
        else:
            self._stop_listening()

    def _start_listening(self) -> None:
        if not config.openai_key_configured():
            self.window.status_changed.emit(
                "OpenAI key missing in interview-copilot/.env (OPENAI_API_KEY=sk-...)"
            )
            self.window.set_listening_state(False)
            return

        def on_chunk(chunk: AudioChunk) -> None:
            if self._busy:
                self.bridge.status.emit("Still processing last question — hang on...")
                return
            self._busy = True
            self.executor.submit(self._worker_process_audio, chunk)

        def on_status(msg: str) -> None:
            self.bridge.status.emit(msg)

        self.recorder = SpeechRecorder(on_chunk=on_chunk, on_status=on_status)
        try:
            self.recorder.start()
        except Exception as e:
            self.bridge.error.emit(format_api_error(e))
            self.window.set_listening_state(False)
            return
        label = getattr(self.recorder, "_device_label", "")
        mode = "system audio" if self.recorder and self.recorder._loopback else "microphone"
        self.window.status_changed.emit(
            f"Listening ({mode}) — {label[:50]} — click Stop when done"
        )

    def _stop_listening(self) -> None:
        if self.recorder:
            self.recorder.stop()
            self.recorder = None
        self.window.status_changed.emit("Stopped listening")

    def _worker_process_audio(self, chunk: AudioChunk) -> None:
        try:
            self.bridge.status.emit("Transcribing interviewer audio...")
            text = transcribe(chunk.samples, chunk.sample_rate)
            if not text:
                self.bridge.status.emit(
                    "Could not hear speech — turn up Meet volume / use speakers"
                )
                return
            if len(text.split()) < 2:
                self.bridge.status.emit(f"Heard: \"{text}\" — waiting for full question...")
                return
            force = self._force_next_coding
            self._force_next_coding = False
            self._generate_for_question(text, force)
        except Exception as e:
            self.bridge.error.emit(format_api_error(e))
            traceback.print_exc()
        finally:
            self._busy = False

    def _generate_for_question(self, text: str, force_coding: bool) -> None:
        try:
            self.bridge.question.emit(text)
            from openai_service import should_use_coding_mode

            force_coding = force_coding or text.strip().startswith("[Screen problem]")
            coding = should_use_coding_mode(text, force_coding)
            self.bridge.status.emit(
                f"Generating {'coding solution' if coding else 'answer'}..."
            )
            response = generate_answer(text, self.conversation, force_coding)
            self.conversation.append({"role": "user", "content": text})
            self.conversation.append(
                {"role": "assistant", "content": response.full_text}
            )
            self.bridge.answer.emit(response)
            self.bridge.status.emit("Ready — listening...")
        except Exception as e:
            self.bridge.error.emit(format_api_error(e))
            traceback.print_exc()
        finally:
            self._busy = False

    def run(self) -> int:
        plat = "macOS" if config.IS_MAC else "Windows"
        self.window.show()
        self.window.move(80, 80)
        self.window.raise_()
        if not config.STEALTH_FOCUS:
            self.window.activateWindow()
        QTimer.singleShot(300, self.window._apply_exclude_once)
        msg = f"Ready ({plat})"
        if config.openai_key_configured():
            msg += " · API key OK"
            ssl_ok, ssl_note = check_ssl_connectivity()
            msg += f" · {ssl_note}" if ssl_ok else f" · {ssl_note}"
        else:
            msg += " · set OPENAI_API_KEY in interview-copilot/.env"
        if config.use_transparent_overlay():
            msg += " · transparent"
        else:
            msg += " · opaque"
        if config.INVISIBLE_IN_SHARE:
            msg += " · share-hide on"
        if config.LIGHTWEIGHT_MODE:
            msg += " · lightweight"
        if config.STEALTH_FOCUS:
            msg += " · stealth (hover+scroll)"
        if config.load_resume_context():
            msg += " · resume loaded"
        self.window.status_changed.emit(msg)
        if self._watcher.enabled:
            self.window.set_watch_checked(True)
        return self.app.exec()


def main() -> None:
    app = InterviewApp()
    sys.exit(app.run())


if __name__ == "__main__":
    main()
