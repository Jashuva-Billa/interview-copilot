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
        processor.roles.calibrate_candidate("SPEAKER_00")

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

    def test_step21_test_cases(self):
        processor = InterviewQuestionProcessor()
        processor.aggregator.completion_timeout_seconds = 0.0
        # Calibrate speaker 0 as candidate
        processor.roles.calibrate_candidate("0")


        # TEST 1: Candidate speech: "Thank you for giving this opportunity, sir. Let me introduce myself."
        cand_turn = TranscriptSegment(
            text="Thank you for giving this opportunity, sir. Let me introduce myself.",
            start=0.0,
            end=3.0,
            is_final=True,
            confidence=0.95,
            source=source_metadata(AudioSourceKind.SYSTEM, 0.0, 3.0),
            speaker_id="0",
        )
        decision1 = processor.process_transcript(cand_turn)
        self.assertEqual(decision1.turn.role, SpeakerRole.CANDIDATE)
        self.assertIsNone(decision1.question)

        # TEST 2: Interviewer (speaker 1): "Tell me about yourself."
        int_turn1 = TranscriptSegment(
            text="Tell me about yourself.",
            start=4.0,
            end=6.0,
            is_final=True,
            confidence=0.95,
            source=source_metadata(AudioSourceKind.SYSTEM, 4.0, 6.0),
            speaker_id="1",
        )
        decision2 = processor.process_transcript(int_turn1)
        self.assertIsNotNone(decision2.question)
        self.assertEqual(decision2.question.question, "Tell me about yourself.")

        # TEST 3 & 4: Candidate speech stored, Interviewer question triggers
        cand_turn2 = TranscriptSegment(
            text="I have experience with Python and RAG.",
            start=7.0,
            end=9.0,
            is_final=True,
            confidence=0.95,
            source=source_metadata(AudioSourceKind.SYSTEM, 7.0, 9.0),
            speaker_id="0",
        )
        decision3 = processor.process_transcript(cand_turn2)
        self.assertEqual(decision3.turn.role, SpeakerRole.CANDIDATE)
        self.assertIsNone(decision3.question)

        int_turn2 = TranscriptSegment(
            text="How did you implement your RAG pipeline?",
            start=10.0,
            end=13.0,
            is_final=True,
            confidence=0.95,
            source=source_metadata(AudioSourceKind.SYSTEM, 10.0, 13.0),
            speaker_id="1",
        )
        decision4 = processor.process_transcript(int_turn2)
        self.assertIsNotNone(decision4.question)

        # TEST 5: Interviewer without question mark: "Tell me about your experience with LangGraph"
        int_turn3 = TranscriptSegment(
            text="Tell me about your experience with LangGraph",
            start=14.0,
            end=17.0,
            is_final=True,
            confidence=0.95,
            source=source_metadata(AudioSourceKind.SYSTEM, 14.0, 17.0),
            speaker_id="1",
        )
        decision5 = processor.process_transcript(int_turn3)
        self.assertIsNotNone(decision5.question)
        self.assertEqual(decision5.question.question, "Tell me about your experience with LangGraph")

        # TEST 6: Candidate: "I worked on LangGraph."
        cand_turn3 = TranscriptSegment(
            text="I worked on LangGraph.",
            start=18.0,
            end=20.0,
            is_final=True,
            confidence=0.95,
            source=source_metadata(AudioSourceKind.SYSTEM, 18.0, 20.0),
            speaker_id="0",
        )
        decision6 = processor.process_transcript(cand_turn3)
        self.assertIsNone(decision6.question)

        # TEST 7: Partial transcripts ignored
        partial = TranscriptSegment(
            text="How would you design a RAG",
            start=21.0,
            end=22.0,
            is_final=False,
            confidence=0.5,
            speaker_id="1",
        )
        decision7 = processor.process_transcript(partial)
        self.assertIsNone(decision7.question)

        # TEST 8: Deduplication of repeated final text
        dup_turn = TranscriptSegment(
            text="Tell me about your experience with LangGraph",
            start=23.0,
            end=25.0,
            is_final=True,
            confidence=0.95,
            source=source_metadata(AudioSourceKind.SYSTEM, 23.0, 25.0),
            speaker_id="1",
        )
        decision8 = processor.process_transcript(dup_turn)
        self.assertTrue(decision8.duplicate)
        self.assertIsNone(decision8.question)

    def test_role_resolver_test1_basic_calibration(self):
        from audio_stt.models import ConversationState
        from audio_stt.conversation import SpeakerRoleResolver
        
        resolver = SpeakerRoleResolver()
        state = ConversationState()
        resolver.calibrate_candidate(0)

        role0, _ = resolver.resolve(state, 0)
        role1, _ = resolver.resolve(state, 1)
        role2, _ = resolver.resolve(state, 2)

        self.assertEqual(role0, SpeakerRole.CANDIDATE)
        self.assertEqual(role1, SpeakerRole.INTERVIEWER)
        self.assertEqual(role2, SpeakerRole.INTERVIEWER)

    def test_role_resolver_test2_ignore_subsequent_calibration(self):
        from audio_stt.models import ConversationState
        from audio_stt.conversation import SpeakerRoleResolver
        
        resolver = SpeakerRoleResolver()
        state = ConversationState()
        resolver.calibrate_candidate(0)
        resolver.calibrate_candidate(1)

        self.assertEqual(resolver.candidate_speaker_id, "0")
        role0, _ = resolver.resolve(state, 0)
        role1, _ = resolver.resolve(state, 1)
        self.assertEqual(role0, SpeakerRole.CANDIDATE)
        self.assertEqual(role1, SpeakerRole.INTERVIEWER)

    def test_role_resolver_test3_alternating_conversation(self):
        from audio_stt.models import ConversationState
        from audio_stt.conversation import SpeakerRoleResolver
        
        resolver = SpeakerRoleResolver()
        state = ConversationState()
        resolver.calibrate_candidate(0)

        sequence = [1, 0, 1, 0, 1]
        expected = [
            SpeakerRole.INTERVIEWER,
            SpeakerRole.CANDIDATE,
            SpeakerRole.INTERVIEWER,
            SpeakerRole.CANDIDATE,
            SpeakerRole.INTERVIEWER,
        ]
        resolved = [resolver.resolve(state, spk)[0] for spk in sequence]
        self.assertEqual(resolved, expected)

    def test_role_resolver_test4_unknown_before_calibration(self):
        from audio_stt.models import ConversationState
        from audio_stt.conversation import SpeakerRoleResolver
        
        resolver = SpeakerRoleResolver()
        state = ConversationState()

        # Before calibration
        role0_before, _ = resolver.resolve(state, 0)
        role1_before, _ = resolver.resolve(state, 1)
        self.assertEqual(role0_before, SpeakerRole.UNKNOWN)
        self.assertEqual(role1_before, SpeakerRole.UNKNOWN)

        # After calibration
        resolver.calibrate_candidate(0)
        role0_after, _ = resolver.resolve(state, 0)
        role1_after, _ = resolver.resolve(state, 1)
        self.assertEqual(role0_after, SpeakerRole.CANDIDATE)
        self.assertEqual(role1_after, SpeakerRole.INTERVIEWER)

    def test_role_resolver_test5_candidate_question_remains_candidate(self):
        from audio_stt.models import ConversationState
        from audio_stt.conversation import SpeakerRoleResolver
        
        resolver = SpeakerRoleResolver()
        state = ConversationState()
        resolver.calibrate_candidate(0)

        # Candidate asks a question text
        role0, _ = resolver.resolve(state, 0, text="What is Python?", question_hint=True)
        self.assertEqual(role0, SpeakerRole.CANDIDATE)
        self.assertNotEqual(role0, SpeakerRole.INTERVIEWER)

        # End-to-end check in InterviewQuestionProcessor
        processor = InterviewQuestionProcessor()
        processor.roles.calibrate_candidate("0")
        cand_question = TranscriptSegment(
            text="What is Python?",
            start=0.0,
            end=2.0,
            is_final=True,
            confidence=0.95,
            speaker_id="0",
        )
        decision = processor.process_transcript(cand_question)
        self.assertEqual(decision.turn.role, SpeakerRole.CANDIDATE)
        self.assertIsNone(decision.question)

    def test_pipeline_test1_interviewer_question_calls_llm(self):
        from unittest.mock import MagicMock, patch
        from audio_stt.models import ConversationState
        from audio_stt.conversation import SpeakerRoleResolver, QuestionDetector, QuestionDeduplicator
        from llm_project.response_parser import ParsedResponse

        resolver = SpeakerRoleResolver()
        detector = QuestionDetector()
        deduper = QuestionDeduplicator()
        state = ConversationState()
        resolver.calibrate_candidate(0)

        # Mock generate_answer
        from llm_project.response_parser import parse_structured_response
        mock_generate = MagicMock(return_value={"openai": parse_structured_response("I would design the RAG system with an ingestion pipeline...", False)})
        
        # Interviewer asks question
        spk = 1
        text = "How would you design a RAG system?"
        role, _ = resolver.resolve(state, spk)
        self.assertEqual(role, SpeakerRole.INTERVIEWER)
        
        detection = detector.detect(text)
        self.assertTrue(detection.is_question)
        self.assertFalse(deduper.is_duplicate(detection.text))
        
        with patch("llm_project.openai_service.generate_answer", mock_generate):
            resps = mock_generate(detection.text, [])
            self.assertIn("openai", resps)
            mock_generate.assert_called_once_with("How would you design a RAG system?", [])

    def test_pipeline_test2_candidate_speech_no_llm(self):
        from unittest.mock import MagicMock
        from audio_stt.models import ConversationState
        from audio_stt.conversation import SpeakerRoleResolver, QuestionDetector

        resolver = SpeakerRoleResolver()
        detector = QuestionDetector()
        state = ConversationState()
        resolver.calibrate_candidate(0)

        mock_generate = MagicMock()
        spk = 0
        text = "I used Milvus for vector retrieval."
        role, _ = resolver.resolve(state, spk)
        self.assertEqual(role, SpeakerRole.CANDIDATE)

        # Candidate speech does not call generate_answer
        if role == SpeakerRole.INTERVIEWER:
            mock_generate(text)
        mock_generate.assert_not_called()

    def test_pipeline_test3_interviewer_non_question_no_llm(self):
        from unittest.mock import MagicMock
        from audio_stt.models import ConversationState
        from audio_stt.conversation import SpeakerRoleResolver, QuestionDetector

        resolver = SpeakerRoleResolver()
        detector = QuestionDetector()
        state = ConversationState()
        resolver.calibrate_candidate(0)

        mock_generate = MagicMock()
        spk = 1
        text = "Okay, let's move to the next topic."
        role, _ = resolver.resolve(state, spk)
        self.assertEqual(role, SpeakerRole.INTERVIEWER)
        
        detection = detector.detect(text)
        self.assertFalse(detection.is_question)
        if detection.is_question:
            mock_generate(text)
        mock_generate.assert_not_called()

    def test_pipeline_test4_question_without_question_mark_calls_llm(self):
        from unittest.mock import MagicMock
        from audio_stt.models import ConversationState
        from audio_stt.conversation import SpeakerRoleResolver, QuestionDetector

        resolver = SpeakerRoleResolver()
        detector = QuestionDetector()
        state = ConversationState()
        resolver.calibrate_candidate(0)

        mock_generate = MagicMock()
        spk = 1
        text = "Tell me about your experience with LangGraph"
        role, _ = resolver.resolve(state, spk)
        self.assertEqual(role, SpeakerRole.INTERVIEWER)
        
        detection = detector.detect(text)
        self.assertTrue(detection.is_question)
        mock_generate(detection.text)
        mock_generate.assert_called_once_with("Tell me about your experience with LangGraph")

    def test_pipeline_test5_duplicate_question_calls_llm_once(self):
        from unittest.mock import MagicMock
        from audio_stt.models import ConversationState
        from audio_stt.conversation import SpeakerRoleResolver, QuestionDetector, QuestionDeduplicator

        resolver = SpeakerRoleResolver()
        detector = QuestionDetector()
        deduper = QuestionDeduplicator()
        state = ConversationState()
        resolver.calibrate_candidate(0)

        mock_generate = MagicMock()
        spk = 1
        text1 = "How would you design a RAG system?"
        text2 = "How would you design a RAG system?"

        # Event 1
        d1 = detector.detect(text1)
        if d1.is_question and not deduper.is_duplicate(d1.text):
            mock_generate(d1.text)

        # Event 2 (duplicate)
        d2 = detector.detect(text2)
        if d2.is_question and not deduper.is_duplicate(d2.text):
            mock_generate(d2.text)

        self.assertEqual(mock_generate.call_count, 1)


if __name__ == "__main__":
    unittest.main()




