"""Low-latency streaming transcription for the active system-audio runtime.

Audio frames are queued from the recorder thread and streamed as raw PCM16 to
Deepgram. Interim hypotheses update the UI immediately; speech-final messages
are the only ones that trigger answer generation.
"""
from __future__ import annotations

import asyncio
import logging
import queue
import threading
from typing import Callable

import numpy as np

log = logging.getLogger(__name__)


class LiveDeepgramTranscriber:
    def __init__(
        self,
        api_key: str,
        on_partial: Callable[[str], None],
        on_final: Callable[[str], None],
        on_status: Callable[[str], None] | None = None,
        *,
        sample_rate: int = 16000,
        queue_capacity: int = 250,
    ) -> None:
        if not api_key:
            raise ValueError("DEEPGRAM_API_KEY is required for live streaming transcription")
        try:
            from audio_processing.audio_processing_backend.providers.deepgram import DeepgramProvider
        except ImportError as exc:
            raise RuntimeError("Install deepgram-sdk to enable streaming transcription") from exc
        self._provider = DeepgramProvider(api_key=api_key)
        self._on_partial = on_partial
        self._on_final = on_final
        self._on_status = on_status or (lambda _message: None)
        self._sample_rate = sample_rate
        self._incoming: queue.Queue[bytes] = queue.Queue(maxsize=queue_capacity)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._audio_queue: asyncio.Queue[bytes | None] | None = None
        self._wake: asyncio.Event | None = None
        self._committed: list[str] = []
        self._interim = ""
        self._lock = threading.Lock()
        self._pending_final_text = ""
        self._final_flush_task: asyncio.Task | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._thread_main, name="live-deepgram-stt", daemon=True)
        self._thread.start()

    def push_audio(self, samples: np.ndarray) -> None:
        """Enqueue one short float32 frame; safe for the recorder worker."""
        if self._stop.is_set():
            return
        values = np.asarray(samples, dtype=np.float32).reshape(-1)
        if values.size == 0:
            return
        pcm16 = (np.clip(values, -1.0, 1.0) * 32767.0).astype("<i2", copy=False).tobytes()
        try:
            self._incoming.put_nowait(pcm16)
        except queue.Full:
            # Drop the oldest waiting frame instead of blocking capture or building stale latency.
            try:
                self._incoming.get_nowait()
            except queue.Empty:
                pass
            try:
                self._incoming.put_nowait(pcm16)
            except queue.Full:
                return
        loop, wake = self._loop, self._wake
        if loop and wake and loop.is_running():
            try:
                loop.call_soon_threadsafe(wake.set)
            except RuntimeError:
                pass

    def stop(self) -> None:
        self._stop.set()
        loop, wake = self._loop, self._wake
        if loop and loop.is_running() and wake:
            try:
                loop.call_soon_threadsafe(wake.set)
            except RuntimeError:
                pass
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=4.0)
        self._thread = None

    def _thread_main(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._run_session())
        except Exception as exc:
            log.exception("Live Deepgram session failed")
            self._on_status(f"Live transcription stopped: {exc}")
        finally:
            try:
                pending = asyncio.all_tasks(loop)
                for task in pending:
                    task.cancel()
                if pending:
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            except Exception:
                pass
            loop.close()
            self._loop = None
            self._audio_queue = None
            self._wake = None

    async def _run_session(self) -> None:
        self._audio_queue = asyncio.Queue(maxsize=250)
        self._wake = asyncio.Event()
        pump = asyncio.create_task(self._pump_audio(), name="deepgram-audio-pump")
        provider = asyncio.create_task(
            self._provider.process_audio_stream(self._audio_queue, self._handle_transcript),
            name="deepgram-websocket-session",
        )
        self._on_status("Live system-audio transcription connecting...")
        done, pending = await asyncio.wait((pump, provider), return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for task in done:
            error = task.exception()
            if error:
                raise error
        if not self._stop.is_set():
            self._on_status("Live transcription disconnected; restart listening to reconnect")

    async def _pump_audio(self) -> None:
        assert self._audio_queue is not None and self._wake is not None
        while not self._stop.is_set():
            if self._incoming.empty():
                self._wake.clear()
                # Avoid losing a wake between the empty check and clear.
                if not self._incoming.empty():
                    continue
                await self._wake.wait()
            while True:
                try:
                    frame = self._incoming.get_nowait()
                except queue.Empty:
                    break
                if self._audio_queue.full():
                    try:
                        self._audio_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                try:
                    self._audio_queue.put_nowait(frame)
                except asyncio.QueueFull:
                    pass
        try:
            self._audio_queue.put_nowait(None)
        except asyncio.QueueFull:
            pass

    async def _handle_transcript(
        self,
        text: str,
        segment_final: bool = False,
        speaker_id: int | None = None,
        confidence: float | None = None,
        speech_final: bool = False,
    ) -> None:
        del speaker_id, confidence
        text = (text or "").strip()
        if not text:
            return
        with self._lock:
            if segment_final:
                # Deepgram finalizes short segments separately; retain them until the pause ends.
                if not self._committed or self._committed[-1] != text:
                    self._committed.append(text)
                self._interim = ""
            else:
                self._interim = text
            display = " ".join(part for part in [*self._committed, self._interim] if part).strip()
            if speech_final:
                final_text = display
                self._committed.clear()
                self._interim = ""
            else:
                final_text = ""
        if display:
            self._on_partial(display)
        if final_text:
            # Deepgram can mark a clause as speech-final during a short pause
            # inside one interview question. Debounce the callback so adjacent
            # finals are combined before the UI treats them as separate questions.
            self._pending_final_text = " ".join(
                part for part in (self._pending_final_text, final_text) if part
            ).strip()
            if self._final_flush_task and not self._final_flush_task.done():
                self._final_flush_task.cancel()
            self._final_flush_task = asyncio.create_task(self._flush_final_after_pause())

    async def _flush_final_after_pause(self) -> None:
        try:
            await asyncio.sleep(1.0)
            with self._lock:
                final_text = self._pending_final_text.strip()
                self._pending_final_text = ""
                self._final_flush_task = None
            if final_text:
                self._on_final(final_text)
        except asyncio.CancelledError:
            return
