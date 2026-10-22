"""Replay generated WAVs through production VAD and report segmentation/latency."""
from __future__ import annotations
import argparse, json, sys, time, wave, threading, re
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "wboxai_app", ROOT / "audio_processing", ROOT / "llm_project"):
    if str(p) not in sys.path: sys.path.insert(0, str(p))
from audio_processing.audio_capture import FRAME_SAMPLES, FRAME_MS, SAMPLE_RATE, SpeechRecorder, EnergyVAD
CORPUS = ROOT / "tests" / "audio_corpus"
REPORTS = ROOT / "reports"

def read_wav(path):
    with wave.open(str(path), "rb") as f:
        rate, channels, width = f.getframerate(), f.getnchannels(), f.getsampwidth()
        if width != 2: raise ValueError("Expected 16-bit PCM WAV: " + str(path))
        x = np.frombuffer(f.readframes(f.getnframes()), dtype="<i2").astype(np.float32) / 32768.0
    if channels > 1: x = x.reshape(-1, channels).mean(axis=1)
    if rate != SAMPLE_RATE:
        size = max(1, round(x.size * SAMPLE_RATE / rate))
        x = np.interp(np.linspace(0, x.size - 1, size), np.arange(x.size), x).astype(np.float32)
    return x

def replay(path, realtime):
    finals, partials = [], []
    recorder = SpeechRecorder(on_chunk=finals.append, on_partial=partials.append,
                              on_status=lambda _: None, source="system")
    recorder._loopback = True
    recorder._vad = EnergyVAD(loopback=True)
    recorder._stop.clear()
    worker = threading.Thread(target=recorder._process_loop, daemon=True)
    worker.start()
    audio = read_wav(path)
    padded = np.pad(audio, (0, max(0, FRAME_SAMPLES - audio.size)))
    started = time.perf_counter()
    for offset in range(0, padded.size - FRAME_SAMPLES + 1, FRAME_SAMPLES):
        recorder._queue.put(padded[offset:offset + FRAME_SAMPLES], timeout=2)
        if realtime: time.sleep(FRAME_MS / 1000)
        elif offset % (FRAME_SAMPLES * 20) == 0: time.sleep(0.001)
    for _ in range(max(200, int(4500 / FRAME_MS))):
        recorder._queue.put(np.zeros(FRAME_SAMPLES, dtype=np.float32), timeout=2)
        if realtime: time.sleep(FRAME_MS / 1000)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and not recorder._queue.empty(): time.sleep(0.02)
    time.sleep(0.1)
    recorder._stop.set()
    worker.join(timeout=3)
    return {"file": path.name, "audio_seconds": round(audio.size / SAMPLE_RATE, 3),
            "replay_processing_ms": round((time.perf_counter()-started)*1000, 1),
            "segments": len(finals), "partial_events": len(partials),
            "segment_durations_seconds": [round(c.samples.size / SAMPLE_RATE, 3) for c in finals],
            "chunks": finals}

