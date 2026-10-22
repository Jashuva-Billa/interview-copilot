"""Unit tests for structured LLM response parsing."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for entry in (ROOT, ROOT / "wboxai_app", ROOT / "audio_processing", ROOT / "llm_project"):
    value = str(entry.resolve())
    if value not in sys.path:
        sys.path.insert(0, value)

from llm_project.response_parser import parse_structured_response, parse_vision_response


class ResponseParserTests(unittest.TestCase):
    def test_behavioral_response_is_preserved_as_plain_text(self):
        text = "I used hybrid retrieval and reranking."
        parsed = parse_structured_response(text, is_coding=False)
        self.assertEqual(parsed.approach, text)
        self.assertEqual(parsed.full_text, text)
        self.assertEqual(parsed.code, "")
        self.assertFalse(parsed.is_coding)

    def test_coding_sections_are_parsed(self):
        raw = (
            "===PROBLEM===\nFind a pair.\n"
            "===APPROACH===\nUse a hash map.\n"
            "===COMPLEXITY===\nTime: O(n)\n"
            "===CODE===\ndef solve():\n    return 1\n"
            "===EDGE_CASES===\nEmpty input\n"
        )
        parsed = parse_structured_response(raw, is_coding=True)
        self.assertTrue(parsed.is_coding)
        self.assertEqual(parsed.problem_text, "Find a pair.")
        self.assertIn("Use a hash map.", parsed.approach)
        self.assertIn("O(n)", parsed.complexity)
        self.assertIn("def solve():", parsed.code)
        self.assertIn("Empty input", parsed.edge_cases)

    def test_vision_response_returns_problem_and_parsed_solution(self):
        raw = (
            "===PROBLEM===\nReverse a string.\n"
            "===APPROACH===\nTwo pointers.\n"
            "===CODE===\nprint('ok')"
        )
        problem, parsed = parse_vision_response(raw)
        self.assertEqual(problem, "Reverse a string.")
        self.assertEqual(parsed.problem_text, problem)
        self.assertIn("print('ok')", parsed.code)

    def test_unstructured_coding_response_does_not_crash(self):
        parsed = parse_structured_response("Try sorting first.", is_coding=True)
        self.assertTrue(parsed.is_coding)
        self.assertEqual(parsed.approach, "Try sorting first.")
        self.assertEqual(parsed.code, "")


if __name__ == "__main__":
    unittest.main()
