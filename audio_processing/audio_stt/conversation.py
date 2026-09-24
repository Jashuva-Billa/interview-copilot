"""Stateful role, turn, question, and LLM trigger processing."""

from __future__ import annotations

import logging
import re
from collections import deque
from dataclasses import dataclass
from difflib import SequenceMatcher
from time import monotonic, monotonic_ns
from uuid import uuid4

from .alignment import WordAligner
from .diarization import SpeakerDiarizationProvider, SourceMetadataDiarizationProvider
from .models import (
    AudioSourceKind,
    ConfidenceBundle,
    ConversationState,
    ConversationTurn,
    InterviewQuestion,
    QuestionDetectionResult,
    SpeakerRole,
    SpeakerState,
    TranscriptSegment,
)

log = logging.getLogger(__name__)

QUESTION_STARTERS = {
    "what",
    "why",
    "how",
    "when",
    "where",
    "who",
    "which",
    "can",
    "could",
    "would",
    "should",
    "do",
    "does",
    "did",
    "is",
    "are",
    "was",
    "were",
}

IMPERATIVE_PATTERNS = (
    "tell me about",
    "walk me through",
    "explain",
    "describe",
    "talk about",
    "give me an example",
    "share an example",
    "help me understand",
)

TECHNICAL_HINTS = (
    "architecture",
    "system",
    "scale",
    "latency",
    "rag",
    "retrieval",
    "database",
    "api",
    "pipeline",
    "design",
    "trade-off",
)

BEHAVIORAL_HINTS = (
    "conflict",
    "challenge",
    "leadership",
    "failure",
    "strength",
    "weakness",
    "team",
)


CANDIDATE_STATEMENT_PATTERNS = (
    "thank you for",
    "thanks for giving",
    "giving this opportunity",
    "let me introduce myself",
    "my name is",
    "i worked on",
    "i have experience",
    "i used",
    "i implemented",
    "i built",
    "i am an",
    "i am a",
)


@dataclass(frozen=True, slots=True)
class PipelineDecision:
    turn: ConversationTurn | None = None
    question: InterviewQuestion | None = None
    duplicate: bool = False
    reason: str = ""
    latency_ms: float = 0.0


def _normalize_speaker_id(speaker_id: int | str | None) -> str:
    if speaker_id is None:
        return "UNKNOWN"
    s = str(speaker_id).strip()
    digits = re.sub(r"[^\d]", "", s)
    if digits:
        return str(int(digits))
    return s.upper()


class SpeakerRoleResolver:
    def __init__(self, role_confidence_threshold: float = 0.50):
        self.role_confidence_threshold = role_confidence_threshold
        self.candidate_speaker_id: str | None = None

    def calibrate_candidate(self, speaker_id: str | int | None) -> None:
        if speaker_id is None:
            return
        norm_spk = _normalize_speaker_id(speaker_id)
        if norm_spk == "UNKNOWN":
            return

        if self.candidate_speaker_id is not None:
            if self.candidate_speaker_id != norm_spk:
                print(
                    f"[CALIBRATION] candidate_speaker_id already set to {self.candidate_speaker_id}; ignoring speaker={norm_spk}",
                    flush=True,
                )
                log.info(
                    "candidate_speaker_id already set to %s; ignoring speaker=%s",
                    self.candidate_speaker_id,
                    norm_spk,
                )
            return

        self.candidate_speaker_id = norm_spk
        print(f"[CALIBRATION] candidate_speaker_id = {self.candidate_speaker_id}", flush=True)
        log.info("Calibrated candidate_speaker_id = %s", self.candidate_speaker_id)

    def reset_calibration(self) -> None:
        self.candidate_speaker_id = None
        print("[CALIBRATION] candidate speaker reset", flush=True)
        log.info("Candidate speaker calibration reset")

    def resolve(
        self,
        state: ConversationState,
        speaker_id: str | int,
        source: AudioSourceKind = AudioSourceKind.UNKNOWN,
        text: str = "",
        question_hint: bool = False,
    ) -> tuple[SpeakerRole, float]:
        norm_spk = _normalize_speaker_id(speaker_id)
        speaker = state.speakers.setdefault(norm_spk, SpeakerState())
        speaker.source_votes[source] = speaker.source_votes.get(source, 0) + 1

        # Direct microphone input can calibrate candidate speaker if not already set
        if source == AudioSourceKind.MICROPHONE and norm_spk != "UNKNOWN" and self.candidate_speaker_id is None:
            self.calibrate_candidate(norm_spk)

        # 1. Once candidate is calibrated: candidate_speaker_id -> CANDIDATE, all other speakers -> INTERVIEWER
        if self.candidate_speaker_id is not None:
            if norm_spk == self.candidate_speaker_id:
                speaker.role = SpeakerRole.CANDIDATE
                speaker.confidence = 0.95
                return SpeakerRole.CANDIDATE, 0.95
            else:
                speaker.role = SpeakerRole.INTERVIEWER
                speaker.confidence = 0.90
                return SpeakerRole.INTERVIEWER, 0.90

        # 2. Before candidate calibration: UNKNOWN
        speaker.role = SpeakerRole.UNKNOWN
        speaker.confidence = 0.0
        return SpeakerRole.UNKNOWN, 0.0


