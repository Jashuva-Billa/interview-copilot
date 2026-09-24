"""Modular, event-driven audio-to-text pipeline."""

from .config import AudioSTTConfig
from .conversation import InterviewQuestionProcessor, QuestionDetector
from .events import AudioEvent, EventKind, Transcript
from .models import (
    AudioSourceKind,
    ConversationState,
    ConversationTurn,
    InterviewQuestion,
    SpeakerRole,
    TranscriptSegment,
)

__all__ = [
    "AudioEvent",
    "AudioSTTConfig",
    "AudioToTextPipeline",
    "AudioSourceKind",
    "ConversationState",
    "ConversationTurn",
    "EventKind",
    "InterviewQuestion",
    "InterviewQuestionProcessor",
    "QuestionDetector",
    "SpeakerRole",
    "Transcript",
    "TranscriptSegment",
]


def __getattr__(name: str):
    if name == "AudioToTextPipeline":
        from .pipeline import AudioToTextPipeline

        return AudioToTextPipeline
    raise AttributeError(name)
