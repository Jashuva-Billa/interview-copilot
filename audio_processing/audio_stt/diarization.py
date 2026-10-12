"""Replaceable speaker diarization providers."""

from __future__ import annotations

import logging
from typing import Protocol

import numpy as np

from .models import AudioSourceKind, SpeakerSegment, TranscriptSegment

log = logging.getLogger(__name__)


class SpeakerDiarizationProvider(Protocol):
    name: str

    def diarize(
        self,
        audio: np.ndarray | None,
        sample_rate: int,
        transcript: TranscriptSegment | None = None,
    ) -> tuple[SpeakerSegment, ...]: ...


class SourceMetadataDiarizationProvider:
    """Low-latency fallback that preserves diarization contract.

    It does not pretend to separate voices in mixed audio. For separate source
    mode it emits stable source-backed speaker IDs; for combined audio it emits
    an unknown speaker so role resolution can remain conservative.
    """

    name = "source_metadata"

    def diarize(
        self,
        audio: np.ndarray | None,
        sample_rate: int,
        transcript: TranscriptSegment | None = None,
    ) -> tuple[SpeakerSegment, ...]:
        del audio, sample_rate
        if transcript is None:
            return ()
        spk = getattr(transcript, "speaker_id", None)
        if spk is not None:
            speaker = str(spk)
            confidence = getattr(transcript, "confidence", 0.85) or 0.85
        else:
            source = transcript.source.source if transcript.source else AudioSourceKind.UNKNOWN
            if source == AudioSourceKind.SYSTEM:
                speaker = "SPEAKER_SYSTEM"
                confidence = 0.82
            elif source == AudioSourceKind.MICROPHONE:
                speaker = "SPEAKER_MICROPHONE"
                confidence = 0.82
            else:
                speaker = "SPEAKER_00"
                confidence = 0.35
        return (
            SpeakerSegment(
                speaker=speaker,
                start=transcript.start,
                end=transcript.end,
                confidence=confidence,
            ),
        )


class PyannoteDiarizationProvider:
    """Optional pyannote.audio adapter.

    Requires pyannote.audio and a local/authorized model setup. This class is
    intentionally isolated so business logic is not coupled to pyannote.
    """

    name = "pyannote"

    def __init__(self, model: str = "pyannote/speaker-diarization-3.1", token: str = ""):
        try:
            from pyannote.audio import Pipeline
        except ImportError as exc:
            raise RuntimeError("Install pyannote.audio to use diarization") from exc
        kwargs = {"use_auth_token": token} if token else {}
        self._pipeline = Pipeline.from_pretrained(model, **kwargs)

    def diarize(
        self,
        audio: np.ndarray | None,
        sample_rate: int,
        transcript: TranscriptSegment | None = None,
    ) -> tuple[SpeakerSegment, ...]:
        if audio is None or audio.size == 0:
            return ()
        diarization = self._pipeline({"waveform": audio.reshape(1, -1), "sample_rate": sample_rate})
        segments: list[SpeakerSegment] = []
        for turn, _, speaker in diarization.itertracks(yield_label=True):
            segments.append(
                SpeakerSegment(
                    speaker=str(speaker),
                    start=float(turn.start),
                    end=float(turn.end),
                    confidence=None,
                )
            )
        return tuple(segments)


def create_diarization_provider(
    provider: str = "source_metadata",
    *,
    model: str = "",
    token: str = "",
    allow_fallback: bool = True,
) -> SpeakerDiarizationProvider:
    if provider.lower() == "pyannote":
        try:
            return PyannoteDiarizationProvider(model or "pyannote/speaker-diarization-3.1", token)
        except Exception:
            if not allow_fallback:
                raise
            log.warning("pyannote diarization unavailable; using source metadata fallback")
    return SourceMetadataDiarizationProvider()

