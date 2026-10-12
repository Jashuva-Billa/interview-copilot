"""Low-cost DSP and an optional WebRTC Audio Processing adapter."""

from __future__ import annotations

import logging
from math import exp, pi

import numpy as np

from .config import AudioSTTConfig

log = logging.getLogger(__name__)


def float_to_pcm16(samples: np.ndarray) -> bytes:
    clipped = np.clip(samples, -1.0, 1.0)
    return (clipped * 32767.0).astype("<i2", copy=False).tobytes()


class BasicAudioEnhancer:
    """Stateful HPF, gain control, and peak protection.

    This is the safe fallback when a native WebRTC APM binding is unavailable.
    It intentionally does not claim to provide AEC or neural noise suppression.
    """

    def __init__(self, config: AudioSTTConfig):
        self._config = config
        self._x1 = 0.0
        self._y1 = 0.0
        self._gain = 1.0
        self._alpha = exp(-2.0 * pi * 80.0 / config.sample_rate)

    def reset(self) -> None:
        self._x1 = self._y1 = 0.0
        self._gain = 1.0

    def process(
        self,
        near_end: np.ndarray,
        far_end: np.ndarray | None = None,
    ) -> np.ndarray:
        del far_end
        output = np.asarray(near_end, dtype=np.float32).reshape(-1).copy()
        if self._config.enable_high_pass:
            x1, y1, alpha = self._x1, self._y1, self._alpha
            for index, sample in enumerate(output):
                value = alpha * (y1 + float(sample) - x1)
                output[index] = value
                x1, y1 = float(sample), value
            self._x1, self._y1 = x1, y1

        if self._config.enable_agc:
            rms = float(np.sqrt(np.mean(output * output) + 1e-9))
            target_gain = min(8.0, max(0.25, 0.10 / max(rms, 1e-4)))
            self._gain = 0.92 * self._gain + 0.08 * target_gain
            output *= self._gain

        if self._config.enable_normalization:
            peak = float(np.max(np.abs(output), initial=0.0))
            if peak > 0.95:
                output *= 0.95 / peak
        return np.clip(output, -1.0, 1.0)


class WebRTCAudioEnhancer:
    """Adapter for the optional ``webrtc_audio_processing`` native package."""

    def __init__(self, config: AudioSTTConfig):
        try:
            from webrtc_audio_processing import AudioProcessingModule
        except ImportError as exc:
            raise RuntimeError("WebRTC Audio Processing is not installed") from exc

        self._config = config
        self._apm = AudioProcessingModule(
            enable_aec=config.enable_aec,
            enable_ns=config.enable_ns,
            enable_agc=config.enable_agc,
        )
        self._apm.set_stream_format(config.sample_rate, 1)
        self._apm.set_reverse_stream_format(config.sample_rate, 1)

    def reset(self) -> None:
        # Native APM wrappers generally reset state by reconstruction.
        self.__init__(self._config)

    def process(
        self,
        near_end: np.ndarray,
        far_end: np.ndarray | None = None,
    ) -> np.ndarray:
        if far_end is not None and far_end.size:
            self._apm.process_reverse_stream(float_to_pcm16(far_end))
        result = self._apm.process_stream(float_to_pcm16(near_end))
        return np.frombuffer(result, dtype="<i2").astype(np.float32) / 32768.0


def create_enhancer(config: AudioSTTConfig) -> BasicAudioEnhancer | WebRTCAudioEnhancer:
    if config.enable_aec or config.enable_ns:
        try:
            return WebRTCAudioEnhancer(config)
        except Exception:
            if not config.allow_component_fallback:
                raise
            log.info(
                "Native WebRTC APM unavailable; using HPF/AGC fallback without AEC/NS",
            )
    return BasicAudioEnhancer(config)
