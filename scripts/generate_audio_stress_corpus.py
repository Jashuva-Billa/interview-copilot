"""Generate a 100+ case synthetic audio stress corpus.

Each question has five incremental internal pauses (0.3, 0.7, 1.2, 1.8, 2.6s).
Voice, speaking rate, and style rotate across variants. Uses Edge neural TTS and
the existing ffmpeg conversion helper; requires network access for synthesis.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tests" / "audio_stress_corpus"
RATE = 16_000
sys.path.insert(0, str(ROOT / "scripts"))
from generate_audio_question_corpus import edge_tts_clip, read_wav, write_wav

# Deliberately varied question shapes and technical vocabulary.
QUESTIONS = [
    ("python", "How do Python generators work, and when would you use yield instead of return?"),
    ("python", "Can you explain decorators in Python, including a practical example from production?"),
    ("python", "What is the difference between asyncio gather and creating tasks manually?"),
    ("python", "How would you diagnose a memory leak in a long-running Python service?"),
    ("python", "When would you choose a dataclass over a Pydantic model?"),
    ("python", "How do Python context managers handle resource cleanup when an exception occurs?"),
    ("python", "What are the trade-offs between multiprocessing and multithreading for CPU-bound work?"),
    ("python", "How would you make an API client resilient to timeouts, retries, and rate limits?"),
    ("machine_learning", "How do you detect overfitting, and which regularization techniques would you try first?"),
    ("machine_learning", "Explain precision, recall, F one score, and how you select a threshold for an imbalanced dataset."),
    ("machine_learning", "How would you handle data leakage when building a time-series validation pipeline?"),
    ("machine_learning", "What is the difference between feature selection and feature extraction?"),
    ("genai", "How does self-attention work in a transformer, and why does positional encoding matter?"),
    ("genai", "How would you evaluate hallucination in a language model beyond checking exact-match answers?"),
    ("genai", "When would you use fine-tuning instead of retrieval-augmented generation?"),
    ("rag", "How do you combine BM25 keyword search with dense vector retrieval and reranking?"),
    ("rag", "The retriever returns the right document, but the model gives inconsistent answers; how do you debug it?"),
    ("rag", "How do chunk size and overlap affect retrieval precision, recall, and context quality?"),
    ("agentic_ai", "How would you design a LangGraph workflow with tool calling, retries, and human approval?"),
    ("agentic_ai", "How do you prevent an agent from repeating tool calls or getting stuck in a reasoning loop?"),
]

# Four English locales; each variant rotates voice, speed, and pause.
VOICES = [
    "en-US-AriaNeural", "en-US-GuyNeural", "en-GB-SoniaNeural",
    "en-GB-RyanNeural", "en-IN-NeerjaNeural", "en-IN-PrabhatNeural",
    "en-AU-NatashaNeural", "en-AU-WilliamNeural",
]
PAUSES = [0.3, 0.7, 1.2, 1.8, 2.6]
RATES = [0.88, 0.96, 1.0, 1.08, 1.16]


def trim_edge_silence(audio: np.ndarray) -> np.ndarray:
    """Trim TTS encoder padding so requested internal pauses are accurate."""
    frame = max(1, int(RATE * 0.01))
    usable = audio[: len(audio) // frame * frame]
    if usable.size == 0:
        return audio
    rms = np.sqrt(np.mean(usable.reshape(-1, frame) ** 2, axis=1))
    peak = float(rms.max(initial=0.0))
    active = np.flatnonzero(rms > max(0.0015, peak * 0.035))
    if active.size == 0:
        return audio
    pad = int(RATE * 0.08)
    start = max(0, int(active[0]) * frame - pad)
    end = min(audio.size, (int(active[-1]) + 1) * frame + pad)
    return audio[start:end]


def split_question(question: str) -> tuple[str, str]:
    # Prefer clause boundaries; fall back to a word boundary near the middle.
    match = re.search(r"\s+(and|but|when|including)\s+|,\s+", question, re.I)
    if match:
        cut = match.start()
        left = question[:cut].strip().rstrip(",")
        separator = match.group(0).strip()
        right = question[match.end():].strip()
        # Keep conjunctions on the partial side: they are a reliable unfinished-clause cue.
        if separator.lower() in {"and", "but", "when", "including"}:
            return left + ", " + separator, right
        return left, right
    words = question.split()
    cut = max(3, len(words) // 2)
    return " ".join(words[:cut]).rstrip("?,."), " ".join(words[cut:]).strip().rstrip("?.") + "?"


async def synthesize(text: str, voice: str, rate: float, path: Path) -> None:
    await edge_tts_clip(text, voice, rate, path)


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="Regenerate all clips and overwrite existing WAVs")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = []
    # 20 questions x 5 pauses = 100 distinct WAV fixtures.
    for qi, (topic, question) in enumerate(QUESTIONS):
        left, right = split_question(question)
        for pi, pause_s in enumerate(PAUSES):
            variant = qi * len(PAUSES) + pi
            voice = VOICES[(qi + pi) % len(VOICES)]
            rate = RATES[(qi * 2 + pi) % len(RATES)]
            case_id = f"stress_{variant + 1:03d}_{topic}_pause_{int(pause_s * 10):02d}"
            out_path = OUT / f"{case_id}.wav"
            if not args.force and out_path.exists() and out_path.stat().st_size > 1000:
                audio = read_wav(out_path)
                manifest.append({
                    "id": case_id, "topic": topic, "expected_question": question,
                    "audio_file": out_path.name, "voice": voice, "rate": rate,
                    "pause_seconds": pause_s, "duration_seconds": round(audio.size / RATE, 3),
                    "sample_rate": RATE, "engine": "edge_tts",
                    "variation": "voice+rate+incremental internal pause",
                })
                print(f"[{len(manifest):03d}/100] reused {out_path.name}")
                continue
            left_path = OUT / f"{case_id}_left.wav"
            right_path = OUT / f"{case_id}_right.wav"
            try:
                await synthesize(left, voice, rate, left_path)
                await synthesize(right, voice, rate, right_path)
            except Exception as exc:
                print(f"Synthesis failed at {case_id}: {exc}", file=sys.stderr)
                return 2
            left_audio = trim_edge_silence(read_wav(left_path))
            right_audio = trim_edge_silence(read_wav(right_path))
            left_path.unlink(missing_ok=True)
            right_path.unlink(missing_ok=True)
            lead = np.zeros(int(RATE * (0.1 + (variant % 4) * 0.08)), dtype=np.float32)
            pause = np.zeros(int(RATE * pause_s), dtype=np.float32)
            tail = np.zeros(int(RATE * (0.4 + (variant % 3) * 0.15)), dtype=np.float32)
            audio = np.concatenate([lead, left_audio, pause, right_audio, tail])
            out_path = OUT / f"{case_id}.wav"
            write_wav(out_path, audio)
            manifest.append({
                "id": case_id, "topic": topic, "expected_question": question,
                "audio_file": out_path.name, "voice": voice, "rate": rate,
                "pause_seconds": pause_s, "duration_seconds": round(audio.size / RATE, 3),
                "sample_rate": RATE, "engine": "edge_tts",
                "variation": "voice+rate+incremental internal pause",
            })
            print(f"[{len(manifest):03d}/100] {out_path.name} voice={voice} rate={rate} pause={pause_s:.1f}s")
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Generated {len(manifest)} stress WAVs in {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
