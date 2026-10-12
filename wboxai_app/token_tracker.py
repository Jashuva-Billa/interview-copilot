import time
from pathlib import Path
import config

class TokenTracker:
    def __init__(self):
        self.transactions = []
        self.candidate_answers = [] # list of (timestamp, candidate_spoken_text)

    def record_candidate_speech(self, text: str):
        self.candidate_answers.append((time.time(), text))

    def record_llm_call(self, provider: str, model: str, prompt_text: str, response_text: str):
        prompt_tokens = self.count_tokens(prompt_text)
        resp_tokens = self.count_tokens(response_text)
        
        # Calculate cost
        cost = self.calculate_cost(provider, model, prompt_tokens, resp_tokens)
        
        self.transactions.append({
            "timestamp": time.time(),
            "provider": provider,
            "model": model,
            "prompt_text": prompt_text,
            "response_text": response_text,
            "prompt_tokens": prompt_tokens,
            "response_tokens": resp_tokens,
            "cost": cost
        })

    def count_tokens(self, text: str) -> int:
        try:
            import tiktoken
            encoding = tiktoken.get_encoding("cl100k_base")
            return len(encoding.encode(text))
        except Exception:
            return max(1, (len(text) + 3) // 4)

    def calculate_cost(self, provider: str, model: str, prompt_tokens: int, resp_tokens: int) -> float:
        provider = provider.lower()
        model = model.lower()
        
        input_rate = 0.0
        output_rate = 0.0
        
        if "openai" in provider:
            if "gpt-4o-mini" in model:
                input_rate = 0.15 / 1_000_000
                output_rate = 0.60 / 1_000_000
            elif "gpt-4o" in model:
                input_rate = 2.50 / 1_000_000
                output_rate = 10.00 / 1_000_000
            else:
                # default fallback to gpt-4o-mini
                input_rate = 0.15 / 1_000_000
                output_rate = 0.60 / 1_000_000
        elif "gemini" in provider:
            if "gemini-1.5-pro" in model:
                input_rate = 1.25 / 1_000_000
                output_rate = 5.00 / 1_000_000
            else:
                # default fallback to gemini-1.5-flash
                input_rate = 0.075 / 1_000_000
                output_rate = 0.30 / 1_000_000
        elif "claude" in provider:
            if "claude-3-5-sonnet" in model or "claude-3.5-sonnet" in model:
                input_rate = 3.00 / 1_000_000
                output_rate = 15.00 / 1_000_000
            elif "claude-3-haiku" in model:
                input_rate = 0.25 / 1_000_000
                output_rate = 1.25 / 1_000_000
            else:
                input_rate = 3.00 / 1_000_000
                output_rate = 15.00 / 1_000_000
                
        return (prompt_tokens * input_rate) + (resp_tokens * output_rate)

    def write_report(self, candidate_name: str, timestamp: str):
        safe_name = "".join(c for c in candidate_name if c.isalnum() or c in (" ", "_", "-")).strip().replace(" ", "_")
        project_root = Path(__file__).resolve().parent.parent / "reports"
        project_root.mkdir(parents=True, exist_ok=True)
        report_path = project_root / f"token_report_{safe_name}_{timestamp}.md"
        
        total_prompt = 0
        total_resp = 0
        total_cost = 0.0
        
        lines = []
        lines.append("# LLM Session Token & Cost Tracking Report\n")
        lines.append(f"Generated on: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        lines.append(f"Target Job Role: **{config.JOB_ROLE}**\n")
        lines.append("## Transaction Summary\n")
        lines.append("| # | Timestamp | Provider | Model | Prompt Tokens | Output Tokens | Total Tokens | Estimated Cost ($) |")
        lines.append("|---|---|---|---|---|---|---|---|")
        
        for idx, tx in enumerate(self.transactions, 1):
            ts = time.strftime('%H:%M:%S', time.localtime(tx["timestamp"]))
            total_prompt += tx["prompt_tokens"]
            total_resp += tx["response_tokens"]
            total_cost += tx["cost"]
            total_tokens = tx["prompt_tokens"] + tx["response_tokens"]
            lines.append(f"| {idx} | {ts} | {tx['provider'].capitalize()} | {tx['model']} | {tx['prompt_tokens']} | {tx['response_tokens']} | {total_tokens} | ${tx['cost']:.6f} |")
            
        lines.append("\n## Totals\n")
        lines.append(f"- **Total Input/Prompt Tokens**: {total_prompt}")
        lines.append(f"- **Total Output/Response Tokens**: {total_resp}")
        lines.append(f"- **Total Tokens Utilized**: {total_prompt + total_resp}")
        lines.append(f"- **Estimated Session Cost**: **${total_cost:.4f}**\n")
        
        lines.append("## Conversation & Candidate Transcript Logs\n")
        
        # Link questions with their responses and candidate speech (by order or timestamp proximity)
        for idx, tx in enumerate(self.transactions, 1):
            lines.append(f"### Q{idx} Dialogue Block")
            # Extract question from prompt or model input
            question = ""
            if "Interviewer asked:\n" in tx["prompt_text"]:
                question = tx["prompt_text"].split("Interviewer asked:\n")[-1].strip()
            elif "Coding interview problem (from interviewer):\n" in tx["prompt_text"]:
                question = tx["prompt_text"].split("Coding interview problem (from interviewer):\n")[-1].split("\n\nGive the")[0].strip() if "\n\nGive the" in tx["prompt_text"] else tx["prompt_text"].split("Coding interview problem (from interviewer):\n")[-1].strip()
            else:
                question = "Could not parse question from prompt"
                
            lines.append(f"- **Question**: {question}")
            lines.append(f"- **LLM ({tx['provider'].capitalize()}) Answer**: {tx['response_text']}")
            
            # Find candidate speech that occurred shortly after this transaction
            next_tx_time = self.transactions[idx]["timestamp"] if idx < len(self.transactions) else time.time() + 99999
            spoken = []
            for c_ts, text in self.candidate_answers:
                if tx["timestamp"] <= c_ts < next_tx_time:
                    spoken.append(text)
            
            cand_ans = " ".join(spoken) if spoken else "(Candidate did not speak for this question)"
            lines.append(f"- **Candidate Spoken Answer**: {cand_ans}\n")
            lines.append("-" * 30 + "\n")
            
        report_path.write_text("\n".join(lines), encoding="utf-8")
        print(f"[Token Tracker] Report saved to {report_path}", flush=True)

# Global tracker instance
tracker_instance = TokenTracker()
