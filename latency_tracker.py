import time
from pathlib import Path

class LatencyTracker:
    def __init__(self, filepath="latency_report.md", dialogue_filepath="interview_transcript.md"):
        root = Path(__file__).resolve().parent
        report_dir = root / "reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        self.filepath = report_dir / Path(filepath).name
        self.dialogue_filepath = report_dir / Path(dialogue_filepath).name
        self.stt_events = [] # list of dicts: {"timestamp": float, "text": str, "latency_ms": float, "is_final": bool}
        self.llm_events = [] # list of dicts: {"timestamp": float, "text": str, "ttft_ms": float, "tgt_ms": float}
        self.dialogue_events = [] # list of dicts: {"timestamp": float, "role": str, "text": str}

    def record_stt(self, text: str, is_final: bool, latency_ms: float):
        text = text.strip()
        if text:
            self.stt_events.append({
                "timestamp": time.time(),
                "text": text,
                "is_final": is_final,
                "latency_ms": latency_ms
            })
            self.generate_report()

    def record_llm(self, text: str, ttft_ms: float, tgt_ms: float):
        text = text.strip()
        if text:
            self.llm_events.append({
                "timestamp": time.time(),
                "text": text,
                "ttft_ms": ttft_ms,
                "tgt_ms": tgt_ms
            })
            self.generate_report()

    def record_dialogue(self, role: str, text: str):
        text = text.strip()
        if text:
            self.dialogue_events.append({
                "timestamp": time.time(),
                "role": role,
                "text": text
            })
            self.generate_dialogue_report()

    def generate_report(self):
        try:
            with open(self.filepath, "w", encoding="utf-8") as f:
                f.write("# Latency Analysis Report\n\n")
                f.write(f"*Last updated: {time.strftime('%Y-%m-%d %H:%M:%S')}*\n\n")

                f.write("## Summary Statistics\n\n")
                
                # STT stats
                final_stt = [e["latency_ms"] for e in self.stt_events if e["is_final"] and e["latency_ms"] > 0]
                avg_stt = sum(final_stt) / len(final_stt) if final_stt else 0.0
                
                # LLM stats
                ttfts = [e["ttft_ms"] for e in self.llm_events if e["ttft_ms"] is not None]
                avg_ttft = sum(ttfts) / len(ttfts) if ttfts else 0.0
                tgts = [e["tgt_ms"] for e in self.llm_events]
                avg_tgt = sum(tgts) / len(tgts) if tgts else 0.0

                f.write("| Metric | Average Latency | Count |\n")
                f.write("| :--- | :--- | :--- |\n")
                f.write(f"| **Speech-to-Text (STT)** | {avg_stt/1000:.2f} s ({avg_stt:.1f} ms) | {len(final_stt)} |\n")
                f.write(f"| **LLM Time-to-First-Token (TTFT)** | {avg_ttft/1000:.2f} s ({avg_ttft:.1f} ms) | {len(ttfts)} |\n")
                f.write(f"| **LLM Total Generation Time (TGT)** | {avg_tgt/1000:.2f} s ({avg_tgt:.1f} ms) | {len(tgts)} |\n\n")

                f.write("## Detailed Logs\n\n")
                
                f.write("### Speech-to-Text (STT) Transcription Latencies\n\n")
                if not final_stt:
                    f.write("*No final transcription events recorded yet.*\n")
                else:
                    f.write("| Timestamp | Transcript | Latency |\n")
                    f.write("| :--- | :--- | :--- |\n")
                    for e in reversed(self.stt_events):
                        if e["is_final"]:
                            ts = time.strftime('%H:%M:%S', time.localtime(e['timestamp']))
                            f.write(f"| {ts} | `{e['text']}` | {e['latency_ms']/1000:.2f} s ({e['latency_ms']:.1f} ms) |\n")

                f.write("\n### LLM Answering Latencies\n\n")
                if not self.llm_events:
                    f.write("*No answer generation events recorded yet.*\n")
                else:
                    f.write("| Timestamp | Question Prompt | Time-to-First-Token (TTFT) | Total Generation Time (TGT) |\n")
                    f.write("| :--- | :--- | :--- | :--- |\n")
                    for e in reversed(self.llm_events):
                        ts = time.strftime('%H:%M:%S', time.localtime(e['timestamp']))
                        ttft_str = f"{e['ttft_ms']/1000:.2f} s ({e['ttft_ms']:.1f} ms)" if e['ttft_ms'] is not None else "N/A"
                        f.write(f"| {ts} | `{e['text'][:60]}...` | {ttft_str} | {e['tgt_ms']/1000:.2f} s ({e['tgt_ms']:.1f} ms) |\n")
        except Exception as e:
            print(f"Error writing latency report: {e}")

    def generate_dialogue_report(self):
        try:
            with open(self.dialogue_filepath, "w", encoding="utf-8") as f:
                f.write("# Interview Transcript & Roleplay Log\n\n")
                f.write(f"*Last updated: {time.strftime('%Y-%m-%d %H:%M:%S')}*\n\n")
                
                f.write("| Timestamp | Role | Transcript |\n")
                f.write("| :--- | :--- | :--- |\n")
                for e in self.dialogue_events:
                    ts = time.strftime('%H:%M:%S', time.localtime(e['timestamp']))
                    role_str = f"**{e['role']}**"
                    f.write(f"| {ts} | {role_str} | {e['text']} |\n")
        except Exception as e:
            print(f"Error writing dialogue report: {e}")

    def set_dynamic_filepaths(self, candidate_name: str, timestamp: str):
        root = Path(__file__).resolve().parent / "reports"
        root.mkdir(parents=True, exist_ok=True)
        safe_name = "".join(c for c in candidate_name if c.isalnum() or c in (" ", "_", "-")).strip().replace(" ", "_")
        self.filepath = root / f"latency_report_{safe_name}_{timestamp}.md"
        self.dialogue_filepath = root / f"interview_transcript_{safe_name}_{timestamp}.md"

# Global instance
tracker = LatencyTracker()
