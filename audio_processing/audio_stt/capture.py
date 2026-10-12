"""Cross-platform PortAudio microphone capture with device recovery."""

from __future__ import annotations

import logging
import sys
import threading
from time import monotonic_ns
from typing import Any

import numpy as np
import sounddevice as sd

from .config import AudioSTTConfig
from .contracts import AudioCallback, ErrorCallback

log = logging.getLogger(__name__)


class _FrameAssembler:
    def __init__(self, frame_samples: int):
        self._frame_samples = frame_samples
        self._buffer = np.empty(0, dtype=np.float32)

    def push(self, samples: np.ndarray) -> list[np.ndarray]:
        value = np.asarray(samples, dtype=np.float32).reshape(-1)
        self._buffer = np.concatenate((self._buffer, value))
        frames: list[np.ndarray] = []
        while self._buffer.size >= self._frame_samples:
            frames.append(self._buffer[: self._frame_samples].copy())
            self._buffer = self._buffer[self._frame_samples :]
        return frames


def _resample(samples: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
    if source_rate == target_rate or samples.size == 0:
        return np.asarray(samples, dtype=np.float32)
    output_size = max(1, round(samples.size * target_rate / source_rate))
    source_x = np.arange(samples.size, dtype=np.float64)
    target_x = np.linspace(0, samples.size - 1, output_size, dtype=np.float64)
    return np.interp(target_x, source_x, samples).astype(np.float32)


class RobustMicrophoneSource:
    """Automatically reopens the default/input device after failures or changes."""

    def __init__(self, config: AudioSTTConfig, device: int | str | None = None):
        self._config = config
        self._requested_device = device
        self._active_device: int | str | None = None
        self._device_label = ""
        self._stream: sd.InputStream | None = None
        self._stop = threading.Event()
        self._restart = threading.Event()
        self._supervisor: threading.Thread | None = None
        self._on_audio: AudioCallback | None = None
        self._on_error: ErrorCallback | None = None
        self._lock = threading.Lock()

    def current_device(self) -> str:
        return self._device_label

    def start(self, on_audio: AudioCallback, on_error: ErrorCallback) -> None:
        if self._supervisor and self._supervisor.is_alive():
            return
        self._on_audio = on_audio
        self._on_error = on_error
        self._stop.clear()
        self._restart.set()
        self._supervisor = threading.Thread(
            target=self._supervise,
            name="audio-device-supervisor",
            daemon=True,
        )
        self._supervisor.start()

    def stop(self) -> None:
        self._stop.set()
        self._restart.set()
        self._close_stream()
        if (
            self._supervisor
            and self._supervisor is not threading.current_thread()
            and self._supervisor.is_alive()
        ):
            self._supervisor.join(timeout=3.0)
        self._supervisor = None

    def _default_input_id(self) -> int | str | None:
        if self._requested_device is not None:
            return self._requested_device
        default = sd.default.device
        if hasattr(default, "input"):
            value: Any = getattr(default, "input")
        elif isinstance(default, (tuple, list)):
            value = default[0] if default else None
        else:
            value = default
        if value is None:
            return None
        if isinstance(value, str):
            return value.strip() or None
        try:
            device_id = int(value)
        except (TypeError, ValueError):
            return None
        return device_id if device_id >= 0 else None

    def _device_signature(self) -> tuple[int | str | None, str]:
        device_id = self._default_input_id()

        # Check if it's a loopback device before querying as standard input
        is_loopback = False
        if device_id is not None and not isinstance(device_id, str):
            try:
                import pyaudiowpatch as pyaudio
                p = pyaudio.PyAudio()
                try:
                    dev_info = p.get_device_info_by_index(device_id)
                    is_loopback = dev_info.get("isLoopbackDevice", False)
                    name = dev_info.get("name", str(device_id))
                finally:
                    p.terminate()
            except Exception:
                is_loopback = False

        if is_loopback:
            return device_id, name

        info = sd.query_devices(device_id, "input")
        return device_id, str(info.get("name", device_id))

    def _supervise(self) -> None:
        backoff = self._config.recovery_initial_seconds
        while not self._stop.is_set():
            try:
                device_id, label = self._device_signature()
                if self._stream is None or device_id != self._active_device:
                    self._open_stream(device_id, label)
                    backoff = self._config.recovery_initial_seconds

                self._restart.wait(self._config.device_poll_seconds)
                self._restart.clear()
                if self._stop.is_set():
                    break
                current_id, _ = self._device_signature()
                if current_id != self._active_device:
                    self._close_stream()
            except Exception as exc:
                self._close_stream()
                self._report_error(exc)
                self._stop.wait(backoff)
                backoff = min(backoff * 2.0, self._config.recovery_max_seconds)

    def _open_stream(self, device_id: int | str | None, label: str) -> None:
        is_loopback = False
        if device_id is not None and not isinstance(device_id, str):
            try:
                import pyaudiowpatch as pyaudio
                p = pyaudio.PyAudio()
                try:
                    dev_info = p.get_device_info_by_index(device_id)
                    is_loopback = dev_info.get("isLoopbackDevice", False)
                finally:
                    p.terminate()
            except Exception:
                is_loopback = False

        if is_loopback:
            from audio_processing.audio_capture import WasapiLoopbackStream
            assembler = _FrameAssembler(self._config.frame_samples)
            
            def callback(indata, _frames, time_info, status):
                mono = np.asarray(indata[:, 0], dtype=np.float32).copy()
                adc_ns = monotonic_ns()
                if self._on_audio:
                    for frame in assembler.push(mono):
                        self._on_audio(frame, self._config.sample_rate, adc_ns)

            stream = WasapiLoopbackStream(
                device_index=device_id,
                target_rate=self._config.sample_rate,
                target_blocksize=self._config.frame_samples,
                callback=callback
            )
            try:
                stream.start()
                with self._lock:
                    self._stream = stream
                    self._active_device = device_id
                    self._device_label = label
                log.info(
                    "WASAPI Loopback stream opened: %s (%s Hz)",
                    label,
                    self._config.sample_rate
                )
                return
            except Exception as exc:
                raise RuntimeError(f"Unable to open WASAPI Loopback stream {label}: {exc}")

        info = sd.query_devices(device_id, "input")
        native_rate = int(round(float(info["default_samplerate"])))
        rates = [self._config.sample_rate]
        if native_rate != self._config.sample_rate:
            rates.append(native_rate)

        last_error: Exception | None = None
        for capture_rate in rates:
            assembler = _FrameAssembler(self._config.frame_samples)

            def callback(indata, _frames, time_info, status, rate=capture_rate):
                if status:
                    log.warning("PortAudio status: %s", status)
                    if getattr(status, "input_overflow", False):
                        self._restart.set()
                mono = np.asarray(indata[:, 0], dtype=np.float32).copy()
                standardized = _resample(mono, rate, self._config.sample_rate)
                adc_ns = monotonic_ns()
                if time_info:
                    # PortAudio clocks are not guaranteed to share Python's
                    # monotonic epoch, so monotonic_ns remains the event clock.
                    adc_ns = monotonic_ns()
                if self._on_audio:
                    for frame in assembler.push(standardized):
                        self._on_audio(frame, self._config.sample_rate, adc_ns)

            try:
                stream = sd.InputStream(
                    device=device_id,
                    samplerate=capture_rate,
                    channels=1,
                    dtype="float32",
                    blocksize=max(1, round(capture_rate * self._config.frame_ms / 1000)),
                    latency="low",
                    callback=callback,
                )
                stream.start()
                with self._lock:
                    self._stream = stream
                    self._active_device = device_id
                    self._device_label = label
                log.info(
                    "Microphone opened: %s (%s Hz capture -> 16000 Hz mono)",
                    label,
                    capture_rate,
                )
                return
            except Exception as exc:
                last_error = exc

        raise RuntimeError(f"Unable to open microphone {label}: {last_error}")

    def _close_stream(self) -> None:
        with self._lock:
            stream, self._stream = self._stream, None
            self._active_device = None
        if stream is not None:
            try:
                stream.abort()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass

    def _report_error(self, exc: Exception) -> None:
        log.warning("Microphone capture failed; retrying: %s", exc)
        if self._on_error:
            self._on_error(exc)
