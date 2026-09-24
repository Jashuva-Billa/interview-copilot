"""Audio source wrappers and metadata helpers."""

from __future__ import annotations

from dataclasses import dataclass
from time import monotonic_ns
from typing import Iterable
from uuid import uuid4

from .contracts import AudioCallback, AudioSource, ErrorCallback
from .models import AudioSourceKind, SourceMetadata


def source_metadata(
    source: AudioSourceKind,
    start_seconds: float,
    end_seconds: float,
    chunk_id: str | None = None,
) -> SourceMetadata:
    return SourceMetadata(
        source=source,
        audio_chunk_id=chunk_id or uuid4().hex,
        timestamp_start=start_seconds,
        timestamp_end=end_seconds,
    )


@dataclass(slots=True)
class TaggedAudioSource:
    """Decorates any AudioSource with a stable semantic source label."""

    source: AudioSource
    kind: AudioSourceKind

    def start(self, on_audio: AudioCallback, on_error: ErrorCallback) -> None:
        self.source.start(on_audio, on_error)

    def stop(self) -> None:
        self.source.stop()

    def current_device(self) -> str:
        return self.source.current_device()


class SystemAudioSource(TaggedAudioSource):
    def __init__(self, source: AudioSource):
        super().__init__(source, AudioSourceKind.SYSTEM)


class MicrophoneAudioSource(TaggedAudioSource):
    def __init__(self, source: AudioSource):
        super().__init__(source, AudioSourceKind.MICROPHONE)


class CombinedAudioSource:
    """Fan-in abstraction for future mixed-stream capture implementations."""

    kind = AudioSourceKind.COMBINED

    def __init__(self, sources: Iterable[AudioSource]):
        self._sources = tuple(sources)

    def start(self, on_audio: AudioCallback, on_error: ErrorCallback) -> None:
        for source in self._sources:
            source.start(on_audio, on_error)

    def stop(self) -> None:
        for source in self._sources:
            source.stop()

    def current_device(self) -> str:
        labels = [source.current_device() for source in self._sources]
        return " + ".join(label for label in labels if label)


def timestamp_ns_to_seconds(value: int | None) -> float:
    if not value:
        return monotonic_ns() / 1_000_000_000
    return value / 1_000_000_000

