from __future__ import annotations

import sys
from pathlib import Path
import unittest

_root = Path(__file__).resolve().parents[2]
for _p in (_root, _root / "wboxai_app", _root / "audio_processing", _root / "llm_project"):
    _p_str = str(_p.resolve())
    if _p_str not in sys.path:
        sys.path.insert(0, _p_str)

from audio_stt.alignment import WordAligner
from audio_stt.conversation import (
    InterviewQuestionProcessor,
    QuestionAggregator,
    QuestionDeduplicator,
    QuestionDetector,
)
from audio_stt.models import (
    AudioSourceKind,
    ConfidenceBundle,
    ConversationTurn,
    SpeakerRole,
    SpeakerSegment,
    TranscriptSegment,
)
from audio_stt.sources import source_metadata


class SpeakerAwarePipelineTests(unittest.TestCase):
    def test_question_detector_expected_cases(self):
        detector = QuestionDetector()
        cases = {
            "What is RAG?": True,
            "Explain your RAG architecture.": True,
            "Tell me about your experience with LangGraph.": True,
            "Why did you choose Milvus?": True,
            "Okay, that's interesting.": False,
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(detector.detect(text).is_question, expected)

    def test_question_aggregator_combines_fragments(self):
        detector = QuestionDetector()
        aggregator = QuestionAggregator()
        parts = ["Can you", "explain", "how you", "evaluated", "your RAG system?"]
        combined = ""
        complete = False
        for index, part in enumerate(parts):
            turn = ConversationTurn(
                speaker_id="SPEAKER_00",
                role=SpeakerRole.INTERVIEWER,
                text=part,
                start=float(index),
                end=float(index + 1),
                confidence=ConfidenceBundle(0.9, 0.9, 0.9, 0.9),
                source=AudioSourceKind.SYSTEM,
            )
            combined, complete = aggregator.update(turn, detector.detect(part))
        self.assertTrue(complete)
        self.assertEqual(combined, "Can you explain how you evaluated your RAG system?")

    def test_deduplicator_marks_similar_questions(self):
        deduper = QuestionDeduplicator(threshold=0.72)
        self.assertFalse(deduper.is_duplicate("How did you evaluate your RAG system?"))
        self.assertTrue(deduper.is_duplicate("How did you evaluate the RAG pipeline?"))

    def test_word_alignment_assigns_by_interval_overlap(self):
        transcript = TranscriptSegment(
            text="Can you explain retrieval",
            start=0.0,
            end=4.0,
            is_final=True,
        )
        aligner = WordAligner()
        words = aligner.align_words(transcript)
        groups = aligner.assign_speakers(
            words,
            (
                SpeakerSegment("SPEAKER_00", 0.0, 2.0, 0.9),
                SpeakerSegment("SPEAKER_01", 2.0, 4.0, 0.9),
            ),
        )
        self.assertEqual(groups[0].speaker, "SPEAKER_00")
        self.assertEqual(groups[1].speaker, "SPEAKER_01")
        self.assertEqual(groups[0].text, "Can you")
        self.assertEqual(groups[1].text, "explain retrieval")

    def test_processor_triggers_only_interviewer_question(self):
        processor = InterviewQuestionProcessor()
        candidate = TranscriptSegment(
            text="Sure, we used hybrid retrieval.",
            start=0.0,
            end=2.0,
            is_final=True,
            confidence=0.9,
            source=source_metadata(AudioSourceKind.MICROPHONE, 0.0, 2.0),
        )
        interviewer = TranscriptSegment(
            text="Can you explain how you evaluated your RAG system?",
            start=3.0,
            end=7.0,
            is_final=True,
            confidence=0.9,
            source=source_metadata(AudioSourceKind.SYSTEM, 3.0, 7.0),
        )
        self.assertIsNone(processor.process_transcript(candidate).question)
        decision = processor.process_transcript(interviewer)
        self.assertIsNotNone(decision.question)
        self.assertEqual(decision.question.speaker, SpeakerRole.INTERVIEWER)
        self.assertIn("evaluated your RAG system", decision.question.question)


if __name__ == "__main__":
    unittest.main()

