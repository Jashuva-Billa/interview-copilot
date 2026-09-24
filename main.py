"""
WboxAI — Windows 10/11.
Isolated project: uses only interview-copilot/.env and interview-copilot/venv.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Initialize application entry

# Associate taskbar icon on Windows
if sys.platform == "win32":
    import ctypes
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("whitebox.wboxai.v1")
    except Exception:
        pass

# Inject reorganized codebase package directories into Python sys.path
_ROOT = Path(__file__).resolve().parent
for _p in (_ROOT, _ROOT / "wboxai_app", _ROOT / "audio_processing", _ROOT / "llm_project"):
    _p_str = str(_p.resolve())
    if _p_str not in sys.path:
        sys.path.insert(0, _p_str)


# Bootstrap before config (venv + .env checks)
try:
    from project_bootstrap import bootstrap
    bootstrap()
except Exception as e:
    import sys
    from pathlib import Path
    
    # Check if this is a missing .env file
    is_missing_env = isinstance(e, FileNotFoundError) or "Missing configuration file" in str(e)
    
    try:
        from PyQt6.QtWidgets import QApplication, QMessageBox
    except ImportError:
        print(f"Bootstrap error: {e}", file=sys.stderr)
        sys.exit(1)
        
    app = QApplication.instance() or QApplication(sys.argv)
    
    if is_missing_env:
        try:
            from installer import SetupWizard
            wizard = SetupWizard(first_time_setup=True)
            wizard.show()
            app.exec()
            
            if getattr(wizard, "setup_successful", False):
                try:
                    from project_bootstrap import bootstrap
                    bootstrap()
                except Exception as boot_err:
                    print(f"Error bootstrapping after setup: {boot_err}", file=sys.stderr)
                    sys.exit(1)
            else:
                sys.exit(1)
        except Exception as wizard_err:
            import traceback
            err_msg = traceback.format_exc()
            box = QMessageBox()
            box.setIcon(QMessageBox.Icon.Critical)
            box.setWindowTitle("Setup Wizard Error")
            box.setText("Failed to start the configuration setup wizard.")
            box.setInformativeText(f"{str(wizard_err)}\n\n{err_msg}")
            box.exec()
            sys.exit(1)
    else:
        import traceback
        err_msg = traceback.format_exc()
        box = QMessageBox()
        box.setIcon(QMessageBox.Icon.Critical)
        box.setWindowTitle("Startup Error")
        box.setText("Failed to start WboxAI.")
        box.setInformativeText(f"{str(e)}\n\n{err_msg}")
        box.exec()
        sys.exit(1)


import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtWidgets import QApplication

import config
from audio_processing.audio_stt import (
    AudioEvent,
    AudioSourceKind,
    AudioSTTConfig,
    AudioToTextPipeline,
    EventKind,
    InterviewQuestionProcessor,
    SpeakerRole,
    TranscriptSegment,
)
from audio_processing.audio_stt.diarization import create_diarization_provider
from audio_processing.audio_stt.sources import source_metadata
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


class WorkerBridge(QObject):
    status = pyqtSignal(str)
    question = pyqtSignal(str)
    answer = pyqtSignal(object)
    error = pyqtSignal(str)
    jpeg_ready = pyqtSignal(bytes, str)
    watch_jpeg_ready = pyqtSignal(bytes, bool)
    coding_busy = pyqtSignal(bool)
    transcript = pyqtSignal(str, bool, float, object)  # text, is_final, latency_ms, speaker_id
    candidate_transcript = pyqtSignal(str, bool, object) # text, is_final, speaker_id
    live_transcript = pyqtSignal(str, str, bool)        # role, text, is_final
    listening_state = pyqtSignal(bool)




class InterviewApp:
    def __init__(self):
        self.app = QApplication.instance() or QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)
        self.app.setApplicationName("WboxAI")
        self.window = OverlayWindow()
        self.bridge = WorkerBridge()
        self.executor = ThreadPoolExecutor(max_workers=max(4, config.MAX_WORKERS))
        self.recorder: SpeechRecorder | None = None
        self.audio_pipeline: AudioToTextPipeline | None = None
        self.candidate_pipeline: AudioToTextPipeline | None = None
        self.question_processor = self._create_question_processor()
        self._pipeline_warmup_thread: threading.Thread | None = None
        self._generation_lock = threading.Lock()
        self._generation_request_id = 0
        self._last_partial_submit_time = 0.0
        self._last_submitted_text = ""
        self.backend_process = None
        self.conversation: list[dict] = []
        self._busy = False
        self._last_final_question = ""
        self._last_question_time = 0.0
        self._recent_candidate_speech = []
        self._force_next_coding = False
        self._pending_scan_detail = "high"
        self._watch_capture_pending = False
        self._shutting_down = False
        self._assessment_screenshots: list[bytes] = []

        self._watcher = ScreenWatcher(on_change=lambda _: None)
        self._watch_timer = QTimer()
        self._watch_timer.timeout.connect(self._watch_tick_start)

        self.bridge.status.connect(self.window.status_changed.emit)
        self.bridge.question.connect(self.window.set_question)
        self.bridge.answer.connect(self.window.answer_ready.emit)
        self.bridge.error.connect(self._on_error)
        self.bridge.jpeg_ready.connect(self._on_scan_jpeg_ready)
        self.bridge.watch_jpeg_ready.connect(self._on_watch_jpeg_ready)
        self.bridge.coding_busy.connect(self.window.set_coding_busy)
        self.bridge.transcript.connect(self._on_audio_transcript)
        self.bridge.candidate_transcript.connect(self._on_candidate_transcript)
        self.bridge.live_transcript.connect(self.window.update_live_transcript)
        self.bridge.listening_state.connect(self.window.set_listening_state)


        self.window.listening_toggled.connect(self._on_listen_toggle)
        self.window.force_coding_requested.connect(self._on_force_coding)
        self.window.scan_screen_requested.connect(self._on_scan_screen)
        self.window.watch_screen_toggled.connect(self._on_watch_toggle)
        self.window.refresh_requested.connect(self._on_refresh_requested)
        self.window.capture_assessment_requested.connect(self._on_capture_assessment_screenshot)
        self.window.submit_assessment_requested.connect(self._on_submit_assessment)
        self.window.clear_assessment_requested.connect(self._on_clear_assessment)
        self.window.logout_requested.connect(self._on_logout)
        self.app.aboutToQuit.connect(self._shutdown)

        if config.SCREEN_WATCH_ENABLED:
            self._watcher.enabled = True
            self._watch_timer.start(config.SCREEN_WATCH_INTERVAL_SEC * 1000)

        if config.ENTERPRISE_AUDIO:
            self._start_pipeline_warmup()

    def _audio_settings(self) -> AudioSTTConfig:
        return AudioSTTConfig(
            stt_provider=config.AUDIO_STT_PROVIDER,
            stt_model=config.AUDIO_STT_MODEL,
            language=config.AUDIO_LANGUAGE,
            vad_model_path=config.AUDIO_VAD_MODEL_PATH,
            allow_component_fallback=config.AUDIO_ALLOW_FALLBACK,
            allow_openai_stt=config.AUDIO_ALLOW_OPENAI_STT,
            speech_to_text_server_url=config.SPEECH_TO_TEXT_SERVER_URL,
            speech_to_text_provider=config.SPEECH_TO_TEXT_PROVIDER,
            speech_to_text_openai_key=config.SPEECH_TO_TEXT_OPENAI_KEY or config.OPENAI_API_KEY,
            speech_to_text_deepgram_key=config.SPEECH_TO_TEXT_DEEPGRAM_KEY,
            disable_llm_cleaning=config.DISABLE_LLM_CLEANING,
            question_confidence_threshold=config.QUESTION_CONFIDENCE_THRESHOLD,
            role_confidence_threshold=config.ROLE_CONFIDENCE_THRESHOLD,
            question_dedup_threshold=config.QUESTION_DEDUP_THRESHOLD,
            llm_trigger_confidence_threshold=config.LLM_TRIGGER_CONFIDENCE_THRESHOLD,
            context_turn_count=config.LLM_CONTEXT_TURN_COUNT,
            diarization_provider=config.AUDIO_DIARIZATION_PROVIDER,
            diarization_model=config.AUDIO_DIARIZATION_MODEL,
            pyannote_auth_token=config.PYANNOTE_AUTH_TOKEN,
        )

    def _create_question_processor(self) -> InterviewQuestionProcessor:
        settings = self._audio_settings()
        diarization = create_diarization_provider(
            settings.diarization_provider,
            model=settings.diarization_model,
            token=settings.pyannote_auth_token,
            allow_fallback=settings.allow_component_fallback,
        )
        processor = InterviewQuestionProcessor(
            diarization=diarization,
            question_confidence_threshold=settings.question_confidence_threshold,
            trigger_confidence_threshold=settings.llm_trigger_confidence_threshold,
            context_turns=settings.context_turn_count,
        )
        processor.roles.role_confidence_threshold = settings.role_confidence_threshold
        processor.deduper.threshold = settings.question_dedup_threshold
        return processor

    def _on_error(self, msg: str) -> None:
        self._busy = False
        self.window.status_changed.emit(f"Error: {msg}")

    def _on_logout(self) -> None:
        """Handle logout: clear session, hide overlay, re-show LoginDialog for re-login."""
        from login_dialog import clear_session, is_logged_in
        from PyQt6.QtCore import QEventLoop
        clear_session()
        self.window.hide()

        from login_dialog import LoginDialog
        dlg = LoginDialog()
        loop = QEventLoop()
        dlg.finished.connect(loop.quit)
        dlg.show()
        loop.exec()

        if is_logged_in():
            # Reload config from .env (keys may have changed)
            try:
                import importlib
                importlib.reload(config)
            except Exception:
                pass
            self.window.show()
            self.window.move(80, 80)
            self.window.raise_()
            self.window.status_changed.emit("Logged in — Ready")
        else:
            # Dismissed without completing login — quit
            self.app.quit()


    def _on_refresh_requested(self) -> None:
        print("[main] Refresh requested. Aborting active generation...", flush=True)
        self._generation_request_id += 1
        self._busy = False
        self.window.set_coding_busy(False)
        self.bridge.coding_busy.emit(False)
        self.window.clear_responses()
        self.window.status_changed.emit("Ready — refreshed")

    def _on_force_coding(self) -> None:
        if self._busy:
            self.window.status_changed.emit("Already generating — please wait...")
            return
        q = self.window.get_last_question().strip()
        checked = self.window.btn_coding.isChecked()
        if q:
            has_cached_code = False
            if hasattr(self.window, "_last_responses") and self.window._last_responses:
                for data in self.window._last_responses.values():
                    resp = data.get("response")
                    if resp and resp.code and resp.code.strip().upper() != "N/A":
                        has_cached_code = True
                        break
            
            if checked and not has_cached_code:
                self.window._update_all_responses_layout()
                self.window.status_changed.emit("Regenerating coding solution...")
                self.window.set_coding_busy(True)
                self._busy = True
                self._generation_request_id += 1
                self.executor.submit(
                    self._generate_for_question,
                    q,
                    checked,
                    self._generation_request_id,
                    True,
                    False,
                )
            else:
                if checked:
                    self.window.status_changed.emit("Coding mode active")
                else:
                    self.window.status_changed.emit("Standard mode active")
                self.window._update_all_responses_layout()
        else:
            self.window._update_all_responses_layout()
            if checked:
                self.window.status_changed.emit("Coding mode armed for next question")
            else:
                self.window.status_changed.emit("Standard mode armed for next question")

    def _on_scan_screen(self) -> None:
        if self._busy or self._watch_capture_pending:
            self.window.status_changed.emit("Busy — please wait...")
            return
        self._busy = True
        self._pending_scan_detail = "high"
        self.window.status_changed.emit("Capturing screen...")
        
        screen = self.window.screen()
        geom = screen.geometry() if screen else None
        screen_index = -1
        if screen:
            try:
                screen_index = QApplication.screens().index(screen)
            except Exception:
                pass

        screen_info = {
            "index": screen_index,
            "x": geom.x(),
            "y": geom.y(),
            "width": geom.width(),
            "height": geom.height(),
        } if geom else None
        
        # Capture screen for processing
        from capture_exclude import apply_to_window
        self._was_excluded = config.INVISIBLE_IN_SHARE
        if not self._was_excluded:
            apply_to_window(self.window)
        self._scan_step_capture_and_restore(screen_info)

    def _scan_step_capture_and_restore(self, screen_info: dict | None) -> None:
        try:
            detail = self._pending_scan_detail
            max_w = 1920 if detail == "high" else None
            quality = 88 if detail == "high" else None
            is_coding = self.window.btn_coding.isChecked() if hasattr(self, "window") and hasattr(self.window, "btn_coding") else False
            jpeg = capture_screen_jpeg(max_width=max_w, quality=quality, screen_info=screen_info, crop=not is_coding)
            
            if not getattr(self, "_was_excluded", False):
                from capture_exclude import restore_window
                restore_window(self.window)
            
            self.bridge.jpeg_ready.emit(jpeg, detail)
        except Exception as e:
            if not getattr(self, "_was_excluded", False):
                from capture_exclude import restore_window
                restore_window(self.window)
            self.bridge.jpeg_ready.emit(b"", self._pending_scan_detail)
            self.bridge.error.emit(format_api_error(e))
            traceback.print_exc()

    def _on_scan_jpeg_ready(self, jpeg: bytes, detail: str) -> None:
        if not jpeg:
            self._busy = False
            return
        self.window.status_changed.emit("Reading problem (AI vision)...")
        self._generation_request_id += 1
        last_question = self.window.get_last_question()
        force_coding = self.window.btn_coding.isChecked()
        self.executor.submit(
            self._worker_solve_jpeg,
            jpeg,
            detail,
            self._generation_request_id,
            last_question,
            force_coding,
        )

    def _worker_solve_jpeg(
        self,
        jpeg: bytes,
        detail: str,
        request_id: int,
        last_question: str,
        force_coding: bool,
    ) -> None:
        with self._generation_lock:
            if request_id < self._generation_request_id:
                return
            self._busy = True
            history = list(self.conversation)

        has_started = False
        def on_chunk(parsed: ParsedResponse) -> None:
            nonlocal has_started
            with self._generation_lock:
                if request_id < self._generation_request_id:
                    return
            if not has_started:
                has_started = True
                if force_coding:
                    self.bridge.status.emit("Generating coding solution (streaming)...")
                else:
                    self.bridge.status.emit("Generating answer (streaming)...")
            self.bridge.answer.emit({"provider": "openai", "response": parsed})

        def is_cancelled() -> bool:
            with self._generation_lock:
                return request_id < self._generation_request_id

        try:
            problem, response = solve_from_screenshot(
                jpeg,
                detail=detail,
                conversation=history,
                last_question=last_question,
                force_coding=force_coding,
                on_chunk=on_chunk,
                is_cancelled=is_cancelled,
            )

            with self._generation_lock:
                if request_id < self._generation_request_id:
                    return
                question = problem or response.problem_text or "(from screenshot)"
                self.bridge.question.emit(question)
                self.conversation.append(
                    {"role": "user", "content": f"[Screen problem]\n{question}"}
                )
                self.conversation.append(
                    {"role": "assistant", "content": response.full_text}
                )
                active_providers = config.get_active_providers()
                if active_providers:
                    for provider in active_providers:
                        self.bridge.answer.emit({"provider": provider, "response": response})
                else:
                    self.bridge.answer.emit({"provider": "openai", "response": response})
                if response.is_coding and response.code:
                    self.bridge.status.emit("Coding solution ready — Ctrl+Shift+S to rescan")
                else:
                    self.bridge.status.emit("Ready — Ctrl+Shift+S to rescan")
        except Exception as e:
            with self._generation_lock:
                is_current = (request_id == self._generation_request_id)
            if is_current:
                self.bridge.error.emit(format_api_error(e))
            traceback.print_exc()
        finally:
            with self._generation_lock:
                if request_id == self._generation_request_id:
                    self._busy = False

    def _on_capture_assessment_screenshot(self) -> None:
        """Capture desktop workspace uncropped and append to assessment screenshots list."""
        if self._busy:
            self.window.status_changed.emit("Busy — please wait...")
            return
        self.window.status_changed.emit("Capturing assessment screenshot...")

        screen = self.window.screen()
        geom = screen.geometry() if screen else None
        screen_index = -1
        if screen:
            try:
                screen_index = QApplication.screens().index(screen)
            except Exception:
                pass

        screen_info = {
            "index": screen_index,
            "x": geom.x(),
            "y": geom.y(),
            "width": geom.width(),
            "height": geom.height(),
        } if geom else None

        def do_capture():
            try:
                jpeg = capture_screen_jpeg(max_width=1920, quality=88, screen_info=screen_info, crop=False)
                if not getattr(self, "_was_excluded", False):
                    from capture_exclude import restore_window
                    restore_window(self.window)

                if jpeg:
                    self._assessment_screenshots.append(jpeg)
                    count = len(self._assessment_screenshots)
                    QTimer.singleShot(0, lambda: self.window.update_assessment_count(count))
            except Exception as e:
                print(f"[main] Assessment capture error: {e}", flush=True)

        from capture_exclude import apply_to_window
        self._was_excluded = config.INVISIBLE_IN_SHARE
        if not self._was_excluded:
            apply_to_window(self.window)
        do_capture()

    def _on_clear_assessment(self) -> None:
        self._assessment_screenshots.clear()
        self.window.update_assessment_count(0)
        self.window.status_changed.emit("Assessment screenshots cleared.")

    def _on_submit_assessment(self) -> None:
        if not self._assessment_screenshots:
            self.window.status_changed.emit("No assessment screenshots queued! Click '+ Capture Screen' first.")
            return
        if self._busy:
            self.window.status_changed.emit("Busy — please wait...")
            return

        self._busy = True
        self._generation_request_id += 1
        request_id = self._generation_request_id
        images = list(self._assessment_screenshots)

        self.window.status_changed.emit(f"Analyzing {len(images)} assessment screenshots (AI Vision)...")
        self.executor.submit(self._worker_solve_assessment, images, request_id)

    def _worker_solve_assessment(self, images: list[bytes], request_id: int) -> None:
        from llm_project.openai_service import solve_assessment_multi_image

        with self._generation_lock:
            if request_id < self._generation_request_id:
                return
            self._busy = True

        has_started = False
        def on_chunk(parsed: ParsedResponse) -> None:
            nonlocal has_started
            with self._generation_lock:
                if request_id < self._generation_request_id:
                    return
            if not has_started:
                has_started = True
                self.bridge.status.emit("Generating Assessment solution (streaming)...")
            self.bridge.answer.emit({"provider": "openai", "response": parsed})

        def is_cancelled() -> bool:
            with self._generation_lock:
                return request_id < self._generation_request_id

        try:
            problem, response = solve_assessment_multi_image(
                images,
                detail="high",
                on_chunk=on_chunk,
                is_cancelled=is_cancelled,
            )

            with self._generation_lock:
                if request_id < self._generation_request_id:
                    return
                self._busy = False

            active_providers = config.get_active_providers()
            if active_providers:
                for provider in active_providers:
                    self.bridge.answer.emit({"provider": provider, "response": response})
            else:
                self.bridge.answer.emit({"provider": "openai", "response": response})

            self.bridge.status.emit(f"Assessment completed ({len(images)} screenshots context)")
        except Exception as e:
            with self._generation_lock:
                if request_id < self._generation_request_id:
                    return
                self._busy = False
            self.bridge.error.emit(format_api_error(e))
            traceback.print_exc()

    def _on_watch_toggle(self, enabled: bool) -> None:
        self._watcher.enabled = enabled
        if enabled:
            self._watcher.reset()
            self._watch_timer.start(config.SCREEN_WATCH_INTERVAL_SEC * 1000)
            self.window.status_changed.emit(
                f"Watch on (every {config.SCREEN_WATCH_INTERVAL_SEC}s)"
            )
            QTimer.singleShot(0, self._watch_tick_start)
        else:
            self._watch_timer.stop()
            self._watch_capture_pending = False
            self.window.status_changed.emit("Watch off")

    def _watch_tick_start(self) -> None:
        if self._busy or self._watch_capture_pending or not self._watcher.enabled:
            return
        self._watch_capture_pending = True
        
        screen = self.window.screen()
        geom = screen.geometry() if screen else None
        screen_index = -1
        if screen:
            try:
                screen_index = QApplication.screens().index(screen)
            except Exception:
                pass

        screen_info = {
            "index": screen_index,
            "x": geom.x(),
            "y": geom.y(),
            "width": geom.width(),
            "height": geom.height(),
        } if geom else None

        self._watch_step_capture(screen_info)

    def _watch_step_capture(self, screen_info: dict | None = None) -> None:
        if not self._watcher.enabled:
            self._watch_capture_pending = False
            return
        self.executor.submit(self._worker_watch_capture, screen_info)

    def _worker_watch_capture(self, screen_info: dict | None = None) -> None:
        try:
            changed, jpeg = self._watcher.capture_and_check(screen_info)
            self.bridge.watch_jpeg_ready.emit(jpeg, changed)
        except Exception as e:
            self.bridge.watch_jpeg_ready.emit(b"", False)
            traceback.print_exc()

    def _on_watch_jpeg_ready(self, jpeg: bytes, changed: bool) -> None:
        self._watch_capture_pending = False
        if changed and jpeg and not self._busy:
            self._busy = True
            self.window.status_changed.emit("Screen changed — analyzing...")
            self._generation_request_id += 1
            last_question = self.window.get_last_question()
            self.executor.submit(
                self._worker_solve_jpeg,
                jpeg,
                "low",
                self._generation_request_id,
                last_question,
                False,
            )

    def _on_listen_toggle(self, listening: bool) -> None:
        if listening:
            self._start_listening()
        else:
            self._stop_listening()

    def _start_listening(self) -> None:
        if not config.AUDIO_ALLOW_OPENAI_STT and not config.ENTERPRISE_AUDIO:
            self.window.status_changed.emit(
                "Local STT only is enabled. Set ENTERPRISE_AUDIO=true in .env."
            )
            self.window.set_listening_state(False)
            return
        if config.ENTERPRISE_AUDIO:
            self._start_enterprise_audio()
            return
        if not config.openai_key_configured():
            self.window.status_changed.emit(
                "OpenAI key missing in interview-copilot/.env (OPENAI_API_KEY=sk-...)"
            )
            self.window.set_listening_state(False)
            return

        def on_chunk(chunk: AudioChunk) -> None:
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

    def _start_pipeline_warmup(self) -> None:
        self._pipeline_warmup_thread = threading.Thread(
            target=self._warm_up_pipeline,
            name="audio-pipeline-warmup",
            daemon=True,
        )
        self._pipeline_warmup_thread.start()

    def _warm_up_pipeline(self) -> None:
        try:
            settings = self._audio_settings()

            # 1. System/Interviewer pipeline (loopback)
            from audio_capture import _find_loopback_device
            from audio_stt.capture import RobustMicrophoneSource
            
            loopback_id = _find_loopback_device()
            sys_source = RobustMicrophoneSource(settings, device=loopback_id)
            pipeline = AudioToTextPipeline(settings, source=sys_source)

            def on_event(event: AudioEvent) -> None:
                if event.kind in (
                    EventKind.PARTIAL_TRANSCRIPT,
                    EventKind.FINAL_TRANSCRIPT,
                ) and event.transcript is not None:
                    self.bridge.transcript.emit(
                        event.transcript.text,
                        event.transcript.is_final,
                        event.transcript.latency_ms or 0.0,
                        getattr(event.transcript, "speaker_id", None),
                    )
                elif event.kind == EventKind.DEVICE_CHANGED:
                    self.bridge.status.emit(f"Interviewer mic: {event.message}")
                elif event.kind in (EventKind.WARNING, EventKind.ERROR):
                    self.bridge.status.emit(f"Audio error: {event.message}")

            pipeline.subscribe(on_event)
            self.audio_pipeline = pipeline

            # 2. Candidate pipeline (local microphone)
            mic_source = RobustMicrophoneSource(settings, device=None)
            candidate_pipeline = AudioToTextPipeline(settings, source=mic_source)

            def on_candidate_event(event: AudioEvent) -> None:
                if event.kind in (
                    EventKind.PARTIAL_TRANSCRIPT,
                    EventKind.FINAL_TRANSCRIPT,
                ) and event.transcript is not None:
                    self.bridge.candidate_transcript.emit(
                        event.transcript.text,
                        event.transcript.is_final,
                        getattr(event.transcript, "speaker_id", None),
                    )
                elif event.kind == EventKind.DEVICE_CHANGED:
                    self.bridge.status.emit(f"Candidate mic: {event.message}")
                elif event.kind in (EventKind.WARNING, EventKind.ERROR):
                    self.bridge.status.emit(f"Candidate audio error: {event.message}")

            candidate_pipeline.subscribe(on_candidate_event)
            self.candidate_pipeline = candidate_pipeline

        except Exception as exc:
            traceback.print_exc()

    def _wait_and_start_pipeline(self) -> None:
        if self._pipeline_warmup_thread:
            self._pipeline_warmup_thread.join()
        if self.audio_pipeline is not None and self.candidate_pipeline is not None:
            self._worker_start_enterprise_audio()
        else:
            self.bridge.error.emit("Failed to load speech models in background")
            self.bridge.listening_state.emit(False)

    def _init_and_start_pipeline(self) -> None:
        try:
            settings = self._audio_settings()

            # 1. System/Interviewer pipeline (loopback)
            from audio_capture import _find_loopback_device
            from audio_stt.capture import RobustMicrophoneSource
            
            loopback_id = _find_loopback_device()
            sys_source = RobustMicrophoneSource(settings, device=loopback_id)
            pipeline = AudioToTextPipeline(settings, source=sys_source)

            def on_event(event: AudioEvent) -> None:
                if event.kind in (
                    EventKind.PARTIAL_TRANSCRIPT,
                    EventKind.FINAL_TRANSCRIPT,
                ) and event.transcript is not None:
                    self.bridge.transcript.emit(
                        event.transcript.text,
                        event.transcript.is_final,
                        event.transcript.latency_ms or 0.0,
                        getattr(event.transcript, "speaker_id", None),
                    )
                elif event.kind == EventKind.DEVICE_CHANGED:
                    self.bridge.status.emit(f"Interviewer mic: {event.message}")
                elif event.kind in (EventKind.WARNING, EventKind.ERROR):
                    self.bridge.status.emit(f"Audio error: {event.message}")

            pipeline.subscribe(on_event)
            self.audio_pipeline = pipeline

            # 2. Candidate pipeline (local microphone)
            mic_source = RobustMicrophoneSource(settings, device=None)
            candidate_pipeline = AudioToTextPipeline(settings, source=mic_source)

            def on_candidate_event(event: AudioEvent) -> None:
                if event.kind in (
                    EventKind.PARTIAL_TRANSCRIPT,
                    EventKind.FINAL_TRANSCRIPT,
                ) and event.transcript is not None:
                    self.bridge.candidate_transcript.emit(
                        event.transcript.text,
                        event.transcript.is_final,
                        getattr(event.transcript, "speaker_id", None),
                    )
                elif event.kind == EventKind.DEVICE_CHANGED:
                    self.bridge.status.emit(f"Candidate mic: {event.message}")
                elif event.kind in (EventKind.WARNING, EventKind.ERROR):
                    self.bridge.status.emit(f"Candidate audio error: {event.message}")


            candidate_pipeline.subscribe(on_candidate_event)
            self.candidate_pipeline = candidate_pipeline

            self._worker_start_enterprise_audio()
        except Exception as exc:
            self.bridge.error.emit(format_api_error(exc))
            self.bridge.listening_state.emit(False)

    def _start_enterprise_audio(self) -> None:
        if self.audio_pipeline is not None and self.candidate_pipeline is not None:
            self.window.status_changed.emit("Starting role-based listening...")
            self.executor.submit(self._worker_start_enterprise_audio)
            return

        if self._pipeline_warmup_thread and self._pipeline_warmup_thread.is_alive():
            self.window.status_changed.emit("Speech models are still loading in background...")
            self.executor.submit(self._wait_and_start_pipeline)
            return

        self.window.status_changed.emit("Loading speech models...")
        self.executor.submit(self._init_and_start_pipeline)

    def _worker_start_enterprise_audio(self) -> None:
        try:
            if self.audio_pipeline is not None:
                self.audio_pipeline.start()
            if self.candidate_pipeline is not None:
                self.candidate_pipeline.start()
        except Exception as exc:
            if self.audio_pipeline is not None:
                self.audio_pipeline.stop()
            if self.candidate_pipeline is not None:
                self.candidate_pipeline.stop()
            self.bridge.error.emit(format_api_error(exc))
            self.bridge.listening_state.emit(False)
            return
        self.bridge.status.emit("Role-based audio listening started")

    def _get_word_similarity(self, s1: str, s2: str) -> float:
        w1 = set(s1.lower().replace("?", "").replace(".", "").replace(",", "").split())
        w2 = set(s2.lower().replace("?", "").replace(".", "").replace(",", "").split())
        if not w1 or not w2:
            return 0.0
        return len(w1.intersection(w2)) / len(w1.union(w2))

    def _structured_transcript(
        self,
        text: str,
        is_final: bool,
        source: AudioSourceKind,
        latency_ms: float = 0.0,
    ) -> TranscriptSegment:
        now = time.monotonic()
        words = max(1, len(text.split()))
        estimated_duration = min(12.0, max(0.35, words * 0.32))
        start = max(0.0, now - estimated_duration)
        metadata = source_metadata(source, start, now)
        confidence = 0.78 if is_final else 0.45
        if latency_ms > 0:
            confidence = min(0.90, confidence + 0.04)
        return TranscriptSegment(
            text=text,
            start=start,
            end=now,
            is_final=is_final,
            confidence=confidence,
            provider=config.AUDIO_STT_PROVIDER,
            source=metadata,
        )

    def _on_audio_transcript(
        self,
        text: str,
        is_final: bool,
        latency_ms: float = 0.0,
        speaker_id: int | str | None = None,
    ) -> None:
        text = text.strip()
        if not text:
            return

        now = time.time()

        # 1. Partial transcript handling
        if not is_final:
            self.window.status_changed.emit(f"Hearing: {text[-90:]}")
            self.bridge.live_transcript.emit("Hearing", text, False)
            return

        # 2. Final transcript handling
        spk_display = str(speaker_id) if speaker_id is not None else "unknown"
        role, role_conf = self.question_processor.roles.resolve(
            self.question_processor.state,
            speaker_id if speaker_id is not None else "UNKNOWN",
            AudioSourceKind.SYSTEM,
            text,
            False,
        )

        role_str = role.value.lower()
        print(f"[ROLE] speaker={spk_display} -> {role_str}", flush=True)

        if role == SpeakerRole.CANDIDATE:
            print(f"[CANDIDATE]\n{text}\n", flush=True)
            self.bridge.live_transcript.emit("Candidate", text, True)
            with self._generation_lock:
                self.conversation.append({"role": "user", "content": f"[Candidate] {text}"})
            return

        if role == SpeakerRole.UNKNOWN:
            print(f"[UNKNOWN]\n{text}\n", flush=True)
            self.bridge.live_transcript.emit("Unknown", text, True)
            self.window.status_changed.emit("Speaker role uncertain")
            return

        # Role is INTERVIEWER
        print(f"[INTERVIEWER]\n{text}\n", flush=True)
        self.bridge.live_transcript.emit("Interviewer", text, True)

        # Question Detection
        detection = self.question_processor.questions.detect(text)
        print(f"[QUESTION DETECTOR] question={detection.is_question}", flush=True)

        if not detection.is_question:
            self.window.status_changed.emit("Listening — interviewer statement recorded")
            with self._generation_lock:
                self.conversation.append({"role": "user", "content": f"[Interviewer] {text}"})
            return

        # Deduplication
        question_text = detection.text
        if self.question_processor.deduper.is_duplicate(question_text):
            print(f"[DEDUPLICATOR] Duplicate question ignored: '{question_text}'", flush=True)
            return

        print(f"[QUESTION]\n{question_text}\n", flush=True)

        # Update Question UI immediately
        self._last_final_question = question_text
        self._last_question_time = now
        self.window.set_question(question_text)
        self.window.status_changed.emit("Generating answer...")
        print("[LLM] generating answer...", flush=True)

        with self._generation_lock:
            self.conversation.append({"role": "user", "content": question_text})

        force = self._force_next_coding
        self._force_next_coding = False
        self._generation_request_id += 1
        self.executor.submit(
            self._generate_for_question,
            question_text,
            force,
            self._generation_request_id,
            True,
        )

    def _on_candidate_transcript(
        self,
        text: str,
        is_final: bool,
        speaker_id: int | str | None = None,
    ) -> None:
        text = text.strip()
        if not text:
            return

        spk_str = str(speaker_id) if speaker_id is not None else "CANDIDATE_MIC"
        self.question_processor.roles.calibrate_candidate(spk_str)

        if not is_final:
            self.bridge.live_transcript.emit("Candidate", text, False)
            self.window.status_changed.emit(f"You said: {text[-90:]}")
            return

        print(f"[ROLE] speaker={spk_str} -> candidate", flush=True)
        print(f"[CANDIDATE]\n{text}\n", flush=True)
        self.bridge.live_transcript.emit("Candidate", text, True)
        self.window.status_changed.emit("Candidate speech recorded")

        with self._generation_lock:
            self.conversation.append({"role": "user", "content": f"[Candidate] {text}"})


    def _stop_listening(self) -> None:
        if self.audio_pipeline is not None:
            self.audio_pipeline.stop()
        if self.candidate_pipeline is not None:
            self.candidate_pipeline.stop()
        if self.recorder:
            self.recorder.stop()
            self.recorder = None
        self.window.status_changed.emit("Stopped listening")

    def _shutdown(self) -> None:
        if self._shutting_down:
            return
        self._shutting_down = True

        candidate_name = getattr(config, "SELECTED_CANDIDATE_NAME", "UnknownCandidate")
        timestamp = getattr(config, "SESSION_TIMESTAMP", time.strftime("%Y%m%d_%H%M%S"))

        # Write token report before sending email
        try:
            from token_tracker import tracker_instance
            tracker_instance.write_report(candidate_name, timestamp)
        except Exception as e:
            print(f"Error writing token report: {e}")

        if config.EMAIL_RECEIVER:
            try:
                from email_service import send_transcript_email
                t = threading.Thread(
                    target=send_transcript_email,
                    args=(candidate_name, timestamp),
                    name="email-transcript-thread",
                    daemon=False
                )
                t.start()
            except Exception as e:
                print(f"Error launching email thread: {e}")

        self._watch_timer.stop()
        self._watcher.enabled = False

        if self.audio_pipeline is not None:
            self.audio_pipeline.stop()
            self.audio_pipeline = None
        if self.candidate_pipeline is not None:
            self.candidate_pipeline.stop()
            self.candidate_pipeline = None
        if self.recorder is not None:
            try:
                self.recorder.stop()
            except Exception:
                traceback.print_exc()
            self.recorder = None
        try:
            close_client()
        finally:
            self.executor.shutdown(wait=False, cancel_futures=True)

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
            self._generation_request_id += 1
            self._generate_for_question(text, force, self._generation_request_id, True)
        except Exception as e:
            self.bridge.error.emit(format_api_error(e))
            traceback.print_exc()

    def _generate_for_question(
        self,
        text: str,
        force_coding: bool,
        request_id: int,
        is_final: bool,
        include_history: bool = True,
    ) -> None:
        if request_id < self._generation_request_id:
            return

        with self._generation_lock:
            if request_id < self._generation_request_id:
                return

            self._busy = True
            self.bridge.question.emit(text)
            history = list(self.conversation) if include_history else []


        try:
            from openai_service import should_use_coding_mode

            force_coding = force_coding or text.strip().startswith("[Screen problem]")
            coding = should_use_coding_mode(text, force_coding)
            self.bridge.status.emit(
                f"Generating {'coding solution' if coding else 'answer'}..."
            )

            print("[LLM] Starting answer generation...", flush=True)
            print(f"[LLM] Question: {text}", flush=True)
            print("[LLM] Calling OpenAI...", flush=True)

            responses = generate_answer(
                text,
                history,
                force_coding,
                on_chunk=on_chunk,
                is_cancelled=is_cancelled,
            )

            tgt_ms = (time.perf_counter() - start_time) * 1000

            if responses:
                print("[LLM] Response received", flush=True)
                primary = "openai" if "openai" in responses else list(responses.keys())[0]
                primary_response = responses[primary]
                resp_text = primary_response.approach or primary_response.full_text
                print(f"[LLM] Response length: {len(resp_text)}", flush=True)
                print(f"[ANSWER]\n{resp_text}\n", flush=True)

                # Emit final response for all providers to ensure UI consistency
                for provider, resp in responses.items():
                    self.bridge.answer.emit({"provider": provider, "response": resp})
                print("[UI] Answer emitted", flush=True)

                if is_final:
                    self.conversation.append({"role": "user", "content": text})
                    self.conversation.append(
                        {"role": "assistant", "content": primary_response.full_text}
                    )
                    from latency_tracker import tracker
                    tracker.record_llm(text, ttft_ms or tgt_ms, tgt_ms)
            else:
                print("[LLM] No response received from providers", flush=True)

            self.bridge.status.emit("Ready — listening...")
        except Exception as e:
            print(f"[LLM][ERROR] {e}", flush=True)
            err_str = format_api_error(e)
            self.bridge.status.emit(f"Unable to generate answer: {err_str}")
            self.bridge.error.emit(err_str)
            from llm_project.response_parser import parse_structured_response
            error_response = parse_structured_response(f"Unable to generate answer: {err_str}", False)
            for provider in config.get_active_providers():
                self.bridge.answer.emit({"provider": provider, "response": error_response})
            traceback.print_exc()
        finally:
            self._busy = False
            if force_coding:
                self.bridge.coding_busy.emit(False)


    def run(self) -> int:
        self.app.setQuitOnLastWindowClosed(False)

        # ---- Login gate: show LoginDialog if no valid session ----
        from login_dialog import is_logged_in, get_candidate_mode
        if not is_logged_in():
            from login_dialog import LoginDialog
            from PyQt6.QtCore import QEventLoop
            dlg = LoginDialog()
            loop = QEventLoop()
            dlg.finished.connect(loop.quit)
            dlg.show()
            loop.exec()

            if not is_logged_in():
                # User closed the dialog without completing login
                return 0

            # Reload config so freshly-written .env keys are active
            try:
                import importlib
                importlib.reload(config)
            except Exception:
                pass

        # ---- Candidate picker — mode-aware ----
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

        # Update dynamic filepaths for latency tracker using chosen candidate
        candidate_name = getattr(config, "SELECTED_CANDIDATE_NAME", "UnknownCandidate")
        timestamp = getattr(config, "SESSION_TIMESTAMP", time.strftime("%Y%m%d_%H%M%S"))
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
    if "--config" in sys.argv or "--setup" in sys.argv:
        try:
            from PyQt6.QtWidgets import QApplication
            from installer import SetupWizard
            app = QApplication.instance() or QApplication(sys.argv)
            wizard = SetupWizard(config_only=True)
            wizard.show()
            sys.exit(app.exec())
        except Exception as e:
            print(f"Error launching configuration editor: {e}", file=sys.stderr)
            sys.exit(1)

    app = InterviewApp()
    sys.exit(app.run())


if __name__ == "__main__":
    main()
