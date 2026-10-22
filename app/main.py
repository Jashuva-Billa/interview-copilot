"""
Interview Copilot — Windows + macOS.
Isolated project: uses only interview-copilot/.env and interview-copilot/venv.
"""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

_PROJECT_ROOT = _Path(__file__).resolve().parents[1]
for _module_dir in (
    _PROJECT_ROOT, _PROJECT_ROOT / "app" / "core", _PROJECT_ROOT / "app" / "services",
    _PROJECT_ROOT / "app" / "ui", _PROJECT_ROOT / "app" / "screen",
    _PROJECT_ROOT / "app" / "monitoring", _PROJECT_ROOT / "app" / "setup",
    _PROJECT_ROOT / "audio_processing",
):
    _module_path = str(_module_dir)
    if _module_path not in _sys.path:
        _sys.path.append(_module_path)

from project_bootstrap import bootstrap
bootstrap()

import importlib.util
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtWidgets import QApplication

import config
from audio_processing.audio_capture import AudioChunk, SpeechRecorder
from openai_service import (
    check_ssl_connectivity, format_api_error, generate_answer,
    solve_from_screenshot, transcribe,
)
from overlay import OverlayWindow
from screen_capture import capture_screen_jpeg
from screen_watcher import ScreenWatcher


class WorkerBridge(QObject):
    status = pyqtSignal(str)
    question = pyqtSignal(str)
    question_preview = pyqtSignal(str)
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
        self.audio_executor = ThreadPoolExecutor(max_workers=2)
        self.partial_executor = ThreadPoolExecutor(max_workers=1)
        self._partial_lock = threading.Lock()
        self._partial_inflight = False
        self._pending_partial_chunk: AudioChunk | None = None
        self._finalized_utterances: set[str] = set()
        self._stream_final_lock = threading.Lock()
        self._pending_stream_questions: list[str] = []
        self._live_system_stt = None
        self._streaming_stt_active = False
        self.recorder: SpeechRecorder | None = None
        self.system_recorder: SpeechRecorder | None = None
        self.mic_recorder: SpeechRecorder | None = None
        self.candidate_transcripts: list[str] = []
        self.conversation: list[dict] = []
        self._busy = False
        self._force_next_coding = False
        self._pending_scan_detail = "high"

        self._watcher = ScreenWatcher(on_change=lambda _: None)
        self._watch_timer = QTimer()
        self._watch_timer.timeout.connect(self._watch_tick_start)

        self.bridge.status.connect(self.window.status_changed.emit)
        self.bridge.question.connect(self.window.set_question)
        self.bridge.question_preview.connect(self.window.set_question_preview)
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
        self._drain_pending_stream_question()

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
            self.bridge.jpeg_ready.emit(capture_screen_jpeg(max_width=max_w, quality=quality), detail)
        except Exception as exc:
            self.bridge.error.emit(format_api_error(exc))
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
            self.conversation.append({"role": "user", "content": f"[Screen problem]\n{question}"})
            self.conversation.append({"role": "assistant", "content": response.full_text})
            self.bridge.answer.emit({"provider": "openai", "response": response})
            self.bridge.status.emit("Coding solution ready — Ctrl+Shift+S to rescan" if response.is_coding and response.code else "Ready — Ctrl+Shift+S to rescan")
        except Exception as exc:
            self.bridge.error.emit(format_api_error(exc))
            traceback.print_exc()
        finally:
            self._busy = False
            self._drain_pending_stream_question()

    def _on_watch_toggle(self, enabled: bool) -> None:
        self._watcher.enabled = enabled
        if enabled:
            self._watcher.reset()
            self._watch_timer.start(config.SCREEN_WATCH_INTERVAL_SEC * 1000)
            self.window.status_changed.emit(f"Watch on (every {config.SCREEN_WATCH_INTERVAL_SEC}s)")
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
        except Exception:
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
            self.window.status_changed.emit("Configure an LLM API key in interview-copilot/.env before listening.")
            self.window.set_listening_state(False)
            return

        self._live_system_stt = None
        self._streaming_stt_active = False
        mode = getattr(config, "AUDIO_STT_MODE", "auto").lower()
        deepgram_key = getattr(config, "DEEPGRAM_API_KEY", "")
        stream_note = "Snapshot previews (OpenAI)"
        if mode in ("auto", "streaming", "deepgram") and deepgram_key:
            if importlib.util.find_spec("deepgram") is not None:
                try:
                    from audio_processing.live_deepgram import LiveDeepgramTranscriber
                    self._live_system_stt = LiveDeepgramTranscriber(
                        api_key=deepgram_key,
                        on_partial=self._on_stream_partial,
                        on_final=self._on_stream_final,
                        on_status=self._on_stream_status,
                    )
                    self._live_system_stt.start()
                    self._streaming_stt_active = True
                    stream_note = "Word-level streaming (Deepgram)"
                except Exception as exc:
                    self._live_system_stt = None
                    self.bridge.status.emit(f"Streaming STT unavailable; using OpenAI previews: {exc}")
            else:
                self.bridge.status.emit("Install deepgram-sdk to enable streaming STT; using OpenAI previews")
        elif mode in ("streaming", "deepgram"):
            self.bridge.status.emit("DEEPGRAM_API_KEY missing in .env; using OpenAI snapshot previews")

        def on_system_chunk(chunk: AudioChunk) -> None:
            if self._streaming_stt_active:
                return  # Deepgram's speech_final event is the final utterance boundary.
            if self._busy:
                self.bridge.status.emit("Question processing is busy; waiting for the next question...")
                return
            self._busy = True
            self.audio_executor.submit(self._worker_process_audio, chunk)

        def on_system_partial(chunk: AudioChunk) -> None:
            if self._streaming_stt_active or self._busy or chunk.utterance_id in self._finalized_utterances:
                return
            with self._partial_lock:
                if self._partial_inflight:
                    self._pending_partial_chunk = chunk
                    return
                self._partial_inflight = True
            self.partial_executor.submit(self._worker_process_partial_audio, chunk)

        def on_system_status(msg: str) -> None:
            self.bridge.status.emit(f"System audio: {msg}")

        def on_mic_chunk(chunk: AudioChunk) -> None:
            self.audio_executor.submit(self._worker_process_candidate_audio, chunk)

        def on_mic_status(msg: str) -> None:
            self.bridge.status.emit(f"Microphone: {msg}")

        try:
            self.system_recorder = SpeechRecorder(
                on_chunk=on_system_chunk, on_status=on_system_status, source="system",
                on_partial=on_system_partial,
                on_frame=self._live_system_stt.push_audio if self._streaming_stt_active and self._live_system_stt else None,
                stream_only=self._streaming_stt_active,
            )
            self.system_recorder.start()
            self.recorder = self.system_recorder
            self.mic_recorder = SpeechRecorder(on_chunk=on_mic_chunk, on_status=on_mic_status, source="microphone")
            self.mic_recorder.start()
        except Exception as exc:
            for recorder in (self.mic_recorder, self.system_recorder):
                if recorder is not None:
                    try:
                        recorder.stop()
                    except Exception:
                        pass
            if self._live_system_stt is not None:
                self._live_system_stt.stop()
            self._live_system_stt = None
            self._streaming_stt_active = False
            self.recorder = self.system_recorder = self.mic_recorder = None
            self.bridge.error.emit(format_api_error(exc))
            self.window.set_listening_state(False)
            return

        system_label = getattr(self.system_recorder, "_device_label", "system input")
        mic_label = getattr(self.mic_recorder, "_device_label", "default microphone")
        self.window.status_changed.emit(f"Listening | Interviewer: {system_label[:36]} | Your mic: {mic_label[:36]} | {stream_note}")

    def _on_stream_status(self, msg: str) -> None:
        self.bridge.status.emit(f"Streaming STT: {msg}")
        lower = msg.lower()
        if "failed" in lower or "disconnected" in lower or "stopped" in lower:
            # Switch the current recorder to snapshot mode if the WebSocket closes.
            self._streaming_stt_active = False
            if self.system_recorder is not None:
                self.system_recorder.stream_only = False
                self.system_recorder.on_frame = None

    def _on_stream_partial(self, text: str) -> None:
        if text:
            self.bridge.question_preview.emit(text)

    def _on_stream_final(self, text: str) -> None:
        text = " ".join((text or "").split()).strip()
        if not text:
            return
        with self._stream_final_lock:
            if self._busy:
                self._pending_stream_questions.append(text)
                self.bridge.status.emit("Question queued while the previous answer finishes")
                return
            self._busy = True
        self.audio_executor.submit(self._worker_process_stream_question, text)

    def _worker_process_stream_question(self, text: str) -> None:
        try:
            if len(text.split()) < 2:
                self.bridge.question.emit(text)
                self.bridge.status.emit(f"Heard: \"{text}\" — waiting for a complete question...")
            else:
                force = self._force_next_coding
                self._force_next_coding = False
                self._generate_for_question(text, force)
        except Exception as exc:
            self.bridge.error.emit(format_api_error(exc))
            traceback.print_exc()
        finally:
            self._busy = False
            self._drain_pending_stream_question()

    def _drain_pending_stream_question(self) -> None:
        with self._stream_final_lock:
            if not self._pending_stream_questions or self._busy:
                return
            pending = self._pending_stream_questions.pop(0)
            self._busy = True
        self.audio_executor.submit(self._worker_process_stream_question, pending)

    def _stop_listening(self) -> None:
        for recorder in (self.mic_recorder, self.system_recorder):
            if recorder is not None:
                try:
                    recorder.stop()
                except Exception:
                    traceback.print_exc()
        if self._live_system_stt is not None:
            self._live_system_stt.stop()
        self._live_system_stt = None
        self._streaming_stt_active = False
        self.recorder = self.system_recorder = self.mic_recorder = None
        self.window.status_changed.emit("Stopped listening (system audio + microphone)")

    def _worker_process_partial_audio(self, chunk: AudioChunk) -> None:
        try:
            started = time.perf_counter()
            text = transcribe(chunk.samples, chunk.sample_rate)
            elapsed_ms = (time.perf_counter() - started) * 1000
            if text:
                print(f"[latency] partial_transcription_ms={elapsed_ms:.1f}", flush=True)
                if self.system_recorder is not None:
                    self.system_recorder.update_partial_transcript(chunk.utterance_id, text)
                if not self._busy and chunk.utterance_id not in self._finalized_utterances:
                    self.bridge.question_preview.emit(text)
        except Exception as exc:
            print(f"[audio] Partial STT skipped: {format_api_error(exc)}", flush=True)
        finally:
            pending = None
            with self._partial_lock:
                self._partial_inflight = False
                candidate = self._pending_partial_chunk
                self._pending_partial_chunk = None
                if (not self._busy and candidate is not None
                        and candidate.utterance_id not in self._finalized_utterances):
                    pending = candidate
                    self._partial_inflight = True
            if pending is not None:
                self.partial_executor.submit(self._worker_process_partial_audio, pending)

    def _worker_process_candidate_audio(self, chunk: AudioChunk) -> None:
        try:
            text = transcribe(chunk.samples, chunk.sample_rate)
            if text:
                self.candidate_transcripts.append(text)
                self.bridge.status.emit(f"Your mic heard: {text[:180]}")
        except Exception as exc:
            self.bridge.status.emit(f"Microphone transcription failed: {format_api_error(exc)}")
            traceback.print_exc()

    def _worker_process_audio(self, chunk: AudioChunk) -> None:
        if chunk.utterance_id:
            if len(self._finalized_utterances) > 128:
                self._finalized_utterances.clear()
            self._finalized_utterances.add(chunk.utterance_id)
        try:
            worker_started = time.perf_counter()
            if chunk.speech_end_at and chunk.emitted_at:
                print(f"[latency] vad_end_delay_ms={(chunk.emitted_at - chunk.speech_end_at) * 1000:.1f}", flush=True)
                print(f"[latency] audio-finalized-to-worker_ms={(worker_started - chunk.emitted_at) * 1000:.1f}", flush=True)
            self.bridge.status.emit("Finalizing interviewer question...")
            transcription_started = time.perf_counter()
            text = transcribe(chunk.samples, chunk.sample_rate)
            print(f"[latency] transcription_ms={(time.perf_counter() - transcription_started) * 1000:.1f}", flush=True)
            if not text:
                self.bridge.status.emit("Could not hear speech — turn up Meet volume / use speakers")
                return
            if len(text.split()) < 2:
                self.bridge.question.emit(text)
                self.bridge.status.emit(f"Heard: \"{text}\" — waiting for a complete question...")
                return
            force = self._force_next_coding
            self._force_next_coding = False
            self._generate_for_question(text, force)
        except Exception as exc:
            self.bridge.error.emit(format_api_error(exc))
            traceback.print_exc()
        finally:
            self._busy = False
            self._drain_pending_stream_question()

    def _generate_for_question(self, text: str, force_coding: bool) -> None:
        generation_started = time.perf_counter()
        first_token_at = None
        active_providers = config.get_active_providers()
        display_provider = "openai" if "openai" in active_providers else (active_providers[0] if active_providers else "openai")

        def on_llm_chunk(provider, parsed) -> None:
            nonlocal first_token_at
            if provider != display_provider:
                return
            if first_token_at is None:
                first_token_at = time.perf_counter()
                print(f"[latency] llm_first_token_ms={(first_token_at - generation_started) * 1000:.1f}", flush=True)
            self.bridge.answer.emit({"provider": provider, "response": parsed})

        try:
            self.bridge.question.emit(text)
            from openai_service import should_use_coding_mode
            force_coding = force_coding or text.strip().startswith("[Screen problem]")
            coding = should_use_coding_mode(text, force_coding)
            self.bridge.status.emit(f"Generating {'coding solution' if coding else 'answer'}...")
            responses = generate_answer(text, self.conversation, force_coding, on_chunk=on_llm_chunk)
            if isinstance(responses, dict):
                if not responses:
                    raise RuntimeError("No answer received from the configured LLM providers.")
                primary_provider = "openai" if "openai" in responses else next(iter(responses))
                primary_response = responses[primary_provider]
                self.bridge.answer.emit({"provider": primary_provider, "response": primary_response})
            else:
                primary_provider, primary_response = "openai", responses
                self.bridge.answer.emit({"provider": primary_provider, "response": primary_response})
            answer_text = getattr(primary_response, "full_text", "") or getattr(primary_response, "approach", "")
            if not answer_text.strip():
                raise RuntimeError("The LLM provider returned an empty answer.")
            print(f"[latency] llm_total_ms={(time.perf_counter() - generation_started) * 1000:.1f}", flush=True)
            self.conversation.append({"role": "user", "content": text})
            self.conversation.append({"role": "assistant", "content": answer_text})
            self.bridge.status.emit("Ready — listening...")
        except Exception as exc:
            self.bridge.error.emit(format_api_error(exc))
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
