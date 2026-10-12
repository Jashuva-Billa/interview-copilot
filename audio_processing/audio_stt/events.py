"""Public events emitted by the audio-to-text pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from time import monotonic_ns
from typing import Any, Mapping


class EventKind(str, Enum):
    STARTED = "started"
    STOPPED = "stopped"
    DEVICE_CHANGED = "device_changed"
    SPEECH_STARTED = "speech_started"
    SPEECH_ENDED = "speech_ended"
    PARTIAL_TRANSCRIPT = "partial_transcript"
    FINAL_TRANSCRIPT = "final_transcript"
    WARNING = "warning"
    ERROR = "error"
    METRICS = "metrics"


@dataclass(frozen=True, slots=True)
class Transcript:
    text: str
    is_final: bool
    utterance_id: str
    started_at_ns: int
    ended_at_ns: int | None = None
    confidence: float | None = None
    language: str | None = None
    provider: str = ""
    latency_ms: float | None = None
    speaker_id: int | None = None
    role: str = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class AudioEvent:
    kind: EventKind
    transcript: Transcript | None = None
    message: str = ""
    data: Mapping[str, Any] = field(default_factory=dict)
    timestamp_ns: int = field(default_factory=monotonic_ns)
