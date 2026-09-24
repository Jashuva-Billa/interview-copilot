"""Capture interviewer audio via system loopback (WASAPI) or microphone."""

from __future__ import annotations

import queue
import threading
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np
import sounddevice as sd

import config

SAMPLE_RATE = 16000
FRAME_MS = 30
FRAME_SAMPLES = int(SAMPLE_RATE * FRAME_MS / 1000)


@dataclass
class AudioChunk:
    samples: np.ndarray
    sample_rate: int


def list_audio_devices() -> None:
    print(sd.query_devices())


def _device_name(device_id: Optional[int]) -> str:
    if device_id is None:
        return "default microphone"
    try:
        import pyaudiowpatch as pyaudio
        p = pyaudio.PyAudio()
        try:
            return p.get_device_info_by_index(device_id).get("name", f"device {device_id}")
        finally:
            p.terminate()
    except Exception:
        return sd.query_devices(device_id).get("name", f"device {device_id}")


def _probe_input_device(device_id: Optional[int]) -> bool:
    """Return True if we can open a short-lived input stream."""
    frames: list[np.ndarray] = []

    def _cb(indata, _frames, _time, _status):
        mono = indata[:, 0] if indata.ndim > 1 else indata.flatten()
        frames.append(mono.copy())

    try:
        kwargs = dict(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="float32",
            blocksize=FRAME_SAMPLES,
            callback=_cb,
        )
        if device_id is not None:
            kwargs["device"] = device_id
        stream = sd.InputStream(**kwargs)
        stream.start()
        stream.stop()
        stream.close()
        return True
    except Exception:
        return False


def _windows_loopback_candidates() -> list[int]:
    """
    Prefer WDM-KS 'PC Speaker' — captures Meet/Zoom audio from speakers.
    Stereo Mix is often disabled or broken on Windows 11.
    """
    devices = sd.query_devices()
    ranked: list[tuple[int, int]] = []

    for i, dev in enumerate(devices):
        if dev.get("max_input_channels", 0) < 1:
            continue
        name = dev.get("name", "").lower()
        if "pc speaker" in name:
            ranked.append((0, i))
        elif "loopback" in name:
            ranked.append((1, i))
        elif "stereo mix" in name:
            ranked.append((2, i))

    ranked.sort(key=lambda x: x[0])
    return [i for _, i in ranked]


class WasapiLoopbackStream:
    def __init__(self, device_index, target_rate, target_blocksize, callback):
        self.device_index = device_index
        self.target_rate = target_rate
        self.target_blocksize = target_blocksize
        self.callback = callback
        self.p = None
        self.stream = None

    def start(self):
        import pyaudiowpatch as pyaudio
        self.p = pyaudio.PyAudio()
        device_info = self.p.get_device_info_by_index(self.device_index)
        self.channels = device_info["maxInputChannels"]
        self.native_rate = int(device_info["defaultSampleRate"])
        self.native_blocksize = int(self.target_blocksize * self.native_rate / self.target_rate)

        def py_callback(in_data, frame_count, time_info, status):
            try:
                samples = np.frombuffer(in_data, dtype=np.float32)
                if self.channels > 1:
                    samples = samples.reshape(-1, self.channels)
                    samples = samples[:, 0]
                
                if self.native_rate == self.target_rate or samples.size == 0:
                    standardized = samples
                else:
                    output_size = max(1, round(samples.size * self.target_rate / self.native_rate))
                    source_x = np.arange(samples.size, dtype=np.float64)
                    target_x = np.linspace(0, samples.size - 1, output_size, dtype=np.float64)
                    standardized = np.interp(target_x, source_x, samples).astype(np.float32)

                standardized = standardized.reshape(-1, 1)
                self.callback(standardized, self.target_blocksize, None, None)
            except Exception:
                pass
            return (None, pyaudio.paContinue)

        self.stream = self.p.open(
            format=pyaudio.paFloat32,
            channels=self.channels,
            rate=self.native_rate,
            input=True,
            input_device_index=self.device_index,
            frames_per_buffer=self.native_blocksize,
            stream_callback=py_callback
        )
        self.stream.start_stream()

    def stop(self):
        if self.stream:
            try:
                self.stream.stop_stream()
                self.stream.close()
            except Exception:
                pass
            self.stream = None
        if self.p:
            try:
                self.p.terminate()
            except Exception:
                pass
            self.p = None

    def close(self):
        self.stop()

    def abort(self):
        self.stop()


def _find_loopback_device() -> Optional[int]:
    try:
        import pyaudiowpatch as pyaudio
        p = pyaudio.PyAudio()
        try:
            wasapi = p.get_host_api_info_by_type(pyaudio.paWASAPI)
            default_speakers = p.get_device_info_by_index(wasapi['defaultOutputDevice'])
            for dev in p.get_loopback_device_info_generator():
                if default_speakers["name"] in dev["name"]:
                    return dev["index"]
        finally:
            p.terminate()
    except Exception:
        pass

    for device_id in _windows_loopback_candidates():
        if _probe_input_device(device_id):
            return device_id
    return None


