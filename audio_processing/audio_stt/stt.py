"""Pluggable streaming STT providers."""

from __future__ import annotations

import logging
import queue
import threading
import asyncio
import json
import time
import io
import wave
from dataclasses import dataclass
from time import monotonic_ns
from typing import Callable
from uuid import uuid4

import numpy as np

from .config import AudioSTTConfig
from .events import Transcript
from .contracts import StreamingSTTProvider

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _InferenceJob:
    utterance_id: str
    started_at_ns: int
    ended_at_ns: int
    pcm16: bytes
    final: bool


class BufferedInferenceProvider:
    """Base class for models that expose fast utterance inference, not sessions.

    It provides streaming semantics by submitting throttled snapshots. Partial
    jobs are dropped under load; final jobs are never intentionally dropped.
    """

    name = "buffered"

    def __init__(self, config: AudioSTTConfig):
        self._config = config
        self._callback: Callable[[Transcript], None] | None = None
        self._jobs: queue.Queue[_InferenceJob | None] = queue.Queue(maxsize=4)
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._utterance_id = ""
        self._started_at_ns = 0
        self._audio = bytearray()
        self._last_partial_ns = 0
        self._last_partial_text: dict[str, str] = {}

    def start(self, on_transcript: Callable[[Transcript], None]) -> None:
        self._callback = on_transcript
        self._stop.clear()
        self._load()
        self._thread = threading.Thread(
            target=self._run,
            name=f"stt-{self.name}",
            daemon=True,
        )
        self._thread.start()

    def begin_utterance(self, utterance_id: str, started_at_ns: int) -> None:
        with self._lock:
            self._utterance_id = utterance_id
            self._started_at_ns = started_at_ns
            self._audio = bytearray()
            self._last_partial_ns = started_at_ns

    def push_audio(self, pcm16: bytes, timestamp_ns: int) -> None:
        with self._lock:
            if not self._utterance_id:
                return
            self._audio.extend(pcm16)
            interval_ns = self._config.partial_interval_ms * 1_000_000
            if timestamp_ns - self._last_partial_ns < interval_ns:
                return
            self._last_partial_ns = timestamp_ns
            job = _InferenceJob(
                self._utterance_id,
                self._started_at_ns,
                timestamp_ns,
                bytes(self._audio),
                False,
            )
        try:
            self._jobs.put_nowait(job)
        except queue.Full:
            # Backpressure policy: partials are disposable; finals are not.
            pass

    def end_utterance(self, ended_at_ns: int) -> None:
        with self._lock:
            if not self._utterance_id:
                return
            job = _InferenceJob(
                self._utterance_id,
                self._started_at_ns,
                ended_at_ns,
                bytes(self._audio),
                True,
            )
            self._utterance_id = ""
            self._audio = bytearray()
        while not self._stop.is_set():
            try:
                self._jobs.put(job, timeout=0.1)
                return
            except queue.Full:
                try:
                    queued = self._jobs.get_nowait()
                    if queued is not None and queued.final:
                        self._jobs.put_nowait(queued)
                except queue.Empty:
                    pass

    def stop(self) -> None:
        self._stop.set()
        try:
            self._jobs.put_nowait(None)
        except queue.Full:
            pass
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=5.0)
        self._thread = None

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                job = self._jobs.get(timeout=0.2)
            except queue.Empty:
                continue
            if job is None:
                break
            inference_started = monotonic_ns()
            try:
                text, confidence, language = self._infer(job.pcm16)
            except Exception:
                log.exception("%s inference failed", self.name)
                continue
            text = text.strip()
            if not text:
                continue
            if not job.final and self._last_partial_text.get(job.utterance_id) == text:
                continue
            self._last_partial_text[job.utterance_id] = text
            if job.final:
                self._last_partial_text.pop(job.utterance_id, None)
            callback = self._callback
            if callback:
                callback(
                    Transcript(
                        text=text,
                        is_final=job.final,
                        utterance_id=job.utterance_id,
                        started_at_ns=job.started_at_ns,
                        ended_at_ns=job.ended_at_ns if job.final else None,
                        confidence=confidence,
                        language=language,
                        provider=self.name,
                        latency_ms=(monotonic_ns() - inference_started) / 1_000_000,
                    )
                )

    def _load(self) -> None:
        raise NotImplementedError

    def _infer(self, pcm16: bytes) -> tuple[str, float | None, str | None]:
        raise NotImplementedError