class ConversationTurnDetector:

    def __init__(self, short_pause_seconds: float = 1.2, max_merge_seconds: float = 6.0):
        self.short_pause_seconds = short_pause_seconds
        self.max_merge_seconds = max_merge_seconds

    def add_turn(self, state: ConversationState, turn: ConversationTurn) -> ConversationTurn:
        previous = state.turns[-1] if state.turns else None
        if (
            previous
            and previous.speaker_id == turn.speaker_id
            and turn.start - previous.end <= self.short_pause_seconds
            and turn.end - previous.start <= self.max_merge_seconds
        ):
            previous.text = f"{previous.text.rstrip()} {turn.text.lstrip()}".strip()
            previous.end = turn.end
            previous.confidence = ConfidenceBundle(
                transcription=min(previous.confidence.transcription, turn.confidence.transcription),
                speaker=min(previous.confidence.speaker, turn.confidence.speaker),
                role=min(previous.confidence.role, turn.confidence.role),
                question=max(previous.confidence.question, turn.confidence.question),
            )
            return previous
        state.turns.append(turn)
        if len(state.turns) > 80:
            del state.turns[:-80]
        return turn


class QuestionDetector:
    def detect(self, text: str) -> QuestionDetectionResult:
        normalized = _normalize(text)
        if not normalized:
            return QuestionDetectionResult(False, 0.0, "general", text)

        # Reject candidate statement patterns
        if any(pattern in normalized for pattern in CANDIDATE_STATEMENT_PATTERNS):
            return QuestionDetectionResult(False, 0.05, "candidate_statement", text)

        score = 0.0
        words = normalized.split()
        first = words[0] if words else ""
        
        if normalized.endswith("?"):
            score += 0.55
        if first in QUESTION_STARTERS:
            score += 0.40
        if any(pattern in normalized for pattern in IMPERATIVE_PATTERNS):
            score += 0.50
        if any(token in normalized for token in ("could you", "can you", "would you", "tell me", "walk me", "explain")):
            score += 0.25

        confidence = min(0.98, score)
        is_question = confidence >= 0.45
        return QuestionDetectionResult(
            is_question=is_question,
            confidence=confidence,
            question_type=self._question_type(normalized),
            text=_clean_question_text(text),
        )


    def _question_type(self, normalized: str) -> str:
        if "code" in normalized or "complexity" in normalized or "algorithm" in normalized:
            return "coding"
        if "system design" in normalized or ("design" in normalized and "system" in normalized):
            return "system_design"
        if any(hint in normalized for hint in BEHAVIORAL_HINTS):
            return "behavioral"
        if any(hint in normalized for hint in TECHNICAL_HINTS):
            return "technical"
        if any(word in normalized for word in ("again", "clarify", "mean by")):
            return "clarification"
        return "general"


class QuestionAggregator:
    def __init__(self, completion_timeout_seconds: float = 1.4):
        self.completion_timeout_seconds = completion_timeout_seconds
        self._pending: ConversationTurn | None = None
        self._updated_at = 0.0

    def update(self, turn: ConversationTurn, detection: QuestionDetectionResult) -> tuple[str, bool]:
        now = monotonic()
        if self._pending and self._pending.speaker_id == turn.speaker_id:
            if turn is self._pending or turn.text.startswith(self._pending.text):
                text = turn.text
            else:
                text = f"{self._pending.text.rstrip()} {turn.text.lstrip()}".strip()
            self._pending = turn
            self._pending.text = text
        else:
            self._pending = turn
        self._updated_at = now
        complete = self._looks_complete(self._pending.text, detection)
        result_text = self._pending.text
        if complete:
            self._pending = None
        return result_text, complete


    def _looks_complete(self, text: str, detection: QuestionDetectionResult) -> bool:
        stripped = text.strip()
        if stripped.endswith("?"):
            return True
        if detection.is_question and len(stripped.split()) >= 3 and stripped.endswith((".", "!")):
            return True
        if detection.is_question and (monotonic() - self._updated_at >= self.completion_timeout_seconds or self.completion_timeout_seconds <= 0):
            return True
        return False




