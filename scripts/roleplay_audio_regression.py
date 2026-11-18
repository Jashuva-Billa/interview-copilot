"""Replay temporary US/Indian English role-play audio through the desktop runtime."""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import tempfile
import time
import urllib.request
from difflib import SequenceMatcher
from pathlib import Path
from unittest.mock import patch

import av
import edge_tts
import numpy as np
from faster_whisper import WhisperModel

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / path) for path in ("", "app", "app/core")]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

MODEL_BASE = "https://huggingface.co/Systran/faster-whisper-tiny.en/resolve/main"
VOICES = {"US": ("en-US-AriaNeural", "en-US-GuyNeural"), "IN": ("en-IN-PrabhatNeural", "en-IN-NeerjaNeural")}
EXCHANGES = (
    (("How do you test a search system", "before you release it?"),
     "I compare the results against a list of known good answers.",
     "Start with a labeled set of queries and check retrieval quality before release.",
     ("test", "search"), 0.45, 160),
    (("Could you explain how a hash table works", "and what happens when two keys have the same hash?"),
     "Both keys can go into the same bucket, where I compare the actual keys.",
     "Use the hash to select a bucket, then compare keys to resolve collisions.",
     ("table", "keys"), 0.62, 185),
    (("How do you handle a slow database request", "and keep the service available?"),
     "I set a timeout and retry only requests that are safe to repeat.",
     "Set a deadline and retry idempotent operations within that deadline.",
     ("database", "service"), 0.30, 205),
    (("How do you measure cost?",),
     "I measure the cost per request and watch the daily budget.",
     "Track cost per request and set budget alerts.",
     ("cost",), 0, 150),
    (("Suppose your service receives ten times the usual traffic and the database starts getting slow",
      "how would you measure the problem, protect the database, and make sure customers can still use the service?"),
     "I would check the service metrics first, then limit traffic and reduce the load on the database.",
     "Measure latency and saturation, then limit concurrency and shed excess load.",
     ("traffic", "database"), 0.50, 175),
)


class SpeechSynthesizer:
    def __init__(self, target_rate: int, folder: Path):
        self.target_rate = target_rate
        self.file = folder / "tts-preview.mp3"

    def speak(self, text: str, voice: str, speed: int) -> np.ndarray:
        rate = f"{round((speed / 175 - 1) * 100):+d}%"
        asyncio.run(edge_tts.Communicate(text, voice, rate=rate).save(str(self.file)))
        resampler = av.AudioResampler(format="fltp", layout="mono", rate=self.target_rate)
        with av.open(str(self.file)) as container:
            frames = [out.to_ndarray().ravel() for frame in container.decode(audio=0) for out in resampler.resample(frame)]
        frames.extend(frame.to_ndarray().ravel() for frame in resampler.resample(None))
        audio = np.concatenate(frames)
        active = np.flatnonzero(np.abs(audio) > 0.003)
        if active.size == 0:
            raise RuntimeError(f"TTS produced silence for {voice}")
        pad = self.target_rate // 25
        return audio[max(0, active[0] - pad):active[-1] + pad]


def recognizer(folder: Path):
    import shutil

    model_path = os.environ.get("COPILOT_REGRESSION_WHISPER_MODEL")
    if not model_path:
        model_folder = folder / "whisper"
        model_folder.mkdir()
        for name in ("config.json", "model.bin", "tokenizer.json", "vocabulary.txt"):
            with urllib.request.urlopen(f"{MODEL_BASE}/{name}", timeout=90) as response, (model_folder / name).open("wb") as output:
                shutil.copyfileobj(response, output)
        model_path = str(model_folder)
    model = WhisperModel(model_path, device="cpu", compute_type="auto", cpu_threads=2)

    def transcribe(samples, sample_rate):
        if sample_rate != 16000:
            raise ValueError(f"Unexpected sample rate: {sample_rate}")
        segments, _ = model.transcribe(samples, language="en", beam_size=3, temperature=0,
                                       condition_on_previous_text=False, without_timestamps=True)
        return " ".join(segment.text.strip() for segment in segments).strip()

    return transcribe


