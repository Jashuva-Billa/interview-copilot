from __future__ import annotations

import asyncio
import threading
import time
import unittest
from unittest.mock import patch

import numpy as np

from audio_processing import audio_capture
from audio_processing.live_deepgram import LiveDeepgramTranscriber


class LiveAudioLatencyTests(unittest.TestCase):
    def test_default_capture_frame_and_endpoint_targets_are_responsive(self):
        self.assertLessEqual(audio_capture.FRAME_MS, 20)
        with patch.dict("os.environ", {
            "AUDIO_END_SILENCE_MS": "500",
            "AUDIO_LONG_UTTERANCE_SILENCE_MS": "1000",
        }):
            self.assertEqual(audio_capture.adaptive_end_silence_ms(1000), 500)
            self.assertEqual(audio_capture.adaptive_end_silence_ms(9000), 1000)

    def test_resampler_preserves_target_sample_count(self):
        samples = np.linspace(-1.0, 1.0, 441, dtype=np.float32)
        output = audio_capture._resample_linear(samples, 44100, 16000)
        self.assertEqual(output.size, 160)
        self.assertEqual(output.dtype, np.float32)
        self.assertTrue(np.isfinite(output).all())

    def test_stream_only_recorder_forwards_frames_without_batch_snapshots(self):
        received = []
        partials = []
        finals = []
        recorder = audio_capture.SpeechRecorder(
            on_chunk=finals.append,
            on_partial=partials.append,
            on_status=lambda _: None,
            source="system",
            on_frame=lambda frame: received.append(frame.copy()),
            stream_only=True,
        )
        recorder._stop.clear()
        worker = threading.Thread(target=recorder._process_loop, daemon=True)
        worker.start()
        recorder._queue.put(np.ones(audio_capture.FRAME_SAMPLES, dtype=np.float32), timeout=1)
        deadline = time.monotonic() + 1.0
        while not received and time.monotonic() < deadline:
            time.sleep(0.005)
        recorder._stop.set()
        worker.join(timeout=1.0)
        self.assertEqual(len(received), 1)
        self.assertEqual(finals, [])
        self.assertEqual(partials, [])

    def test_streaming_transcripts_emit_partial_then_final_only_at_speech_boundary(self):
        partials: list[str] = []
        finals: list[str] = []
        stt = object.__new__(LiveDeepgramTranscriber)
        stt._on_partial = partials.append
        stt._on_final = finals.append
        stt._committed = []
        stt._interim = ""
        stt._lock = threading.Lock()
        stt._pending_final_text = ""
        stt._final_flush_task = None

        asyncio.run(stt._handle_transcript("How does", segment_final=False, speech_final=False))
        self.assertEqual(partials, ["How does"])
        self.assertEqual(finals, [])

        asyncio.run(stt._handle_transcript("How does RAG work", segment_final=True, speech_final=False))
        self.assertEqual(partials[-1], "How does RAG work")
        self.assertEqual(finals, [])

        async def finish_question():
            await stt._handle_transcript("with hybrid search", segment_final=True, speech_final=True)
            await asyncio.sleep(1.05)
        asyncio.run(finish_question())
        self.assertEqual(finals, ["How does RAG work with hybrid search"])
        self.assertEqual(stt._committed, [])
        self.assertEqual(stt._interim, "")

    def test_streaming_mode_requires_key_but_does_not_touch_api_until_instantiated(self):
        with self.assertRaisesRegex(ValueError, "DEEPGRAM_API_KEY"):
            LiveDeepgramTranscriber("", lambda _: None, lambda _: None)


if __name__ == "__main__":
    unittest.main()


def test_stream_finals_are_queued_without_overwriting_while_answer_is_generating():
    import threading
    from types import SimpleNamespace
    from app.main import InterviewApp

    class Signal:
        def __init__(self):
            self.values = []
        def emit(self, value):
            self.values.append(value)

    app = object.__new__(InterviewApp)
    app._stream_final_lock = threading.Lock()
    app._busy = True
    app._pending_stream_questions = []
    app.bridge = SimpleNamespace(status=Signal())
    app._on_stream_final("What are the time and space complexities?")
    app._on_stream_final("How did you design the multi-agent system in Phase 2?")

    assert app._pending_stream_questions == [
        "What are the time and space complexities?",
        "How did you design the multi-agent system in Phase 2?",
    ]