class QuestionDeduplicator:
    def __init__(self, threshold: float = 0.86, cache_size: int = 8):
        self.threshold = threshold
        self._recent: deque[str] = deque(maxlen=cache_size)

    def is_duplicate(self, text: str) -> bool:
        normalized = _normalize(text)
        if not normalized:
            return True
        for recent in self._recent:
            if _similarity(normalized, recent) >= self.threshold:
                return True
        self._recent.append(normalized)
        return False


class InterviewQuestionProcessor:
    """Boundary between speaker-aware transcription and the LLM layer."""

    def __init__(
        self,
        *,
        state: ConversationState | None = None,
        diarization: SpeakerDiarizationProvider | None = None,
        aligner: WordAligner | None = None,
        question_confidence_threshold: float = 0.55,
        trigger_confidence_threshold: float = 0.45,
        context_turns: int = 5,
    ):
        self.state = state or ConversationState()
        self.diarization = diarization or SourceMetadataDiarizationProvider()
        self.aligner = aligner or WordAligner()
        self.roles = SpeakerRoleResolver()
        self.turns = ConversationTurnDetector()
        self.questions = QuestionDetector()
        self.aggregator = QuestionAggregator()
        self.deduper = QuestionDeduplicator()
        self.question_confidence_threshold = question_confidence_threshold
        self.trigger_confidence_threshold = trigger_confidence_threshold
        self.context_turns = context_turns

    def process_transcript(self, transcript: TranscriptSegment) -> PipelineDecision:
        started = monotonic_ns()
        if not transcript.is_final:
            return PipelineDecision(reason="partial transcript ignored")

        words = self.aligner.align_words(transcript)
        speaker_segments = self.diarization.diarize(None, 16_000, transcript)
        groups = self.aligner.assign_speakers(words, speaker_segments)
        if not groups:
            return PipelineDecision(reason="no aligned words")

        group = max(groups, key=lambda value: len(value.words))
        text = group.text or transcript.text
        detection = self.questions.detect(text)
        source = transcript.source.source if transcript.source else AudioSourceKind.UNKNOWN
        role, role_confidence = self.roles.resolve(
            self.state,
            group.speaker,
            source,
            text,
            detection.is_question,
        )
        confidence = ConfidenceBundle(
            transcription=transcript.confidence or 0.75,
            speaker=group.confidence or 0.55,
            role=role_confidence,
            question=detection.confidence,
        )
        turn = ConversationTurn(
            speaker_id=group.speaker,
            role=role,
            text=text,
            start=group.start,
            end=group.end,
            confidence=confidence,
            source=source,
            is_final=True,
        )
        turn = self.turns.add_turn(self.state, turn)
        self.state.last_processed_timestamp = max(self.state.last_processed_timestamp, turn.end)

        if role != SpeakerRole.INTERVIEWER:
            return PipelineDecision(turn=turn, reason=f"speaker role is {role.value}")
        if not detection.is_question or detection.confidence < self.question_confidence_threshold:
            return PipelineDecision(turn=turn, reason="interviewer turn is not a question")

        aggregated_text, complete = self.aggregator.update(turn, detection)
        if not complete:
            return PipelineDecision(turn=turn, reason="question not complete")

        if self.deduper.is_duplicate(aggregated_text):
            return PipelineDecision(turn=turn, duplicate=True, reason="duplicate question")

        overall_confidence = min(confidence.overall, detection.confidence)
        if overall_confidence < self.trigger_confidence_threshold:
            return PipelineDecision(turn=turn, reason="trigger confidence too low")

        recent = tuple(self.state.turns[-self.context_turns :])
        question = InterviewQuestion(
            session_id=self.state.session_id,
            question_id=f"question-{uuid4().hex}",
            question=_clean_question_text(aggregated_text),
            speaker=SpeakerRole.INTERVIEWER,
            confidence=overall_confidence,
            question_type=detection.question_type,
            recent_context=recent,
        )
        self.state.current_question = question
        return PipelineDecision(
            turn=turn,
            question=question,
            reason="question ready",
            latency_ms=(monotonic_ns() - started) / 1_000_000,
        )


def _normalize(text: str) -> str:
    value = text.lower().strip()
    value = re.sub(r"[^a-z0-9?\s-]", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def _clean_question_text(text: str) -> str:
    value = re.sub(r"\s+", " ", text).strip()
    return value[:1].upper() + value[1:] if value else value


def _similarity(left: str, right: str) -> float:
    left_words = set(left.replace("?", "").split())
    right_words = set(right.replace("?", "").split())
    if not left_words or not right_words:
        return 0.0
    jaccard = len(left_words & right_words) / len(left_words | right_words)
    sequence = SequenceMatcher(None, left, right).ratio()
    return max(jaccard, sequence)
