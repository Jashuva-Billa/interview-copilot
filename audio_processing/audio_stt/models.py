"""Structured data contracts for speaker-aware interview audio."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from time import monotonic_ns
from typing import Any
from uuid import uuid4


class AudioSourceKind(str, Enum):
    SYSTEM = "system"
    MICROPHONE = "microphone"
    COMBINED = "combined"
    UNKNOWN = "unknown"


class SpeakerRole(str, Enum):
    INTERVIEWER = "INTERVIEWER"
    CANDIDATE = "CANDIDATE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class TranscriptEvent:
    text: str
    speaker_id: int | None = None
    role: SpeakerRole = SpeakerRole.UNKNOWN
    is_final: bool = True
    confidence: float | None = None
    timestamp: float | None = None
    utterance_id: str = ""
    provider: str = "deepgram"
    latency_ms: float | None = None


@dataclass(frozen=True, slots=True)
class SourceMetadata:
    source: AudioSourceKind
    audio_chunk_id: str
    timestamp_start: float
    timestamp_end: float


@dataclass(frozen=True, slots=True)
class WordTimestamp:
    word: str
    start: float
    end: float
    confidence: float | None = None


@dataclass(frozen=True, slots=True)
class TranscriptSegment:
    text: str
    start: float
    end: float
    is_final: bool
    language: str | None = None
    confidence: float | None = None
    provider: str = ""
    words: tuple[WordTimestamp, ...] = ()
    source: SourceMetadata | None = None
    speaker_id: int | str | None = None


@dataclass(frozen=True, slots=True)
class SpeakerSegment:
    speaker: str
    start: float
    end: float
    confidence: float | None = None


@dataclass(frozen=True, slots=True)
class SpeakerWordGroup:
    speaker: str
    words: tuple[WordTimestamp, ...]
    confidence: float | None = None

    @property
    def text(self) -> str:
        return " ".join(word.word for word in self.words).strip()

    @property
    def start(self) -> float:
        return self.words[0].start if self.words else 0.0

    @property
    def end(self) -> float:
        return self.words[-1].end if self.words else 0.0


@dataclass(slots=True)
class SpeakerState:
    role: SpeakerRole = SpeakerRole.UNKNOWN
    confidence: float = 0.0
    source_votes: dict[AudioSourceKind, int] = field(default_factory=dict)
    question_votes: int = 0
    answer_votes: int = 0


@dataclass(frozen=True, slots=True)
class ConfidenceBundle:
    transcription: float = 0.0
    speaker: float = 0.0
    role: float = 0.0
    question: float = 0.0

    @property
    def overall(self) -> float:
        values = [self.transcription, self.speaker, self.role, self.question]
        present = [value for value in values if value > 0]
        if not present:
            return 0.0
        return min(present)


@dataclass(slots=True)
class ConversationTurn:
    speaker_id: str
    role: SpeakerRole
    text: str
    start: float
    end: float
    confidence: ConfidenceBundle
    source: AudioSourceKind = AudioSourceKind.UNKNOWN
    is_final: bool = True


@dataclass(frozen=True, slots=True)
class QuestionDetectionResult:
    is_question: bool
    confidence: float
    question_type: str
    text: str


@dataclass(frozen=True, slots=True)
class InterviewQuestion:
    session_id: str
    question_id: str
    question: str
    speaker: SpeakerRole
    confidence: float
    question_type: str
    recent_context: tuple[ConversationTurn, ...]
    created_at_ns: int = field(default_factory=monotonic_ns)

    def to_llm_input(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "question_id": self.question_id,
            "question": self.question,
            "speaker": self.speaker.value,
            "confidence": self.confidence,
            "question_type": self.question_type,
            "recent_context": [
                {"speaker": turn.role.value, "text": turn.text}
                for turn in self.recent_context
            ],
        }


@dataclass(slots=True)
class ConversationState:
    session_id: str = field(default_factory=lambda: f"session-{uuid4().hex}")
    speakers: dict[str, SpeakerState] = field(default_factory=dict)
    turns: list[ConversationTurn] = field(default_factory=list)
    current_question: InterviewQuestion | None = None
    last_processed_timestamp: float = 0.0