class SenseVoiceProvider(BufferedInferenceProvider):
    name = "sensevoice"

    def __init__(self, config: AudioSTTConfig):
        super().__init__(config)
        self._model = None
        self._postprocess = lambda value: value

    def _load(self) -> None:
        from funasr import AutoModel

        try:
            from funasr.utils.postprocess_utils import rich_transcription_postprocess

            self._postprocess = rich_transcription_postprocess
        except ImportError:
            pass
        self._model = AutoModel(
            model=self._config.stt_model,
            trust_remote_code=False,
            device="cpu",
            disable_update=True,
        )

    def _infer(self, pcm16: bytes) -> tuple[str, float | None, str | None]:
        if self._model is None:
            raise RuntimeError("SenseVoice is not loaded")
        samples = np.frombuffer(pcm16, dtype="<i2").astype(np.float32) / 32768.0
        result = self._model.generate(
            input=samples,
            cache={},
            language=self._config.language,
            use_itn=True,
            batch_size_s=60,
        )
        item = result[0] if result else {}
        raw = str(item.get("text", "")) if isinstance(item, dict) else str(item)
        return self._postprocess(raw), None, self._config.language


class OpenAIFinalProvider(BufferedInferenceProvider):
    """Compatibility provider. It emits finals only and is not local streaming."""

    name = "openai"

    def push_audio(self, pcm16: bytes, timestamp_ns: int) -> None:
        with self._lock:
            if self._utterance_id:
                self._audio.extend(pcm16)

    def _load(self) -> None:
        return

    def _infer(self, pcm16: bytes) -> tuple[str, float | None, str | None]:
        from openai_service import transcribe

        samples = np.frombuffer(pcm16, dtype="<i2").astype(np.float32) / 32768.0
        return transcribe(samples, 16_000), None, "en"

def pcm16_to_wav_bytes(pcm16: bytes, sample_rate: int = 16000) -> bytes:
    num_channels = 1
    sample_width = 2  # 16-bit
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(num_channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm16)
    buf.seek(0)
    return buf.read()


