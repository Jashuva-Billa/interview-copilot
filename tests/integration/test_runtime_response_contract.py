"""Regression tests for the runtime LLM response contract."""

from __future__ import annotations

import runpy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
for entry in (ROOT, ROOT / "app", ROOT / "app" / "core", ROOT / "app" / "services", ROOT / "app" / "ui", ROOT / "app" / "screen", ROOT / "app" / "monitoring", ROOT / "wboxai_app", ROOT / "audio_processing", ROOT / "llm_project"):
    value = str(entry.resolve())
    if value not in sys.path:
        sys.path.insert(0, value)

# The runtime should be testable without a developer's real .env or API key.
import project_bootstrap

_TEST_ENV_DIR = tempfile.TemporaryDirectory(prefix="interview-copilot-tests-")
_TEST_ENV_FILE = Path(_TEST_ENV_DIR.name) / ".env"
_TEST_ENV_FILE.write_text("OPENAI_API_KEY=sk-test-placeholder\n", encoding="utf-8")
project_bootstrap.ENV_FILE = _TEST_ENV_FILE

import run_app
import main
from llm_project.response_parser import ParsedResponse


class TestRuntimeResponseContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.object(main.config, "get_active_providers", return_value=["openai"]):
            cls.runner = run_app.AppRunner()

    @classmethod
    def tearDownClass(cls):
        cls.runner.executor.shutdown(wait=True)
        cls.runner.audio_executor.shutdown(wait=True)
        cls.runner.partial_executor.shutdown(wait=True)
        cls.runner.app.quit()

    def test_windows_gui_launcher_reports_missing_env(self):
        with (
            patch.object(project_bootstrap, "bootstrap", side_effect=SystemExit("Missing .env")),
            patch("PyQt6.QtWidgets.QMessageBox.critical") as show_error,
            self.assertRaises(SystemExit) as exit_error,
        ):
            runpy.run_path(str(ROOT / "app" / "run_app.py"))

        self.assertEqual(exit_error.exception.code, 1)
        self.assertIn("Missing .env", show_error.call_args.args[2])

    def test_first_launch_saves_key_and_later_launch_skips_dialog(self):
        from app import credentials

        with (
            tempfile.TemporaryDirectory() as folder,
            patch.object(credentials.config, "OPENAI_API_KEY", ""),
            patch.object(run_app, "QApplication", return_value=self.runner.app),
            patch.object(run_app.AppRunner, "run", return_value=0),
            patch.object(credentials.QInputDialog, "getText", return_value=("sk-setup-test", True)) as prompt,
        ):
            settings = Path(folder) / ".env"
            with patch.object(credentials.config, "env_file_path", return_value=settings):
                self.assertEqual(run_app.main(), 0)
                self.assertEqual(run_app.main(), 0)
            self.assertIn("sk-setup-test", settings.read_text(encoding="utf-8"))
            prompt.assert_called_once()

    def test_only_explicit_credit_errors_request_key_replacement(self):
        from llm_project.provider_credits import CreditsExhausted

        rate_limit = RuntimeError("Too many requests")
        rate_limit.code = "rate_limit_exceeded"
        with patch("app.credentials.configure_key") as configure:
            try:
                self.runner._report_error(rate_limit)
                configure.assert_not_called()
                self.runner._report_error(CreditsExhausted("openai"))
                configure.assert_called_once_with("openai", self.runner.window, exhausted=True)
            finally:
                self.runner.app.processEvents()

    def test_assessment_buttons_capture_submit_and_clear(self):
        from openai_service import ParsedResponse

        runner = self.runner
        runner.window.btn_assessment.setChecked(True)
        try:
            with patch.object(main.QTimer, "singleShot"), patch.object(runner.executor, "submit") as submit:
                runner.window.capture_assessment_requested.emit()
                runner._on_scan_jpeg_ready(b"first", "assessment")
                runner.window.capture_assessment_requested.emit()
                runner._on_scan_jpeg_ready(b"second", "assessment")
                runner.window.submit_assessment_requested.emit()
                submit.assert_called_once_with(runner._worker_solve_assessment, [b"first", b"second"])

            response = ParsedResponse(
                is_coding=True, approach="", code="print(42)", complexity="",
                edge_cases="", full_text="print(42)", problem_text="Implement the program.",
            )
            with patch("openai_service.solve_assessment_multi_image", return_value=("Done", response)):
                runner._worker_solve_assessment([b"first", b"second"])
            self.assertEqual(runner.window.columns["openai"]["code_box"].toPlainText(), "print(42)")
            runner.window.clear_assessment_requested.emit()
            self.assertEqual(runner.window.btn_submit_assessment.text(), "Submit (0)")
        finally:
            runner.window.btn_assessment.setChecked(False)
            runner.window.btn_coding.setChecked(False)

    def test_implementation_probe_sends_context_and_step_by_step_instructions(self):
        import openai_service
        from types import SimpleNamespace
        from unittest.mock import Mock

        create = Mock(return_value=[SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content="Validate the payload first."))]
        )])
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        history = [
            {"role": "user", "content": "How do you send a request to the resume API?"},
            {"role": "assistant", "content": "Use an HTTPS request to the ATS."},
        ]
        with (
            patch.object(openai_service, "_client", return_value=client),
            patch.object(openai_service.config, "get_active_providers", return_value=["openai"]),
            patch.dict(sys.modules, {"token_tracker": SimpleNamespace(tracker_instance=Mock())}),
        ):
            result = openai_service.generate_answer("Parameters?", history)
            probe_request = create.call_args.kwargs
            openai_service.generate_answer("What is polymorphism?", history)
            general_request = create.call_args.kwargs

        self.assertEqual(result["openai"].full_text, "Validate the payload first.")
        self.assertEqual(probe_request["messages"][1:-1], history)
        self.assertIn("execution order", probe_request["messages"][0]["content"])
        self.assertIn("do not verify experience", probe_request["messages"][0]["content"])
        self.assertGreater(probe_request["max_tokens"], general_request["max_tokens"])
        self.assertEqual(len(general_request["messages"]), 2)

    def test_screenshot_response_is_wrapped_for_overlay(self):
        expected = ParsedResponse(
            is_coding=True,
            approach="Use a hash map.",
            code="def solve():\\n    return 1",
            complexity="O(1)",
            edge_cases="empty input",
            full_text="Use a hash map.\\n\\ndef solve():\\n    return 1",
            problem_text="Implement solve.",
        )
        received = []
        self.runner.window.answer_ready.connect(received.append)
        try:
            with patch.object(
                main,
                "solve_from_screenshot",
                return_value=("Implement solve.", expected),
            ):
                self.runner._worker_solve_jpeg(b"fake-jpeg", "low")

            self.assertTrue(received)
            self.assertEqual(received[-1]["provider"], "openai")
            self.assertIs(received[-1]["response"], expected)
            self.assertEqual(self.runner.conversation[-1]["content"], expected.full_text)
            self.assertEqual(self.runner.window.get_last_question(), "Implement solve.")
        finally:
            try:
                self.runner.window.answer_ready.disconnect(received.append)
            except (TypeError, RuntimeError):
                pass

    def test_candidate_microphone_transcript_never_triggers_llm(self):
        before = len(self.runner.candidate_transcripts)
        chunk = main.AudioChunk(samples=[], sample_rate=16000)
        with patch.object(main, "transcribe", return_value="I used hybrid retrieval."), patch.object(
            self.runner, "_generate_for_question"
        ) as generate:
            self.runner._worker_process_candidate_audio(chunk)

        self.assertEqual(len(self.runner.candidate_transcripts), before + 1)
        self.assertEqual(self.runner.candidate_transcripts[-1], "I used hybrid retrieval.")
        self.assertIn("I used hybrid retrieval.", self.runner.window.live_transcript_box.toPlainText())
        generate.assert_not_called()

    def test_streamed_primary_answer_reaches_overlay_before_completion(self):
        partial = ParsedResponse(
            is_coding=False,
            approach="The first part",
            code="",
            complexity="",
            edge_cases="",
            full_text="The first part",
        )
        final = ParsedResponse(
            is_coding=False,
            approach="The first part, then the complete answer.",
            code="",
            complexity="",
            edge_cases="",
            full_text="The first part, then the complete answer.",
        )
        received = []
        self.runner.window.answer_ready.connect(received.append)

        def fake_generate_answer(question, conversation, force_coding, on_chunk=None):
            self.assertIsNotNone(on_chunk)
            on_chunk("openai", partial)
            return {"openai": final}

        try:
            with patch.object(main, "generate_answer", side_effect=fake_generate_answer):
                self.runner._generate_for_question("Give a short test answer.", False)

            self.assertGreaterEqual(len(received), 2)
            self.assertIs(received[0]["response"], partial)
            self.assertIs(received[-1]["response"], final)
        finally:
            try:
                self.runner.window.answer_ready.disconnect(received.append)
            except (TypeError, RuntimeError):
                pass

    def test_partial_interviewer_transcript_updates_question_without_calling_llm(self):
        self.runner._busy = False
        self.runner._finalized_utterances.discard("partial-test-1")
        with patch.object(main, "transcribe", return_value="How does hybrid retrieval work?"), patch.object(
            self.runner, "_generate_for_question"
        ) as generate:
            self.runner._worker_process_partial_audio(
                main.AudioChunk(
                    samples=[],
                    sample_rate=16000,
                    utterance_id="partial-test-1",
                    is_partial=True,
                )
            )

        self.assertEqual(
            self.runner.window.question_box.toPlainText(),
            "How does hybrid retrieval work?",
        )
        generate.assert_not_called()

    def test_late_partial_transcript_cannot_overwrite_finalized_question(self):
        self.runner._busy = False
        self.runner._finalized_utterances.add("partial-test-finalized")
        self.runner.bridge.question.emit("Final, complete question")
        with patch.object(main, "transcribe", return_value="Older partial words"):
            self.runner._worker_process_partial_audio(
                main.AudioChunk(
                    samples=[],
                    sample_rate=16000,
                    utterance_id="partial-test-finalized",
                    is_partial=True,
                )
            )

        self.assertEqual(
            self.runner.window.question_box.toPlainText(),
            "Final, complete question",
        )
        self.runner._finalized_utterances.discard("partial-test-finalized")

    def test_empty_provider_result_reports_error_and_clears_busy_state(self):
        self.runner._busy = True
        statuses = []
        self.runner.window.status_changed.connect(statuses.append)
        try:
            with patch.object(main, "generate_answer", return_value={}), patch.object(main.traceback, "print_exc"):
                self.runner._worker_force_coding("Explain a simple test.")
            self.assertFalse(self.runner._busy)
            self.assertTrue(any(status.startswith("Error:") for status in statuses))
        finally:
            try:
                self.runner.window.status_changed.disconnect(statuses.append)
            except (TypeError, RuntimeError):
                pass

    def test_failed_scan_restores_overlay_and_releases_busy_state(self):
        self.assertTrue(self.runner._try_start_work())
        with (
            patch.object(self.runner.window, "restore_after_screenshot") as restore,
            patch.object(main, "capture_screen_jpeg", side_effect=RuntimeError("capture failed")),
            patch.object(main.traceback, "print_exc"),
        ):
            self.runner._worker_capture_jpeg("high")
        restore.assert_called_once_with()
        self.assertFalse(self.runner._busy)

    def test_force_coding_drains_transcripts_in_order(self):
        self.assertTrue(self.runner._try_start_work())
        first = "How would you deploy this?"
        second = "How would you test it?"
        with (
            patch.object(self.runner, "_generate_for_question") as generate,
            patch.object(self.runner.audio_executor, "submit") as submit,
        ):
            self.runner._on_stream_final(first)
            self.runner._on_stream_final(second)
            submit.assert_not_called()
            self.runner._worker_force_coding("Write a test.")
            generate.assert_called_once_with("Write a test.", True)
            submit.assert_called_once_with(self.runner._worker_process_stream_question, first)
            self.assertTrue(self.runner._busy)
            self.runner._worker_process_stream_question(first)
            self.assertEqual(submit.call_args.args, (self.runner._worker_process_stream_question, second))
            self.runner._worker_process_stream_question(second)
            self.assertFalse(self.runner._busy)

    def test_snapshot_audio_waits_for_current_work(self):
        self.assertTrue(self.runner._try_start_work())
        chunk = main.AudioChunk(samples=[], sample_rate=16000)
        with patch.object(self.runner.audio_executor, "submit") as submit:
            self.runner._queue_question(chunk)
            submit.assert_not_called()
            self.runner._finish_work()
            submit.assert_called_once_with(self.runner._worker_process_audio, chunk)
        self.runner._finish_work()
        self.assertFalse(self.runner._busy)

    def test_final_interviewer_transcript_triggers_one_llm_call(self):
        chunk = main.AudioChunk(
            samples=[],
            sample_rate=16000,
            utterance_id="final-test-1",
        )
        with patch.object(main, "transcribe", return_value="How does retrieval augmented generation work?"), patch.object(
            self.runner, "_generate_for_question"
        ) as generate, patch.object(main, "time") as mocked_time:
            mocked_time.perf_counter.side_effect = [1.0, 1.0, 1.01, 1.02]
            self.runner._worker_process_audio(chunk)

        generate.assert_called_once_with(
            "How does retrieval augmented generation work?",
            False,
        )
        self.assertIn("final-test-1", self.runner._finalized_utterances)
        self.assertFalse(self.runner._busy)

    def test_interviewer_transcription_error_clears_busy_state(self):
        self.runner._busy = True
        statuses = []
        self.runner.window.status_changed.connect(statuses.append)
        try:
            with patch.object(main, "transcribe", side_effect=RuntimeError("transcription unavailable")), patch.object(main.traceback, "print_exc"):
                self.runner._worker_process_audio(main.AudioChunk(samples=[], sample_rate=16000))
            self.assertFalse(self.runner._busy)
            self.assertTrue(any(status.startswith("Error:") for status in statuses))
        finally:
            try:
                self.runner.window.status_changed.disconnect(statuses.append)
            except (TypeError, RuntimeError):
                pass

    def test_provider_response_dict_reaches_overlay_and_history(self):
        expected = ParsedResponse(
            is_coding=False,
            approach="A concise test answer.",
            code="",
            complexity="",
            edge_cases="",
            full_text="A concise test answer.",
        )
        received = []
        self.runner.window.answer_ready.connect(received.append)
        try:
            with patch.object(main, "generate_answer", return_value={"openai": expected}):
                self.runner._generate_for_question(
                    "Give a short test answer.", force_coding=False
                )

            self.assertTrue(received)
            self.assertEqual(received[-1]["provider"], "openai")
            self.assertIs(received[-1]["response"], expected)
            self.assertEqual(self.runner.conversation[-1]["content"], expected.full_text)
            answer_box = self.runner.window.columns["openai"]["answer_box"]
            self.assertEqual(answer_box.toPlainText(), expected.full_text)
        finally:
            try:
                self.runner.window.answer_ready.disconnect(received.append)
            except (TypeError, RuntimeError):
                pass


if __name__ == "__main__":
    unittest.main()
