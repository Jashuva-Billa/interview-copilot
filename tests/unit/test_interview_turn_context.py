"""Regression coverage for live question acceptance and dynamic history."""

import unittest

from audio_processing.interviewer_turn import InterviewerTurn
from llm_project.coding_detector import is_coding_question
from llm_project.interview_context import select_interview_history


class InterviewTurnAndContextTests(unittest.TestCase):
    def test_pause_noise_and_duplicate_do_not_split_a_question(self):
        intake = InterviewerTurn()
        self.assertEqual(intake.accept("How does", now=0), "")
        self.assertEqual(intake.accept("[background noise] okay", now=2), "")
        question = "How does hybrid retrieval handle filtering?"
        self.assertEqual(intake.accept("hybrid retrieval handle filtering?", now=4), question)
        self.assertEqual(intake.accept(question, now=5), "")
        self.assertEqual(intake.accept(question, now=12), question)

    def test_preserves_short_topics_and_coding_literals(self):
        intake = InterviewerTurn()
        self.assertEqual(intake.accept("LangGraph"), "LangGraph")
        self.assertEqual(intake.accept("Reverse [1, 2]"), "Reverse [1, 2]")

    def test_retrieves_older_topic_and_keeps_recent_followup_context(self):
        history = [
            {"role": "user", "content": "Describe Milvus indexing."},
            {"role": "assistant", "content": "We used HNSW."},
            {"role": "user", "content": "Explain how EKS rolls out a deployment."},
            {"role": "assistant", "content": "Deployments replace pods incrementally."},
        ]
        self.assertEqual(select_interview_history("How did Milvus handle filters?", history), history[:2])
        self.assertEqual(select_interview_history("Could you elaborate on that approach?", history), history)
        self.assertEqual(select_interview_history("What is polymorphism?", history), [])

    def test_conceptual_question_and_implementation_take_different_routes(self):
        self.assertFalse(is_coding_question("How does binary search work?"))
        self.assertFalse(is_coding_question("Explain how you classify products."))
        self.assertFalse(is_coding_question("How did you implement retries in your queue?"))
        self.assertTrue(is_coding_question("Can you implement binary search?"))
        self.assertTrue(is_coding_question("Given an array, return the longest subarray."))