def coverage(expected, actual):
    def normalize(value):
        value = value.lower().replace("l l m", "llm").replace("f one", "f1")
        value = value.replace("bm twenty five", "bm25").replace("lang graph", "langgraph")
        value = value.replace("human-in-the-loop", "human in the loop").replace("cross-validation", "cross validation").replace("f1-score", "f1 score").replace("documents", "document")
        return re.sub(r"[^a-z0-9]+", " ", value).split()
    a = normalize(expected)
    b = normalize(actual)
    row = [0] * (len(b)+1)
    for word in a:
        nxt = [0]
        for j, other in enumerate(b, 1):
            nxt.append(row[j-1]+1 if word == other else max(row[j], nxt[-1]))
        row = nxt
    return row[-1] / max(1, len(a))

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--transcribe", action="store_true", help="Calls configured STT service; may incur API cost")
    parser.add_argument("--realtime", action="store_true", help="Replay audio at real-time speed")
    args = parser.parse_args()
    manifest_path = CORPUS / "manifest.json"
    if not manifest_path.exists():
        print("Generate corpus first: python scripts/generate_audio_question_corpus.py")
        return 2
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    by_file = {x["audio_file"]: x for x in manifest}
    transcribe_fn = None
    if args.transcribe:
        try:
            from llm_project.openai_service import transcribe as transcribe_fn
        except Exception as exc:
            print("Cannot initialize STT: " + str(exc))
            return 3
    report = {"mode": "real_time_replay" if args.realtime else "accelerated_vad_replay",
              "transcription_enabled": args.transcribe,
              "note": "Accelerated replay is not live latency. STT timings exist only with --transcribe.",
              "cases": []}
    for path in sorted(CORPUS.glob("*.wav")):
        c = replay(path, args.realtime)
        item = by_file.get(path.name, {})
        c["case_id"] = item.get("id", path.stem)
        c["topic"] = item.get("topic", "unknown")
        c["expected_question"] = item.get("expected_question", "")
        ids = item.get("expected_question_ids")
        if ids:
            c["expected_question_count"] = len(ids)
            c["mixing_suspected"] = c["segments"] < len(ids)
        if transcribe_fn:
            texts = []
            stt_times = []
            for chunk in c.pop("chunks"):
                t0 = time.perf_counter()
                try: texts.append(transcribe_fn(chunk.samples, chunk.sample_rate) or "")
                except Exception as exc: texts.append("STT ERROR: " + str(exc)[:200])
                stt_times.append(round((time.perf_counter()-t0)*1000, 1))
            c["transcripts"] = texts
            c["stt_latency_ms"] = stt_times
            c["total_stt_ms"] = round(sum(stt_times), 1)
            if c["expected_question"] and texts:
                c["transcript_text"] = " ".join(texts)
                c["word_coverage"] = round(coverage(c["expected_question"], c["transcript_text"]), 3)
                c["question_fully_taken"] = c["word_coverage"] >= 0.90
        else: c.pop("chunks")
        report["cases"].append(c)
        print("{}: segments={} partials={} replay_ms={}".format(path.name, c["segments"], c["partial_events"], c["replay_processing_ms"]))
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "audio_latency_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    lines = ["# Interview Copilot Audio Latency Report", "",
             "Mode: " + report["mode"], "Real STT enabled: " + str(args.transcribe), "",
             "Replay processing time is not production latency unless --realtime is used. --transcribe calls the configured STT service. The suite exercises production VAD segmentation, not the GUI or LLM.", "",
             "| Audio | Topic | Expected questions | Segments | Partial updates | Replay ms | STT ms | Assessment |",
             "|---|---|---:|---:|---:|---:|---:|---|"]
    for c in report["cases"]:
        expected = c.get("expected_question_count", 1)
        assessment = "CHECK MIXING" if c.get("mixing_suspected") else ("STT not run" if not args.transcribe else ("CHECK TRANSCRIPT" if c.get("word_coverage", 1) < 0.90 else "coverage >= 90%"))
        lines.append("| {} | {} | {} | {} | {} | {} | {} | {} |".format(c["file"], c["topic"], expected, c["segments"], c["partial_events"], c["replay_processing_ms"], c.get("total_stt_ms", "—"), assessment))
    if args.transcribe:
        lines += ["", "## Transcript review", "", "| Audio | Coverage | Fully taken (>=90%) | Transcript |", "|---|---:|---|---|"]
        for c in report["cases"]:
            if "word_coverage" in c:
                lines.append("| {} | {:.1%} | {} | {} |".format(c["file"], c["word_coverage"], c["question_fully_taken"], c.get("transcript_text", "").replace("|", "/")))
    lines += ["", "## How to interpret", "",
              "- Single-question WAVs should produce one final segment; zero suggests VAD missed speech and multiple segments suggest splitting.",
              "- The mixed three-question WAV should produce three segments; fewer may indicate merged questions.",
              "- Word coverage is an approximate LCS word-order score, not semantic accuracy. Read transcript text for omissions, substitutions, and mixing.",
              "- This suite does not call the LLM; only --transcribe calls STT.", ""]
    (REPORTS / "audio_latency_report.md").write_text("\n".join(lines), encoding="utf-8")
    print("Reports: reports/audio_latency_report.md and reports/audio_latency_report.json")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
