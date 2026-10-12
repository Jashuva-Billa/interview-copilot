"""Regression tests for the runtime LLM response contract."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
for entry in (ROOT, ROOT / "wboxai_app", ROOT / "audio_processing", ROOT / "llm_project"):
    value = str(entry.resolve())
    if value not in sys.path:
        sys.path.insert(0, value)

import run_app
import main
from llm_project.response_parser import ParsedResponse


class TestRuntimeResponseContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runner = run_app.AppRunner()

    @classmethod
    def tearDownClass(cls):
        cls.runner.executor.shutdown(wait=True)
        cls.runner.app.quit()

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
            self.assertIn("openai", self.runner.window._last_responses)
        finally:
            try:
                self.runner.window.answer_ready.disconnect(received.append)
            except (TypeError, RuntimeError):
                pass


if __name__ == "__main__":
    unittest.main()