class SpeechToTextSTTProvider:
    name = "speech_to_text"

    def __init__(self, config: AudioSTTConfig):
        self._config = config
        self._callback: Callable[[Transcript], None] | None = None

        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._audio_queue: asyncio.Queue | None = None
        self._stop_event = threading.Event()

        self._utterance_id = ""
        self._started_at_ns = 0
        self._audio_buffer = bytearray()
        self._last_send_time = 0.0
        self._lock = threading.Lock()
        self._raw_transcript_history = ""

    def start(self, on_transcript: Callable[[Transcript], None]) -> None:
        self._callback = on_transcript
        self._stop_event.clear()
        self._audio_buffer = bytearray()
        self._last_send_time = time.time()
        self._raw_transcript_history = ""

        self._thread = threading.Thread(
            target=self._run_loop,
            name="stt-speech-to-text",
            daemon=True,
        )
        self._thread.start()

    def begin_utterance(self, utterance_id: str, started_at_ns: int) -> None:
        with self._lock:
            self._utterance_id = utterance_id
            self._started_at_ns = started_at_ns
            self._audio_buffer = bytearray()
            self._last_send_time = time.time()
            log.info("Speech-to-Text STT begin utterance: %s", utterance_id)

    def push_audio(self, pcm16: bytes, timestamp_ns: int) -> None:
        with self._lock:
            if not self._utterance_id:
                return
            self._audio_buffer.extend(pcm16)

            provider_type = getattr(self._config, "speech_to_text_provider", "openai").lower()
            if provider_type == "deepgram":
                interval = 0.04
            elif provider_type == "openai":
                interval = 2.0
            else:
                interval = 0.25

            now = time.time()
            if now - self._last_send_time >= interval:
                self._queue_send_chunk()
                self._last_send_time = now

    def end_utterance(self, ended_at_ns: int) -> None:
        with self._lock:
            if not self._utterance_id:
                return
            if len(self._audio_buffer) > 0:
                self._queue_send_chunk()
            self._utterance_id = ""

    def stop(self) -> None:
        self._stop_event.set()
        if self._loop:
            if self._audio_queue:
                try:
                    self._loop.call_soon_threadsafe(
                        self._audio_queue.put_nowait, None
                    )
                except Exception:
                    pass
        if self._thread:
            self._thread.join(timeout=3.0)
            self._thread = None
        self._loop = None
        self._audio_queue = None

    def _queue_send_chunk(self) -> None:
        if not self._audio_buffer:
            return

        provider_type = getattr(self._config, "speech_to_text_provider", "openai").lower()
        if provider_type == "deepgram":
            # Stream raw PCM16 bytes directly for low-latency continuous stream
            chunk_bytes = bytes(self._audio_buffer)
        else:
            # Package as WAV chunk for OpenAI
            chunk_bytes = pcm16_to_wav_bytes(bytes(self._audio_buffer), self._config.sample_rate)

        self._audio_buffer = bytearray()

        if self._loop and self._audio_queue:
            try:
                self._loop.call_soon_threadsafe(
                    self._audio_queue.put_nowait, chunk_bytes
                )
            except Exception as e:
                log.debug("Failed to queue send chunk: %s", e)

    def _run_loop(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._main_async())
        finally:
            try:
                # Cancel all remaining pending tasks to prevent runtime errors on close
                pending = asyncio.all_tasks(self._loop)
                if pending:
                    for task in pending:
                        task.cancel()
                    self._loop.run_until_complete(
                        asyncio.gather(*pending, return_exceptions=True)
                    )
            except Exception:
                pass
            try:
                self._loop.close()
            except Exception:
                pass

    async def _main_async(self) -> None:
        self._audio_queue = asyncio.Queue()

        from audio_processing.audio_processing_backend.providers import get_stt_provider
        from audio_processing.audio_processing_backend.services import llm_cleaning

        provider = getattr(self._config, "speech_to_text_provider", "openai")
        openai_key = getattr(self._config, "speech_to_text_openai_key", "")
        # fallback to standard OpenAI key if configured
        if not openai_key:
            try:
                import config as main_config
                openai_key = getattr(main_config, "OPENAI_API_KEY", "")
            except Exception:
                pass

        deepgram_key = getattr(self._config, "speech_to_text_deepgram_key", "")

        log.info("Initializing Speech-to-Text STT provider in-process (provider=%s)", provider)
        stt_provider_instance = get_stt_provider(
            provider,
            openai_key=openai_key,
            deepgram_key=deepgram_key,
        )

        async def handler_callback(
            raw_text: str,
            is_final: bool = True,
            speaker_id: int | None = None,
            confidence: float | None = None,
        ):
            if not raw_text:
                return

            # Emit raw text as partial transcript immediately
            if not is_final:
                if self._callback:
                    partial_latency = ((monotonic_ns() - self._started_at_ns) / 1_000_000) if self._started_at_ns > 0 else 0.0
                    self._callback(
                        Transcript(
                            text=raw_text,
                            is_final=False,
                            utterance_id=self._utterance_id or "speech-to-text-utterance",
                            started_at_ns=self._started_at_ns,
                            provider="speech_to_text",
                            latency_ms=partial_latency,
                            speaker_id=speaker_id,
                            confidence=confidence,
                        )
                    )
                return

            # Update context history
            self._raw_transcript_history = (self._raw_transcript_history + " " + raw_text)[-2000:]

            # Run LLM refining
            cleaned_val = raw_text
            import openai_service
            if not getattr(self._config, "disable_llm_cleaning", True) and not getattr(openai_service, "_use_local_fallback_directly", False):
                try:
                    cleaned_val = await llm_cleaning(self._raw_transcript_history, raw_text)
                    if cleaned_val == "[SILENCE]":
                        cleaned_val = raw_text
                except Exception as e:
                    log.debug("Error during in-process LLM cleaning: %s", e)
                    cleaned_val = raw_text
            else:
                pass

            if cleaned_val and cleaned_val != "[SILENCE]":
                cleaned_val = cleaned_val.replace(". and", ", and")
                cleaned_val = cleaned_val.replace(". And", ", and")
                cleaned_val = cleaned_val.replace(" .", ".")
                cleaned_val = cleaned_val.replace(" ,", ",")

            if self._callback:
                final_latency = ((monotonic_ns() - self._started_at_ns) / 1_000_000) if self._started_at_ns > 0 else 0.0
                self._callback(
                    Transcript(
                        text=cleaned_val,
                        is_final=True,
                        utterance_id=self._utterance_id or "speech-to-text-utterance",
                        started_at_ns=self._started_at_ns,
                        ended_at_ns=monotonic_ns(),
                        provider="speech_to_text",
                        latency_ms=final_latency,
                        speaker_id=speaker_id,
                        confidence=confidence,
                    )
                )


        try:
            await stt_provider_instance.process_audio_stream(self._audio_queue, handler_callback)
        except Exception as e:
            log.error("Speech-to-Text STT in-process provider error: %s", e)



def create_stt_provider(config: AudioSTTConfig) -> StreamingSTTProvider:
    provider = config.stt_provider.lower()
    if provider in ("dhwani", "speech_to_text"):
        try:
            import websockets  # noqa: F401
            return SpeechToTextSTTProvider(config)
        except ImportError:
            raise RuntimeError(
                "Speech-to-Text STT provider requires the 'websockets' package. "
                "Install it in the virtual environment or run pip install websockets."
            )
    if provider == "sensevoice":
        try:
            import funasr  # noqa: F401

            return SenseVoiceProvider(config)
        except ImportError:
            if not config.allow_component_fallback:
                raise RuntimeError("SenseVoice requires the funasr package")
            if not config.allow_openai_stt:
                raise RuntimeError(
                    "SenseVoice unavailable and OpenAI STT fallback is disabled. "
                    "Install requirements-audio-enterprise.txt or set "
                    "AUDIO_ALLOW_OPENAI_STT=true in .env."
                )
            log.warning("SenseVoice unavailable; using final-only OpenAI fallback")
            return OpenAIFinalProvider(config)
    if provider == "openai":
        if not config.allow_openai_stt:
            raise RuntimeError(
                "AUDIO_STT_PROVIDER=openai is disabled by AUDIO_ALLOW_OPENAI_STT=false"
            )
        return OpenAIFinalProvider(config)
    raise ValueError(f"Unknown STT provider: {config.stt_provider}")

