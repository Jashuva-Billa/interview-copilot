"""Replaceable component contracts."""

from __future__ import annotations

from typing import Callable, Protocol

import numpy as np

from .events import Transcript

AudioCallback = Callable[[np.ndarray, int, int], None]
ErrorCallback = Callable[[Exception], None]


class AudioSource(Protocol):
    def start(self, on_audio: AudioCallback, on_error: ErrorCallback) -> None: ...
    def stop(self) -> None: ...
    def current_device(self) -> str: ...


class AudioEnhancer(Protocol):
    def process(
        self,
        near_end: np.ndarray,
        far_end: np.ndarray | None = None,
    ) -> np.ndarray: ...

    def reset(self) -> None: ...


class VoiceActivityDetector(Protocol):
    def probability(self, frame: np.ndarray) -> float: ...
    def reset(self) -> None: ...


class StreamingSTTProvider(Protocol):
    name: str

    def start(self, on_transcript: Callable[[Transcript], None]) -> None: ...
    def begin_utterance(self, utterance_id: str, started_at_ns: int) -> None: ...
    def push_audio(self, pcm16: bytes, timestamp_ns: int) -> None: ...
    def end_utterance(self, ended_at_ns: int) -> None: ...
    def stop(self) -> None: ...
