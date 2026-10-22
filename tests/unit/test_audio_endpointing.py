from __future__ import annotations

import threading
import time
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
for candidate in (ROOT, ROOT / "wboxai_app", ROOT / "app" / "core"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from audio_processing.audio_capture import (
    FRAME_MS, FRAME_SAMPLES, SAMPLE_RATE, AudioChunk, EnergyVAD,
    SpeechRecorder, adaptive_end_silence_ms, partial_indicates_unfinished,
)


class Signal:
    def __init__(self):
        self.values = []

    def emit(self, value):
        self.values.append(value)


def _frames(samples):
    samples = np.asarray(samples, dtype=np.float32)
    if samples.size % FRAME_SAMPLES:
        samples = np.pad(samples, (0, FRAME_SAMPLES - samples.size % FRAME_SAMPLES))
    for i in range(0, samples.size, FRAME_SAMPLES):
        yield samples[i:i + FRAME_SAMPLES]


def test_partial_transcript_extends_endpoint_only_for_unfinished_clause(monkeypatch):
    monkeypatch.setenv("AUDIO_END_SILENCE_MS", "3200")
    monkeypatch.setenv("AUDIO_LONG_UTTERANCE_SILENCE_MS", "4000")
    assert partial_indicates_unfinished("How do Python generators work, and")
    assert partial_indicates_unfinished("Explain the difference between")
    assert not partial_indicates_unfinished("How do Python generators work?")
    assert adaptive_end_silence_ms(1500) == 3200
    assert adaptive_end_silence_ms(1500, unfinished=True) == 4000


def test_paused_unfinished_question_stays_one_segment_and_generates_once(monkeypatch):
    """Simulate partial STT, a 2.7s pause, then the rest of the same question."""
    monkeypatch.setenv("AUDIO_END_SILENCE_MS", "3200")
    monkeypatch.setenv("AUDIO_LONG_UTTERANCE_SILENCE_MS", "4000")
    finals = []
    recorder = SpeechRecorder(
        on_chunk=finals.append,
        on_partial=lambda chunk: recorder.update_partial_transcript(
            chunk.utterance_id,
            "How do Python generators work, and" if chunk.samples.size < SAMPLE_RATE * 3
            else "How do Python generators work, and when would you use yield instead of return?",
        ),
        on_status=lambda _: None,
        source="system",
    )
    recorder._loopback = True
    recorder._vad = EnergyVAD(loopback=True)
    recorder._stop.clear()
    worker = threading.Thread(target=recorder._process_loop, daemon=True)
    worker.start()

    def speech(seconds, frequency):
        t = np.arange(int(SAMPLE_RATE * seconds), dtype=np.float32) / SAMPLE_RATE
        return (0.12 * np.sin(2 * np.pi * frequency * t)).astype(np.float32)

    sequence = np.concatenate([
        np.zeros(int(SAMPLE_RATE * 0.2), dtype=np.float32),
        speech(0.8, 220),
        np.zeros(int(SAMPLE_RATE * 2.7), dtype=np.float32),
        speech(0.9, 330),
        np.zeros(int(SAMPLE_RATE * 3.8), dtype=np.float32),
    ])
    try:
        for frame in _frames(sequence):
            recorder._queue.put(frame, timeout=2)
            time.sleep(FRAME_MS / 1000)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not recorder._queue.empty():
            time.sleep(0.02)
        time.sleep(0.15)
    finally:
        recorder._stop.set()
        worker.join(timeout=3)

    assert len(finals) == 1, f"Expected one final segment, got {len(finals)}"

    # Exercise the app's final-audio worker with the real emitted chunk but mocked STT/LLM.
    import app.main as app_main
    calls = []
    monkeypatch.setattr(app_main, "transcribe", lambda samples, rate: (
        "How do Python generators work, and when would you use yield instead of return?"
    ))
    app = object.__new__(app_main.InterviewApp)
    app._finalized_utterances = set()
    app._busy = False
    app._force_next_coding = False
    app.bridge = SimpleNamespace(status=Signal(), question=Signal(), error=Signal())
    app._generate_for_question = lambda text, force: calls.append((text, force))
    app._drain_pending_stream_question = lambda: None
    app._worker_process_audio(finals[0])
    assert len(calls) == 1, f"Expected one answer-generation call, got {len(calls)}"


def test_completed_question_calls_llm_generation_exactly_once(monkeypatch):
    import app.main as app_main

    llm_calls = []
    response = SimpleNamespace(
        full_text="A generator yields values lazily.",
        approach="",
        is_coding=False,
        code="",
    )

    def fake_generate_answer(question, conversation, force_coding, on_chunk=None):
        llm_calls.append((question, force_coding))
        return response

    monkeypatch.setattr(app_main, "generate_answer", fake_generate_answer)
    monkeypatch.setattr(app_main.config, "get_active_providers", lambda: ["openai"], raising=False)
    app = object.__new__(app_main.InterviewApp)
    app.conversation = []
    app.bridge = SimpleNamespace(
        status=Signal(), question=Signal(), answer=Signal(), error=Signal()
    )
    app._busy = False

    app._generate_for_question("How do Python generators work?", False)

    assert len(llm_calls) == 1
    assert llm_calls[0][0] == "How do Python generators work?"
    assert len(app.conversation) == 2
