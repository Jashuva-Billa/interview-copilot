"""Measure actual quiet gaps in the synthetic stress WAVs."""
from __future__ import annotations
import json, wave
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "tests" / "audio_stress_corpus"
manifest = json.loads((CORPUS / "manifest.json").read_text(encoding="utf-8"))
rows = []
for item in manifest:
    path = CORPUS / item["audio_file"]
    with wave.open(str(path), "rb") as f:
        rate, width, channels = f.getframerate(), f.getsampwidth(), f.getnchannels()
        raw = f.readframes(f.getnframes())
    dtype = "<i2" if width == 2 else "<f4"
    audio = np.frombuffer(raw, dtype=dtype).astype(np.float32)
    if width == 2:
        audio /= 32768.0
    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1)
    frame = max(1, int(rate * 0.01))
    usable = audio[:len(audio)//frame*frame]
    rms = np.sqrt(np.mean(usable.reshape(-1, frame)**2, axis=1))
    active = rms > max(0.0015, float(rms.max(initial=0)) * 0.035)
    # Longest continuous quiet run and quiet runs of at least 100ms.
    quiet = ~active
    runs = []
    start = None
    for i, is_quiet in enumerate(quiet):
        if is_quiet and start is None:
            start = i
        elif not is_quiet and start is not None:
            if i - start >= 10:
                runs.append((round(start*0.01, 3), round((i-start)*0.01, 3)))
            start = None
    if start is not None and len(quiet)-start >= 10:
        runs.append((round(start*0.01, 3), round((len(quiet)-start)*0.01, 3)))
    internal = [(s,d) for s,d in runs if s > 0.2 and s+d < len(audio)/rate-0.2]
    longest = max((d for _,d in internal), default=0)
    rows.append({
        "file": item["audio_file"], "requested_pause_s": item["pause_seconds"],
        "duration_s": round(len(audio)/rate, 3), "longest_internal_quiet_s": longest,
        "internal_quiet_runs": internal,
    })
summary = {}
for pause in sorted({x["requested_pause_s"] for x in rows}):
    subset = [x for x in rows if x["requested_pause_s"] == pause]
    vals = [x["longest_internal_quiet_s"] for x in subset]
    summary[str(pause)] = {
        "count": len(vals), "min_longest_gap_s": min(vals),
        "median_longest_gap_s": float(np.median(vals)), "max_longest_gap_s": max(vals),
        "at_least_requested": sum(v >= pause for v in vals),
    }
out = {"summary_by_requested_pause": summary, "cases": rows}
(ROOT / "reports").mkdir(exist_ok=True)
(ROOT / "reports" / "audio_silence_measurements.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
print(json.dumps(summary, indent=2))
print("Detailed measurements: reports/audio_silence_measurements.json")