def resolve_input_device() -> tuple[Optional[int], bool, str]:
    """
    Returns (device_id, is_loopback, label for UI).
    is_loopback=False and device_id=None means default microphone.
    """
    if config.AUDIO_SOURCE == "microphone":
        if _probe_input_device(None):
            return None, False, _device_name(None)
        raise RuntimeError(
            "Cannot open microphone. Check Windows Sound settings and try again."
        )

    loopback = _find_loopback_device()
    if loopback is not None:
        return loopback, True, _device_name(loopback)

    # Loopback unavailable — fall back to mic so listening still works
    if _probe_input_device(None):
        print(
            "[audio] System audio capture unavailable. Using microphone — "
            "use speakers (not headphones) or set AUDIO_SOURCE=microphone in .env"
        )
        return None, False, _device_name(None)

    raise RuntimeError(
        "No working audio device. Enable Stereo Mix in Windows Sound settings, "
        "or set AUDIO_SOURCE=microphone in interview-copilot/.env"
    )


class EnergyVAD:
    """Simple energy-based voice activity detection (no native deps)."""

    def __init__(self, threshold: float = 0.012, *, loopback: bool = False):
        # Loopback (Meet from speakers) is often quieter than a mic
        self.threshold = 0.006 if loopback else threshold
        self._noise_floor = 0.001

    def is_speech(self, frame: np.ndarray) -> bool:
        energy = float(np.sqrt(np.mean(frame.astype(np.float64) ** 2)))
        self._noise_floor = min(self._noise_floor * 0.995 + energy * 0.005, 0.05)
        return energy > max(self.threshold, self._noise_floor * 3.0)


class SpeechRecorder:
    """VAD-based recorder: emits full utterance chunks when speech ends."""

    def __init__(
        self,
        on_chunk: Callable[[AudioChunk], None],
        on_status: Optional[Callable[[str], None]] = None,
    ):
        self.on_chunk = on_chunk
        self.on_status = on_status or (lambda _: None)
        # Bound callback buffering so a stalled processor cannot consume
        # unbounded memory. Dropping one frame is preferable to blocking the
        # real-time audio callback.
        self._queue: queue.Queue = queue.Queue(maxsize=500)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._stream: Optional[sd.InputStream] = None
        self._device: Optional[int] = None
        self._loopback = False
        self._device_label = ""
        self._vad = EnergyVAD(loopback=False)

    def start(self) -> None:
        self._device, self._loopback, self._device_label = resolve_input_device()
        self._vad = EnergyVAD(loopback=self._loopback)

        def callback(indata, _frames, _time, status):
            if status:
                self.on_status(f"Audio: {status}")
            mono = indata[:, 0] if indata.ndim > 1 else indata.flatten()
            try:
                self._queue.put_nowait(mono.copy())
            except queue.Full:
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    pass
                try:
                    self._queue.put_nowait(mono.copy())
                except queue.Full:
                    pass

        kwargs = dict(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="float32",
            blocksize=FRAME_SAMPLES,
            callback=callback,
        )
        if self._device is not None:
            kwargs["device"] = self._device
        # Do NOT pass WasapiSettings on WDM-KS / Stereo Mix — it breaks the stream.

        if self._loopback:
            self._stream = WasapiLoopbackStream(
                device_index=self._device,
                target_rate=SAMPLE_RATE,
                target_blocksize=FRAME_SAMPLES,
                callback=callback
            )
            self._stream.start()
        else:
            self._stream = sd.InputStream(**kwargs)
            self._stream.start()

        self._stop.clear()
        self._thread = threading.Thread(target=self._process_loop, daemon=True)
        self._thread.start()
        if self._loopback:
            src = f"system audio ({self._device_label})"
        else:
            src = f"microphone ({self._device_label})"
        self.on_status(f"Listening — {src}")

    def stop(self) -> None:
        self._stop.set()
        if self._stream:
            try:
                self._stream.stop()
            except Exception:
                pass
            try:
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        if self._thread:
            self._thread.join(timeout=20)

    def _process_loop(self) -> None:
        buffer: list[np.ndarray] = []
        speech_frames = 0
        silence_frames = 0
        in_speech = False
        min_speech_frames = int(350 / FRAME_MS)
        end_silence_frames = int(900 / FRAME_MS)
        max_frames = int(45000 / FRAME_MS)
        idle_frames = 0

        while not self._stop.is_set():
            try:
                frame = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue

            if len(frame) < FRAME_SAMPLES:
                continue
            frame = frame[:FRAME_SAMPLES]
            is_speech = self._vad.is_speech(frame)

            if is_speech:
                buffer.append(frame)
                speech_frames += 1
                silence_frames = 0
                in_speech = True
                idle_frames = 0
                if speech_frames >= max_frames:
                    self._emit(buffer)
                    buffer = []
                    speech_frames = 0
                    silence_frames = 0
                    in_speech = False
            elif in_speech:
                buffer.append(frame)
                silence_frames += 1
                if silence_frames >= end_silence_frames and speech_frames >= min_speech_frames:
                    self._emit(buffer)
                    buffer = []
                    speech_frames = 0
                    silence_frames = 0
                    in_speech = False
                elif speech_frames >= max_frames:
                    self._emit(buffer)
                    buffer = []
                    speech_frames = 0
                    silence_frames = 0
                    in_speech = False
            else:
                idle_frames += 1
                if idle_frames == int(15000 / FRAME_MS):
                    self.on_status(
                        "Listening — waiting for interviewer speech (use speakers, not only headphones)"
                    )
                    idle_frames = 0

    def _emit(self, buffer: list[np.ndarray]) -> None:
        if not buffer:
            return
        samples = np.concatenate(buffer)
        if len(samples) < SAMPLE_RATE * 0.6:
            return
        self.on_chunk(AudioChunk(samples=samples, sample_rate=SAMPLE_RATE))
