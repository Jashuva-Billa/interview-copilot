from __future__ import annotations

import sys
from pathlib import Path

# Bootstrap paths before importing packages
_root = Path(__file__).resolve().parents[2]
for _p in (_root, _root / "wboxai_app", _root / "audio_processing", _root / "llm_project"):
    _p_str = str(_p.resolve())
    if _p_str not in sys.path:
        sys.path.insert(0, _p_str)

import threading
import time
import unittest

import numpy as np

from audio_stt.buffer import AudioRingBuffer
from audio_stt.config import AudioSTTConfig
from audio_stt.dsp import BasicAudioEnhancer, float_to_pcm16
from audio_stt.events import EventKind, Transcript
from audio_stt.pipeline import AudioToTextPipeline


class FakeSource:
    def __init__(self):
        self.audio = None
        self.error = None

    def start(self, on_audio, on_error):
        self.audio, self.error = on_audio, on_error

    def stop(self):
        return

    def current_device(self):
        return "Test microphone"

    def feed(self, value: float, count: int, frame_samples: int):
        for _ in range(count):
            self.audio(
                np.full(frame_samples, value, dtype=np.float32),
                16_000,
                time.monotonic_ns(),
            )


class FakeEnhancer:
    def process(self, near_end, far_end=None):
        return near_end

    def reset(self):
        return


class FakeVAD:
    def probability(self, frame):
        return 0.99 if float(np.mean(np.abs(frame))) > 0.1 else 0.01

    def reset(self):
        return


class FakeSTT:
    name = "fake"

    def __init__(self):
        self.callback = None
        self.begun = []
        self.audio = bytearray()
        self.ended = []

    def start(self, callback):
        self.callback = callback

    def begin_utterance(self, utterance_id, started_at_ns):
        self.begun.append((utterance_id, started_at_ns))

    def push_audio(self, pcm16, timestamp_ns):
        self.audio.extend(pcm16)

    def end_utterance(self, ended_at_ns):
        self.ended.append(ended_at_ns)
        utterance_id, started = self.begun[-1]
        self.callback(
            Transcript(
                "test transcript",
                True,
                utterance_id,
                started,
                ended_at_ns,
                provider=self.name,
            )
        )

    def stop(self):
        return


class AudioSTTTests(unittest.TestCase):
    def test_ring_buffer_is_bounded(self):
        ring = AudioRingBuffer(5)
        ring.append(np.arange(4, dtype=np.float32))
        ring.append(np.arange(4, 8, dtype=np.float32))
        np.testing.assert_array_equal(ring.tail(5), np.arange(3, 8, dtype=np.float32))
        self.assertEqual(len(ring), 5)

    def test_pcm_is_little_endian_16_bit(self):
        result = np.frombuffer(
            float_to_pcm16(np.array([-2.0, 0.0, 2.0], dtype=np.float32)),
            dtype="<i2",
        )
        np.testing.assert_array_equal(result, [-32767, 0, 32767])

    def test_enhancer_output_is_finite_and_bounded(self):
        enhancer = BasicAudioEnhancer(AudioSTTConfig())
        result = enhancer.process(np.ones(512, dtype=np.float32) * 4)
        self.assertTrue(np.all(np.isfinite(result)))
        self.assertLessEqual(float(np.max(np.abs(result))), 1.0)

    def test_pipeline_emits_speech_and_final_transcript(self):
        config = AudioSTTConfig(
            min_speech_ms=64,
            end_silence_ms=64,
            pre_speech_ms=64,
        )
        source, stt = FakeSource(), FakeSTT()
        pipeline = AudioToTextPipeline(
            config,
            source=source,
            enhancer=FakeEnhancer(),
            vad=FakeVAD(),
            stt=stt,
        )
        events = []
        final = threading.Event()

        def receive(event):
            events.append(event)
            if event.kind == EventKind.FINAL_TRANSCRIPT:
                final.set()

        pipeline.subscribe(receive)
        pipeline.start()
        source.feed(0.5, 3, config.frame_samples)
        source.feed(0.0, 3, config.frame_samples)
        self.assertTrue(final.wait(2.0))
        pipeline.stop()

        kinds = [event.kind for event in events]
        self.assertIn(EventKind.SPEECH_STARTED, kinds)
        self.assertIn(EventKind.SPEECH_ENDED, kinds)
        self.assertIn(EventKind.FINAL_TRANSCRIPT, kinds)
        self.assertGreater(len(stt.audio), 0)


if __name__ == "__main__":
    unittest.main()
