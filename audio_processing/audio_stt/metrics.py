"""Thread-safe operational metrics."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from threading import Lock
from time import monotonic


@dataclass(slots=True)
class MetricsSnapshot:
    uptime_seconds: float = 0
    captured_frames: int = 0
    dropped_frames: int = 0
    processed_frames: int = 0
    speech_frames: int = 0
    utterances: int = 0
    partial_transcripts: int = 0
    final_transcripts: int = 0
    errors: int = 0
    queue_depth: int = 0
    max_queue_depth: int = 0
    last_stt_latency_ms: float = 0


class PipelineMetrics:
    def __init__(self):
        self._values = MetricsSnapshot()
        self._started = monotonic()
        self._lock = Lock()

    def increment(self, field: str, amount: int = 1) -> None:
        with self._lock:
            setattr(self._values, field, getattr(self._values, field) + amount)

    def observe_queue(self, depth: int) -> None:
        with self._lock:
            self._values.queue_depth = depth
            self._values.max_queue_depth = max(self._values.max_queue_depth, depth)

    def observe_latency(self, latency_ms: float) -> None:
        with self._lock:
            self._values.last_stt_latency_ms = latency_ms

    def snapshot(self) -> dict[str, int | float]:
        with self._lock:
            values = asdict(self._values)
        values["uptime_seconds"] = monotonic() - self._started
        return values
