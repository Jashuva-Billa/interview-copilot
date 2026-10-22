"""Run 100+ generated pause/voice variants through the production VAD."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import test_audio_latency as base
CORPUS = ROOT / "tests" / "audio_stress_corpus"
REPORTS = ROOT / "reports"

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--realtime", action="store_true", help="Replay each WAV at real-time speed")
    args = parser.parse_args()
    manifest_path = CORPUS / "manifest.json"
    if not manifest_path.exists():
        print("Generate first: python scripts/generate_audio_stress_corpus.py")
        return 2
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    by_file = {item["audio_file"]: item for item in manifest}
    base.CORPUS = CORPUS
    results = []
    for i, path in enumerate(sorted(CORPUS.glob("*.wav")), 1):
        item = by_file.get(path.name, {})
        result = base.replay(path, args.realtime)
        result.pop("chunks", None)
        result.update({
            "topic": item.get("topic", "unknown"),
            "expected_question": item.get("expected_question", ""),
            "voice": item.get("voice", ""),
            "rate": item.get("rate", 1.0),
            "pause_seconds": item.get("pause_seconds", 0.0),
            "passed": result["segments"] == 1,
        })
        results.append(result)
        print(f"[{i:03d}/{len(manifest)}] {path.name}: segments={result['segments']} pause={result['pause_seconds']}s {'PASS' if result['passed'] else 'FAIL'}")
    REPORTS.mkdir(parents=True, exist_ok=True)
    report = {
        "mode": "real_time_replay" if args.realtime else "accelerated_vad_replay",
        "total": len(results),
        "passed": sum(x["passed"] for x in results),
        "failed": sum(not x["passed"] for x in results),
        "note": "Tests production VAD segmentation only; does not invoke STT or LLM. Accelerated replay timings are not live latency.",
        "cases": results,
    }
    (REPORTS / "audio_stress_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    lines = [
        "# Audio Stress Test Report", "",
        f"Mode: {report['mode']}", f"Total: {report['total']}",
        f"Passed (one question -> one segment): {report['passed']}",
        f"Failed: {report['failed']}", "",
        "| Audio | Topic | Voice | Rate | Pause (s) | Segments | Replay ms | Result |",
        "|---|---|---|---:|---:|---:|---:|---|",
    ]
    for x in results:
        lines.append(f"| {x['file']} | {x['topic']} | {x['voice']} | {x['rate']} | {x['pause_seconds']} | {x['segments']} | {x['replay_processing_ms']} | {'PASS' if x['passed'] else 'FAIL'} |")
    lines += ["", "## Failures", ""]
    failures = [x for x in results if not x["passed"]]
    if failures:
        for x in failures:
            lines.append(f"- {x['file']}: pause {x['pause_seconds']}s, {x['segments']} segments, voice {x['voice']}, rate {x['rate']}.")
    else:
        lines.append("No segmentation failures in this run.")
    lines += ["", "## Limitations", "", report["note"], "The suite tests energy-based VAD; transcript-aware deferral requires a separate app-level test with partial STT results mocked or live STT enabled.", ""]
    (REPORTS / "audio_stress_report.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"Summary: {report['passed']}/{report['total']} passed; {report['failed']} failed")
    print("Reports: reports/audio_stress_report.md and reports/audio_stress_report.json")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
