"""Audio-to-text orchestration with no interview or LLM reasoning."""

from __future__ import annotations

import logging
import queue
import threading
from collections import deque
from time import monotonic, monotonic_ns
from typing import Callable
from uuid import uuid4

import numpy as np

from .buffer import AudioRingBuffer
from .capture import RobustMicrophoneSource
from .config import AudioSTTConfig
from .contracts import AudioEnhancer, AudioSource, StreamingSTTProvider, VoiceActivityDetector
from .dsp import create_enhancer, float_to_pcm16
from .events import AudioEvent, EventKind, Transcript
from .metrics import PipelineMetrics
from .stt import create_stt_provider
from .vad import create_vad

log = logging.getLogger(__name__)
EventCallback = Callable[[AudioEvent], None]


class AudioToTextPipeline:
    """Transforms microphone audio into partial/final transcript events."""

    def __init__(
        self,
        config: AudioSTTConfig | None = None,
        *,
        source: AudioSource | None = None,
        enhancer: AudioEnhancer | None = None,
        vad: VoiceActivityDetector | None = None,
        stt: StreamingSTTProvider | None = None,
    ):
        self.config = config or AudioSTTConfig()
        self._source = source or RobustMicrophoneSource(self.config)
        self._enhancer = enhancer or create_enhancer(self.config)
        self._vad = vad or create_vad(self.config)
        self._stt = stt or create_stt_provider(self.config)

        self._callbacks: list[EventCallback] = []
        self._callback_lock = threading.Lock()
        self._audio_queue: queue.Queue[tuple[np.ndarray, int]] = queue.Queue(
            maxsize=self.config.queue_capacity
        )
        self._event_queue: queue.Queue[AudioEvent | None] = queue.Queue(maxsize=512)
        self._far_end: deque[np.ndarray] = deque(maxlen=self.config.queue_capacity)
        self._far_lock = threading.Lock()
        self._ring = AudioRingBuffer(
            round(self.config.ring_buffer_seconds * self.config.sample_rate)
        )
        self._metrics = PipelineMetrics()
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None
        self._dispatcher: threading.Thread | None = None
        self._running = False

    def subscribe(self, callback: EventCallback) -> Callable[[], None]:
        with self._callback_lock:
            self._callbacks.append(callback)

        def unsubscribe() -> None:
            with self._callback_lock:
                if callback in self._callbacks:
                    self._callbacks.remove(callback)

        return unsubscribe

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._stop.clear()
        self._dispatcher = threading.Thread(
            target=self._dispatch_loop,
            name="audio-event-dispatcher",
            daemon=True,
        )
        self._worker = threading.Thread(
            target=self._process_loop,
            name="audio-processing",
            daemon=True,
        )
        self._dispatcher.start()
        try:
            self._stt.start(self._on_transcript)
            self._worker.start()
            self._source.start(self._on_audio, self._on_capture_error)
        except Exception:
            self.stop()
            raise
        self._emit(
            AudioEvent(
                EventKind.STARTED,
                message="Audio-to-text pipeline started",
                data={"device": self._source.current_device()},
            )
        )

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        self._stop.set()
        self._source.stop()
        if (
            self._worker
            and self._worker is not threading.current_thread()
            and self._worker.is_alive()
        ):
            self._worker.join(timeout=3.0)
        self._stt.stop()
        self._enhancer.reset()
        self._vad.reset()
        self._ring.clear()
        self._emit(AudioEvent(EventKind.STOPPED, message="Audio-to-text pipeline stopped"))
        try:
            self._event_queue.put(None, timeout=0.2)
        except queue.Full:
            pass
        if (
            self._dispatcher
            and self._dispatcher is not threading.current_thread()
            and self._dispatcher.is_alive()
        ):
            self._dispatcher.join(timeout=2.0)
        self._worker = self._dispatcher = None

    def push_far_end(self, samples: np.ndarray, sample_rate: int = 16_000) -> None:
        """Provide synchronized speaker/render audio used as the AEC reference."""
        value = np.asarray(samples, dtype=np.float32).reshape(-1)
        if sample_rate != self.config.sample_rate:
            output_size = max(1, round(value.size * self.config.sample_rate / sample_rate))
            value = np.interp(
                np.linspace(0, value.size - 1, output_size),
                np.arange(value.size),
                value,
            ).astype(np.float32)
        with self._far_lock:
            self._far_end.append(value.copy())

    def metrics(self) -> dict[str, int | float]:
        return self._metrics.snapshot()

    def _on_audio(self, frame: np.ndarray, sample_rate: int, timestamp_ns: int) -> None:
        if self._stop.is_set():
            return
        if sample_rate != self.config.sample_rate:
            self._on_capture_error(ValueError(f"Unexpected sample rate: {sample_rate}"))
            return
        self._metrics.increment("captured_frames")
        try:
            self._audio_queue.put_nowait((frame, timestamp_ns))
            self._metrics.observe_queue(self._audio_queue.qsize())
        except queue.Full:
            self._metrics.increment("dropped_frames")

    def _on_capture_error(self, exc: Exception) -> None:
        self._metrics.increment("errors")
        self._emit(
            AudioEvent(
                EventKind.ERROR,
                message=f"Microphone error; automatic recovery active: {exc}",
                data={"recoverable": True, "component": "capture"},
            )
        )

    def _on_transcript(self, transcript: Transcript) -> None:
        field = "final_transcripts" if transcript.is_final else "partial_transcripts"
        self._metrics.increment(field)
        if transcript.latency_ms is not None:
            self._metrics.observe_latency(transcript.latency_ms)
        self._emit(
            AudioEvent(
                EventKind.FINAL_TRANSCRIPT
                if transcript.is_final
                else EventKind.PARTIAL_TRANSCRIPT,
                transcript=transcript,
            )
        )

    def _take_far_end(self) -> np.ndarray | None:
        with self._far_lock:
            return self._far_end.popleft() if self._far_end else None

    def _process_loop(self) -> None:
        speech_run = silence_run = utterance_frames = 0
        active = False
        utterance_id = ""
        last_device = ""
        last_metrics = monotonic()
        min_speech_frames = max(1, round(self.config.min_speech_ms / self.config.frame_ms))
        end_silence_frames = max(
            1, round(self.config.end_silence_ms / self.config.frame_ms)
        )
        max_frames = max(
            1,
            round(self.config.max_utterance_seconds * 1000 / self.config.frame_ms),
        )
        pre_speech_samples = round(
            self.config.pre_speech_ms * self.config.sample_rate / 1000
        )
        is_speech_to_text = getattr(self._stt, "name", "").lower() in ("speech_to_text", "dhwani")

        while not self._stop.is_set():
            try:
                frame, timestamp_ns = self._audio_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                enhanced = self._enhancer.process(frame, self._take_far_end())
                self._ring.append(enhanced)

                device = self._source.current_device()
                if device and device != last_device:
                    last_device = device
                    self._emit(
                        AudioEvent(
                            EventKind.DEVICE_CHANGED,
                            message=f"Using microphone: {device}",
                            data={"device": device},
                        )
                    )

                if is_speech_to_text:
                    if not active:
                        active = True
                        utterance_id = "continuous-speech-to-text"
                        self._stt.begin_utterance(utterance_id, timestamp_ns)
                    self._stt.push_audio(float_to_pcm16(enhanced), timestamp_ns)
                    continue

                probability = self._vad.probability(enhanced)
                is_speech = probability >= self.config.vad_threshold
                self._metrics.increment("processed_frames")

                if not active:
                    speech_run = speech_run + 1 if is_speech else 0
                    if speech_run >= min_speech_frames:
                        active = True
                        silence_run = 0
                        utterance_frames = speech_run
                        utterance_id = uuid4().hex
                        started_at_ns = timestamp_ns - (
                            speech_run * self.config.frame_ms * 1_000_000
                        )
                        self._stt.begin_utterance(utterance_id, started_at_ns)
                        preroll = self._ring.tail(pre_speech_samples)
                        self._stt.push_audio(float_to_pcm16(preroll), timestamp_ns)
                        self._metrics.increment("utterances")
                        self._emit(
                            AudioEvent(
                                EventKind.SPEECH_STARTED,
                                data={
                                    "utterance_id": utterance_id,
                                    "vad_probability": probability,
                                },
                            )
                        )
                    continue

                utterance_frames += 1
                self._metrics.increment("speech_frames")
                self._stt.push_audio(float_to_pcm16(enhanced), timestamp_ns)
                silence_run = 0 if is_speech else silence_run + 1
                if silence_run >= end_silence_frames or utterance_frames >= max_frames:
                    self._stt.end_utterance(timestamp_ns)
                    self._emit(
                        AudioEvent(
                            EventKind.SPEECH_ENDED,
                            data={"utterance_id": utterance_id},
                        )
                    )
                    active = False
                    speech_run = silence_run = utterance_frames = 0
                    utterance_id = ""
                    self._vad.reset()

                now = monotonic()
                if now - last_metrics >= 5.0:
                    last_metrics = now
                    self._emit(
                        AudioEvent(EventKind.METRICS, data=self._metrics.snapshot())
                    )
            except Exception as exc:
                self._metrics.increment("errors")
                log.exception("Audio processing frame failed")
                self._emit(
                    AudioEvent(
                        EventKind.ERROR,
                        message=str(exc),
                        data={"recoverable": True, "component": "processing"},
                    )
                )

        if active:
            self._stt.end_utterance(monotonic_ns())

    def _emit(self, event: AudioEvent) -> None:
        try:
            self._event_queue.put_nowait(event)
        except queue.Full:
            if event.kind in (EventKind.ERROR, EventKind.FINAL_TRANSCRIPT):
                log.error("Critical audio event queue overflow: %s", event.kind)

    def _dispatch_loop(self) -> None:
        while True:
            try:
                event = self._event_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            if event is None:
                break
            with self._callback_lock:
                callbacks = tuple(self._callbacks)
            for callback in callbacks:
                try:
                    callback(event)
                except Exception:
                    log.exception("Audio event subscriber failed")