class VirtualInput:
    def __init__(self, callback):
        self.callback = callback

    def start(self):
        pass

    def stop(self):
        pass

    close = stop


def wait_until(app, condition, label, timeout=12):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.processEvents()
        if condition():
            return
        time.sleep(0.01)
    raise AssertionError(f"Timed out waiting for {label}")


def words(text):
    return re.findall(r"[a-z]+", text.casefold())


def word_coverage(expected, actual):
    target, heard = words(expected), words(actual)
    return sum(block.size for block in SequenceMatcher(None, target, heard, autojunk=False).get_matching_blocks()) / len(target)


def replay(recorder, samples, capture):
    padding = (-len(samples)) % capture.FRAME_SAMPLES + 4 * capture.SAMPLE_RATE
    padded = np.pad(samples, (capture.FRAME_SAMPLES, padding))
    for index in range(0, len(padded), capture.FRAME_SAMPLES):
        frame = padded[index:index + capture.FRAME_SAMPLES]
        recorder._stream.callback(frame, len(frame), None, None)
        # Keep this faster than real time without overrunning the production queue.
        while recorder._queue.qsize() > 12:
            time.sleep(0.002)


def run(folder: Path) -> None:
    import project_bootstrap

    config_path = folder / ".env"
    config_path.write_text("OPENAI_API_KEY=sk-regression-placeholder\n", encoding="utf-8")
    project_bootstrap.ENV_FILE = config_path
    if sys.platform.startswith("linux"):
        # The sandbox lacks PortAudio. Synthetic frames bypass it on all OSes.
        import types

        sys.modules["sounddevice"] = types.SimpleNamespace(InputStream=None)

    import run_app
    import main as app_module
    from audio_processing import audio_capture as capture
    from generate_audio_question_corpus import write_wav
    from llm_project.response_parser import ParsedResponse

    synth = SpeechSynthesizer(capture.SAMPLE_RATE, folder)
    transcribe = recognizer(folder)
    rng = np.random.default_rng(42)
    questions, errors, results = [], [], []
    roleplay_file = folder / "roleplay.jsonl"

    def generate(question, history, force_coding, on_chunk):
        questions.append(question)
        answer = scripted_reply
        parsed = ParsedResponse(False, answer, "", "", "", answer)
        on_chunk("openai", parsed)
        return {"openai": parsed}

    def device(source):
        return capture.InputDevice(
            None, source, system_audio=source == "system", wasapi=source == "system" and sys.platform == "win32"
        )

    with (
        patch.object(app_module.config, "OPENAI_API_KEY", "sk-regression-placeholder"),
        patch.object(app_module.config, "AUDIO_STT_MODE", "snapshot"),
        patch.object(app_module, "transcribe", side_effect=transcribe),
        patch.object(app_module, "generate_answer", side_effect=generate),
        patch.object(capture, "resolve_input_device", side_effect=device),
        patch.object(capture.sd, "InputStream", side_effect=lambda **kwargs: VirtualInput(kwargs["callback"])),
        patch.object(capture, "WasapiLoopbackStream", side_effect=lambda *args: VirtualInput(args[-1])),
        patch.object(capture, "MacSystemAudioStream", side_effect=VirtualInput),
    ):
        runner = run_app.AppRunner()
        runner.bridge.error.connect(errors.append)
        runner._start_listening()
        try:
            assert runner.system_recorder and runner.mic_recorder, errors
            for accent, voices in VOICES.items():
                for index, (parts, answer, scripted_reply, terms, pause, speed) in enumerate(EXCHANGES, 1):
                    start_questions, start_answers = len(questions), len(runner.candidate_transcripts)
                    for recorder in (runner.system_recorder, runner.mic_recorder):
                        replay(recorder, rng.normal(0, 0.0008, capture.SAMPLE_RATE).astype(np.float32), capture)
                    clips = [synth.speak(part, voices[0], speed) for part in parts]
                    question_audio = clips[0] if len(clips) == 1 else np.concatenate((clips[0], np.zeros(int(pause * capture.SAMPLE_RATE), dtype=np.float32), clips[1]))
                    answer_audio = synth.speak(answer, voices[1], speed + 8)
                    write_wav(folder / f"{accent}-{index}-question.wav", question_audio)
                    write_wav(folder / f"{accent}-{index}-answer.wav", answer_audio)
                    expected = " ".join(parts)
                    replay(runner.system_recorder, question_audio, capture)
                    wait_until(runner.app, lambda: len(runner.conversation) >= (start_questions + 1) * 2 and scripted_reply in runner.window.columns["openai"]["answer_box"].toPlainText(), f"{accent}-{index} Copilot answer")
                    replay(runner.mic_recorder, answer_audio, capture)
                    wait_until(runner.app, lambda: len(runner.candidate_transcripts) >= start_answers + 1 and runner.candidate_transcripts[-1] in runner.window.live_transcript_box.toPlainText(), f"{accent}-{index} mic answer")
                    heard_q, heard_a = questions[-1], runner.candidate_transcripts[-1]
                    score_q, score_a = word_coverage(expected, heard_q), word_coverage(answer, heard_a)
                    record = dict(accent=accent, interviewer_voice=voices[0], candidate_voice=voices[1],
                                  question=expected, candidate=answer, copilot=scripted_reply,
                                  heard_question=heard_q, heard_answer=heard_a)
                    with roleplay_file.open("a", encoding="utf-8") as output:
                        output.write(json.dumps(record) + "\n")
                    print(f"{accent}-{index}: question {score_q:.0%}, candidate {score_a:.0%}, pause {pause:.2f}s", flush=True)
                    assert len(questions) == start_questions + 1, f"Unexpected prompt: {record}"
                    assert len(runner.candidate_transcripts) == start_answers + 1, f"Candidate answer was split: {record}"
                    assert runner.window.get_last_question() == heard_q, f"Question UI mismatch: {record}"
                    assert scripted_reply in runner.window.columns["openai"]["answer_box"].toPlainText(), f"Answer UI mismatch: {record}"
                    assert heard_a in runner.window.live_transcript_box.toPlainText(), f"Candidate UI mismatch: {record}"
                    reference_q = transcribe(question_audio, capture.SAMPLE_RATE)
                    reference_a = transcribe(answer_audio, capture.SAMPLE_RATE)
                    reference_score_q = word_coverage(expected, reference_q)
                    reference_score_a = word_coverage(answer, reference_a)
                    print(f"{accent}-{index} direct decode: {reference_score_q:.0%} / {reference_score_a:.0%}", flush=True)
                    assert score_q >= 0.50 and score_a >= 0.50, f"Low recognition coverage: {record}"
                    assert score_q + max(0.16, 1 / len(words(expected))) + 1e-6 >= reference_score_q, f"Capture lost question words: {reference_q!r} -> {heard_q!r}"
                    assert score_a + max(0.16, 1 / len(words(answer))) + 1e-6 >= reference_score_a, f"Capture lost candidate words: {reference_a!r} -> {heard_a!r}"
                    assert all(any(token.startswith(term) for token in words(heard_q)) for term in terms if any(token.startswith(term) for token in words(reference_q))), f"Capture lost key terms: {record}"
                    results.append((accent, score_q, score_a))
            assert not errors, errors
        finally:
            runner._stop_listening()
            for executor in (runner.executor, runner.audio_executor, runner.partial_executor):
                executor.shutdown(wait=True)
            runner.window.close()

    for accent in VOICES:
        subset = [r for r in results if r[0] == accent]
        print(f"{sys.platform} {accent}: {len(subset)} exchanges passed, mean ordered word coverage "
              f"{np.mean([r[1] for r in subset]):.0%} question / {np.mean([r[2] for r in subset]):.0%} candidate.")


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="copilot-roleplay-") as name:
        folder = Path(name)
        run(folder)
    assert not folder.exists(), "Temporary role-play data was not cleaned"
    print("Temporary role-play data removed.")
