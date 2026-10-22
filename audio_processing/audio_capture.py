"""Capture interviewer audio via system loopback (WASAPI) or microphone."""

from __future__ import annotations

import os
import queue
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np
import sounddevice as sd

import config

SAMPLE_RATE = 16000
# Small frames improve capture and VAD responsiveness without excessive callback overhead.
FRAME_MS = max(10, int(os.getenv("AUDIO_FRAME_MS", "20")))
FRAME_SAMPLES = int(SAMPLE_RATE * FRAME_MS / 1000)


def _resample_linear(samples: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
    """Low-overhead resampling helper for small audio capture blocks."""
    if source_rate == target_rate or samples.size == 0:
        return np.asarray(samples, dtype=np.float32)
    output_size = max(1, round(samples.size * target_rate / source_rate))
    source_x = np.arange(samples.size, dtype=np.float32)
    target_x = np.linspace(0, samples.size - 1, output_size, dtype=np.float32)
    return np.interp(target_x, source_x, samples).astype(np.float32, copy=False)


@dataclass
class AudioChunk:
    samples: np.ndarray
    sample_rate: int
    emitted_at: float = 0.0
    speech_end_at: float = 0.0
    utterance_id: str = ""
    is_partial: bool = False


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
    def _cb(indata, _frames, _time, _status):
        return None

    try:
        kwargs = dict(samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                      blocksize=FRAME_SAMPLES, callback=_cb)
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
    """Prefer WDM-KS PC Speaker, then loopback and Stereo Mix inputs."""
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
        self.native_blocksize = max(1, round(self.target_blocksize * self.native_rate / self.target_rate))

        def py_callback(in_data, frame_count, time_info, status):
            try:
                samples = np.frombuffer(in_data, dtype=np.float32)
                if self.channels > 1:
                    samples = samples.reshape(-1, self.channels)[:, 0]
                standardized = _resample_linear(samples, self.native_rate, self.target_rate)
                self.callback(standardized.reshape(-1, 1), standardized.size, None, status)
            except Exception as exc:
                # Keep the real-time callback non-blocking; make problems visible for debugging.
                print(f"[audio] loopback callback error: {exc}", flush=True)
            return (None, pyaudio.paContinue)

        self.stream = self.p.open(
            format=pyaudio.paFloat32,
            channels=self.channels,
            rate=self.native_rate,
            input=True,
            input_device_index=self.device_index,
            frames_per_buffer=self.native_blocksize,
            stream_callback=py_callback,
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
            default_speakers = p.get_device_info_by_index(wasapi["defaultOutputDevice"])
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


def resolve_input_device(source: Optional[str] = None) -> tuple[Optional[int], bool, str]:
    """Resolve an explicit source; system audio never silently becomes a mic."""
    source = (source or config.AUDIO_SOURCE or "loopback").strip().lower()
    source = "microphone" if source in ("microphone", "mic", "candidate") else "system"
    if source == "microphone":
        if _probe_input_device(None):
            return None, False, _device_name(None)
        raise RuntimeError("Cannot open microphone. Check Windows Sound settings and try again.")
    loopback = _find_loopback_device()
    if loopback is not None:
        return loopback, True, _device_name(loopback)
    raise RuntimeError(
        "System audio capture is unavailable. Enable Windows WASAPI loopback, "
        "a PC Speaker input, or Stereo Mix. The interviewer stream will not "
        "fall back to your microphone."
    )


def partial_indicates_unfinished(text: str) -> bool:
    """Detect partial transcripts that strongly suggest a clause is still in progress."""
    value = " ".join((text or "").lower().split()).strip(" .,!?:;")
    if not value:
        return False
    endings = (
        "and", "or", "but", "because", "when", "while", "whereas", "which",
        "that", "including", "with", "to", "for", "of", "in", "on", "from",
        "such as", "how to", "what is the", "difference between",
    )
    return any(value == ending or value.endswith(" " + ending) for ending in endings)


def adaptive_end_silence_ms(speech_duration_ms: int, unfinished: bool = False) -> int:
    """Use a longer endpoint window only when the live partial sounds unfinished."""
    base_ms = max(400, int(os.getenv("AUDIO_END_SILENCE_MS", "900")))
    long_ms = max(base_ms, int(os.getenv("AUDIO_LONG_UTTERANCE_SILENCE_MS", "3000")))
    if unfinished:
        return long_ms
    if speech_duration_ms >= 8000:
        return long_ms
    if speech_duration_ms >= 3000:
        fraction = (speech_duration_ms - 3000) / 5000
        return round(base_ms + (long_ms - base_ms) * fraction)
    return base_ms


class EnergyVAD:
    """Simple energy-based voice activity detection (no native dependencies)."""
    def __init__(self, threshold: float = 0.012, *, loopback: bool = False):
        self.threshold = 0.006 if loopback else threshold
        self._noise_floor = 0.001

    def is_speech(self, frame: np.ndarray) -> bool:
        energy = float(np.sqrt(np.mean(frame.astype(np.float32) ** 2)))
        self._noise_floor = min(self._noise_floor * 0.995 + energy * 0.005, 0.05)
        return energy > max(self.threshold, self._noise_floor * 3.0)


class SpeechRecorder:
    """VAD recorder with fast snapshots and optional per-frame streaming audio."""
    def __init__(self, on_chunk: Callable[[AudioChunk], None],
                 on_status: Optional[Callable[[str], None]] = None,
                 source: Optional[str] = None,
                 on_partial: Optional[Callable[[AudioChunk], None]] = None,
                 on_frame: Optional[Callable[[np.ndarray], None]] = None,
                 stream_only: bool = False):
        self.on_chunk = on_chunk
        self.on_partial = on_partial or (lambda _: None)
        self.on_frame = on_frame
        self.stream_only = stream_only
        self.source = source or config.AUDIO_SOURCE
        self.on_status = on_status or (lambda _: None)
        self._queue: queue.Queue = queue.Queue(maxsize=500)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._stream: Optional[sd.InputStream] = None
        self._device: Optional[int] = None
        self._loopback = False
        self._device_label = ""
        self._vad = EnergyVAD(loopback=False)
        self._partial_transcripts: dict[str, str] = {}
        self._partial_transcripts_lock = threading.Lock()

    def update_partial_transcript(self, utterance_id: str, text: str) -> None:
        if not utterance_id or not text:
            return
        with self._partial_transcripts_lock:
            self._partial_transcripts[utterance_id] = text

    def _unfinished_partial(self, utterance_id: str) -> bool:
        with self._partial_transcripts_lock:
            text = self._partial_transcripts.get(utterance_id, "")
        return partial_indicates_unfinished(text)

    def start(self) -> None:
        self._device, self._loopback, self._device_label = resolve_input_device(self.source)
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

        kwargs = dict(samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                      blocksize=FRAME_SAMPLES, latency="low", callback=callback)
        if self._device is not None:
            kwargs["device"] = self._device
        if self._loopback:
            self._stream = WasapiLoopbackStream(self._device, SAMPLE_RATE, FRAME_SAMPLES, callback)
            self._stream.start()
        else:
            self._stream = sd.InputStream(**kwargs)
            self._stream.start()
        self._stop.clear()
        self._thread = threading.Thread(target=self._process_loop, daemon=True, name="speech-recorder-vad")
        self._thread.start()
        src = f"system audio ({self._device_label})" if self._loopback else f"microphone ({self._device_label})"
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
            self._thread.join(timeout=5.0)

    def _process_loop(self) -> None:
        buffer: list[np.ndarray] = []
        speech_frames = silence_frames = 0
        in_speech = False
        min_speech_frames = max(1, int(250 / FRAME_MS))
        utterance_counter = 0
        utterance_id = ""
        last_partial_at = 0.0
        partial_interval_sec = max(0.15, float(os.getenv("AUDIO_PARTIAL_INTERVAL_MS", "300")) / 1000)
        partial_min_frames = max(min_speech_frames, int(300 / FRAME_MS))
        end_silence_frames = max(1, int(adaptive_end_silence_ms(0) / FRAME_MS))
        max_frames = int(120000 / FRAME_MS)
        idle_frames = 0
        last_speech_at = 0.0

        while not self._stop.is_set():
            try:
                frame = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            if len(frame) < FRAME_SAMPLES:
                continue
            frame = frame[:FRAME_SAMPLES]
            if self.on_frame:
                try:
                    self.on_frame(frame)
                except Exception as exc:
                    self.on_status(f"Streaming audio frame failed: {exc}")
            if self.stream_only:
                continue
            is_speech = self._vad.is_speech(frame)

            if is_speech:
                now = time.perf_counter()
                if not in_speech:
                    utterance_counter += 1
                    utterance_id = f"{id(self)}-{utterance_counter}"
                    last_partial_at = 0.0
                last_speech_at = now
                buffer.append(frame)
                speech_frames += 1
                silence_frames = 0
                end_silence_frames = max(1, int(adaptive_end_silence_ms(speech_frames * FRAME_MS) / FRAME_MS))
                in_speech = True
                idle_frames = 0
                if speech_frames >= partial_min_frames and now - last_partial_at >= partial_interval_sec:
                    self._emit(buffer, utterance_id=utterance_id, partial=True)
                    last_partial_at = now
                if speech_frames >= max_frames:
                    self.on_status("Long interviewer utterance reached 120-second safety limit")
                    self._emit(buffer, speech_end_at=last_speech_at, utterance_id=utterance_id)
                    buffer = []
                    speech_frames = silence_frames = 0
                    in_speech = False
                    utterance_id = ""
                    last_partial_at = 0.0
            elif in_speech:
                buffer.append(frame)
                silence_frames += 1
                # Partial STT can arrive while silence is accumulating. Re-evaluate the
                # endpoint every frame so an unfinished clause gets a longer grace window.
                end_silence_frames = max(
                    end_silence_frames,
                    int(adaptive_end_silence_ms(
                        speech_frames * FRAME_MS,
                        unfinished=self._unfinished_partial(utterance_id),
                    ) / FRAME_MS),
                )
                if silence_frames >= end_silence_frames and speech_frames >= min_speech_frames:
                    self._emit(buffer, speech_end_at=last_speech_at, utterance_id=utterance_id)
                    buffer = []
                    speech_frames = silence_frames = 0
                    in_speech = False
                    utterance_id = ""
                    last_partial_at = 0.0
            else:
                idle_frames += 1
                if idle_frames == int(15000 / FRAME_MS):
                    speaker = "interviewer" if self._loopback else "candidate"
                    hint = " (check Meet volume and loopback output)" if self._loopback else ""
                    self.on_status(f"Listening — waiting for {speaker} speech{hint}")
                    idle_frames = 0

    def _emit(self, buffer: list[np.ndarray], speech_end_at: float = 0.0, *,
              utterance_id: str = "", partial: bool = False) -> None:
        if not buffer:
            return
        samples = np.concatenate(buffer)
        if len(samples) < SAMPLE_RATE * 0.35:
            return
        emitted_at = time.perf_counter()
        chunk = AudioChunk(samples=samples, sample_rate=SAMPLE_RATE, emitted_at=emitted_at,
                           speech_end_at=speech_end_at or (0.0 if partial else emitted_at),
                           utterance_id=utterance_id, is_partial=partial)
        (self.on_partial if partial else self.on_chunk)(chunk)
