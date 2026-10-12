"""Silero VAD adapter and a clearly identified emergency fallback."""

from __future__ import annotations

import logging

import numpy as np

from .config import AudioSTTConfig

log = logging.getLogger(__name__)


class EnergyFallbackVAD:
    def __init__(self):
        self._noise_floor = 0.001

    def probability(self, frame: np.ndarray) -> float:
        rms = float(np.sqrt(np.mean(np.asarray(frame, dtype=np.float64) ** 2)))
        self._noise_floor = min(0.95 * self._noise_floor + 0.05 * rms, 0.05)
        threshold = max(0.008, self._noise_floor * 2.8)
        return float(np.clip((rms - threshold) / max(threshold, 1e-5) + 0.5, 0, 1))

    def reset(self) -> None:
        self._noise_floor = 0.001


class SileroVAD:
    """Stateful Silero inference using the supported ``silero_vad`` package."""

    def __init__(self, config: AudioSTTConfig):
        if config.frame_samples != 512:
            raise ValueError("Silero at 16 kHz requires 512-sample (32 ms) frames")
        try:
            import torch
            from silero_vad import load_silero_vad
        except ImportError as exc:
            raise RuntimeError("Install silero-vad and torch for Silero VAD") from exc
        self._torch = torch
        self._model = load_silero_vad(onnx=True)

    def probability(self, frame: np.ndarray) -> float:
        tensor = self._torch.from_numpy(
            np.asarray(frame, dtype=np.float32).reshape(-1).copy()
        )
        with self._torch.inference_mode():
            value = self._model(tensor, 16_000)
        return float(value.item())

    def reset(self) -> None:
        reset = getattr(self._model, "reset_states", None)
        if reset:
            reset()


def create_vad(config: AudioSTTConfig) -> SileroVAD | EnergyFallbackVAD:
    try:
        return SileroVAD(config)
    except Exception:
        if not config.allow_component_fallback:
            raise
        log.warning("Silero VAD unavailable; using energy fallback")
        return EnergyFallbackVAD()
