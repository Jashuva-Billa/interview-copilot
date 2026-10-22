"""Generate realistic synthetic interview-question WAV fixtures.

Uses Microsoft Edge neural TTS when reachable, with an offline Windows SAPI
fallback. Accent diversity depends on installed/available voices; see manifest.
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tests" / "audio_corpus"
RATE = 16_000

CASES = [
    ("python_fast", "python", "Can you explain Python decorators and when you would use them?", "en-US-AriaNeural", 1.15),
    ("python_pause", "python", "In Python, how do generators work?", "en-IN-NeerjaNeural", 0.92),
    ("ml_feature_eng", "machine_learning", "What is feature engineering, and how would you handle missing values and categorical variables?", "en-GB-SoniaNeural", 1.0),
    ("ml_overfit", "machine_learning", "Explain overfitting versus underfitting, and how cross validation helps.", "en-US-GuyNeural", 0.95),
    ("genai_transformer", "genai", "How does the transformer architecture use self attention?", "en-IN-PrabhatNeural", 1.0),
    ("genai_mispronounce", "genai", "How do you evaluate an L L M, and what is hallucination?", "en-IN-NeerjaNeural", 0.9),
    ("rag_hybrid", "rag", "In RAG, how do you combine BM twenty five keyword search with vector similarity and reranking?", "en-US-AriaNeural", 1.0),
    ("rag_pause", "rag", "How would you investigate a RAG system that retrieves the right document but gives two different answers?", "en-GB-RyanNeural", 0.9),
    ("agentic_tools", "agentic_ai", "What is the difference between an AI agent and a normal L L M chain?", "en-IN-PrabhatNeural", 1.0),
    ("agentic_langgraph", "agentic_ai", "How would you use Lang Graph, tool calling, and human in the loop approval in a production workflow?", "en-US-GuyNeural", 0.92),
    ("python_pause_long", "python", "Can you explain asynchronous programming in Python?", "en-US-AriaNeural", 1.0),
    ("ml_metrics", "machine_learning", "When would you choose precision, recall, F one score, or ROC AUC?", "en-GB-SoniaNeural", 1.05),
]


def write_wav(path: Path, samples: np.ndarray) -> None:
    samples = np.asarray(samples, dtype=np.float32).reshape(-1)
    pcm = np.clip(samples * 32767, -32768, 32767).astype("<i2")
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1); out.setsampwidth(2); out.setframerate(RATE)
        out.writeframes(pcm.tobytes())


def read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as src:
        rate, channels, width = src.getframerate(), src.getnchannels(), src.getsampwidth()
        data = src.readframes(src.getnframes())
    if width != 2:
        raise ValueError(f"Expected 16-bit WAV: {path}")
    x = np.frombuffer(data, dtype="<i2").astype(np.float32) / 32768.0
    if channels > 1: x = x.reshape(-1, channels).mean(axis=1)
    if rate != RATE:
        size = max(1, round(x.size * RATE / rate))
        x = np.interp(np.linspace(0, x.size - 1, size), np.arange(x.size), x).astype(np.float32)
    return x


async def edge_tts_clip(text: str, voice: str, rate: float, path: Path) -> str:
    import edge_tts
    communicate = edge_tts.Communicate(text, voice, rate=f"{int((rate - 1) * 100):+d}%")
    mp3 = path.with_suffix(".mp3")
    await communicate.save(str(mp3))
    try:
        import subprocess
        import imageio_ffmpeg
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        subprocess.run([ffmpeg, "-y", "-i", str(mp3), "-ac", "1", "-ar", str(RATE),
                        "-c:a", "pcm_s16le", str(path)], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        mp3.unlink(missing_ok=True)
        return voice
    except Exception as exc:
        raise RuntimeError("Could not convert Edge TTS audio to WAV: " + str(exc)) from exc


def sapi_clip(text: str, path: Path, rate: float) -> str:
    import pyttsx3
    engine = pyttsx3.init()
    voices = engine.getProperty("voices") or []
    # Alternate installed voices for timbre diversity; accent diversity is limited
    # to what the operating system actually has installed.
    voice = voices[(len(list(OUT.glob("*.wav"))) % len(voices))] if voices else None
    if voice: engine.setProperty("voice", voice.id)
    engine.setProperty("rate", max(100, min(230, int(175 * rate))))
    temp = path.with_suffix(".sapi.wav")
    engine.save_to_file(text, str(temp)); engine.runAndWait(); engine.stop()
    if not temp.exists() or temp.stat().st_size < 1000:
        raise RuntimeError("Windows SAPI did not produce a WAV file")
    x = read_wav(temp); write_wav(path, x); temp.unlink(missing_ok=True)
    return getattr(voice, "name", "Windows SAPI default")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = []
    edge_available = True
    for idx, (case_id, topic, question, voice, rate) in enumerate(CASES):
        path = OUT / f"{case_id}.wav"
        engine = "edge_tts"
        if True:
            if edge_available:
                try:
                    asyncio.run(edge_tts_clip(question, voice, rate, path))
                except Exception as exc:
                    print(f"Edge TTS unavailable ({exc}); using offline SAPI voice", file=sys.stderr)
                    edge_available = False
            if not edge_available:
                engine = "windows_sapi"
                sapi_clip(question, path, rate)
        else:
            engine = "existing_fixture"
        audio = read_wav(path)
        # Add realistic leading/trailing room tone and varied thinking pauses.
        lead = np.zeros(int(RATE * (0.18 + (idx % 3) * 0.11)), dtype=np.float32)
        tail = np.zeros(int(RATE * (0.5 + (idx % 4) * 0.27)), dtype=np.float32)
        if idx in (1, 7, 10):
            # Simulate a mid-question pause by splitting near a clause boundary.
            cut = int(audio.size * (0.42 if idx != 7 else 0.55))
            audio = np.concatenate([audio[:cut], np.zeros(int(RATE * (1.0 + idx * 0.03))), audio[cut:]])
        audio = np.concatenate([lead, audio, tail])
        write_wav(path, audio)
        manifest.append({"id": case_id, "topic": topic, "expected_question": question,
                         "audio_file": path.name, "voice_requested": voice,
                         "engine": engine, "duration_seconds": round(len(audio) / RATE, 3),
                         "sample_rate": RATE, "accent_verified": engine == "edge_tts"})
    # One mixed-file fixture tests whether separate questions are accidentally joined.
    mixed_parts = []
    for case_id in ("python_fast", "rag_hybrid", "agentic_tools"):
        x = read_wav(OUT / f"{case_id}.wav")
        mixed_parts.extend([x, np.zeros(int(RATE * 2.2), dtype=np.float32)])
    mixed_path = OUT / "three_questions_with_separators.wav"
    write_wav(mixed_path, np.concatenate(mixed_parts))
    manifest.append({"id":"three_questions_with_separators", "topic":"mixed",
                     "expected_question_ids":["python_fast","rag_hybrid","agentic_tools"],
                     "audio_file":mixed_path.name,"duration_seconds":round(len(read_wav(mixed_path))/RATE,3),
                     "sample_rate":RATE,"purpose":"check separation versus mixed question segmentation"})
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Generated {len(manifest)} WAV fixtures in {OUT}")
    print(f"Accent availability: {sum(bool(x.get('accent_verified')) for x in manifest)}/{len(CASES)} requested neural-voice clips")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
