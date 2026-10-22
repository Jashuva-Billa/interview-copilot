import base64
import io
import re
import wave
from typing import Tuple

import certifi
import httpx
import numpy as np
from openai import APIConnectionError, OpenAI

import config
from coding_detector import is_coding_question
from response_parser import (
    ParsedResponse,
    parse_structured_response,
    parse_vision_response,
)

_client_instance: OpenAI | None = None
_ssl_bootstrapped = False


def _init_ssl() -> None:
    """Use OS trust store on Windows (fixes CERTIFICATE_VERIFY_FAILED)."""
    global _ssl_bootstrapped
    if _ssl_bootstrapped:
        return
    _ssl_bootstrapped = True
    if not config.SSL_VERIFY or config.SSL_CA_FILE:
        return
    if config.IS_WINDOWS:
        try:
            import truststore

            truststore.inject_into_ssl()
        except ImportError:
            pass

SYSTEM_PROMPT = """You are my real-time interview copilot for Generative AI, Machine Learning, and AI Engineering interviews. I am answering an interviewer live.

Use the candidate resume below as the source of truth.

ANSWER RULES:
- Give 1–2 crisp, concise sentences that sound natural and are easy to say aloud.
- Answer at Principal AI Engineer level: show sound engineering judgment, architecture awareness, and production trade-offs without becoming academic or verbose.
- Answer the exact question first; avoid filler, headings, long lists, and repeated conclusions.
- Own experience and project answers in first person when supported by the resume. Never invent employers, projects, tools, responsibilities, metrics, or outcomes.
- For technical concepts, explain the principle and the most relevant technology or trade-off directly.
- If the resume does not support a personal-experience claim, answer the technical question generally rather than pretending it is personal experience.
- Be accurate; do not guess when the transcript is clearly incomplete.

Candidate resume:
{resume}

Target role: {role}
{job_desc}
"""

CODING_PROMPT = """You are a live coding interview copilot. The candidate is solving on CoderPad, HackerRank, LeetCode, or similar.

They need:
1) What to SAY while thinking (short bullets, conversational)
2) Copy-paste ready code in {lang} that runs on the platform
3) Time/space complexity
4) Edge cases to mention

Output EXACTLY these sections (headers must match):

===APPROACH===
- Restate the problem in one line
- 3-5 bullets: brute force idea → optimal approach → why it works
- What to say before typing ("I'll start with...")

===COMPLEXITY===
Time: O(...) — one line why
Space: O(...) — one line why

===CODE===
```{lang}
# Complete solution: correct imports, function signature, handles edge cases.
# Prefer clean, interview-standard style (not over-engineered).
# Add brief inline comments only on tricky lines.
```

===EDGE_CASES===
- bullet list of tests to mention or run

Rules:
- If problem is ambiguous, pick the most common LeetCode interpretation and note it.
- Use {lang} only in CODE section.
- For trees/graphs include standard definition helpers if needed.
- Do not include markdown outside the section format.

Candidate background (for style only, not fake experience):
{resume}

Target role: {role}
{job_desc}
"""

VISION_SCREEN_PROMPT = """You are reading a screenshot from a LIVE CODING interview.

Platforms include: LeetCode, HackerRank, CoderPad, Codility, **White-box Learning**,
Replit, CodeSignal, or any split-screen page with:
- LEFT: problem statement (description, examples, constraints)
- RIGHT: code editor with a function stub (e.g. `def classify_temperature(...): pass`)

CRITICAL RULES:
1) Read ALL problem text from the left panel AND the function signature from the editor.
2) If you see ANY problem statement OR a `def` function stub to implement → this IS a coding problem.
3) Only output NO_PROBLEM if the screen is clearly NOT coding (email, slides, blank desktop).

If coding problem, output EXACTLY these sections (headers must match):

===PROBLEM===
Copy the full problem: title, description, examples, constraints, function signature.

===APPROACH===
What the candidate should SAY out loud (bullets): restate problem → approach → before typing.

===COMPLEXITY===
Time: O(...) — one line
Space: O(...) — one line

===CODE===
```{lang}
# Complete working solution matching the on-screen function signature.
# Use only {lang}. Handle all examples and constraints.
```

===EDGE_CASES===
- bullets of tests to mention

Language: {lang}
Match the exact function name and parameters shown in the editor (e.g. classify_temperature).
Never mention AI. Ignore semi-transparent overlay windows.
"""


def format_api_error(exc: Exception) -> str:
    """User-friendly message for OpenAI / network errors."""
    text = str(exc).lower()
    if "certificate verify failed" in text or "ssl" in text:
        return (
            "SSL certificate error — launch from interview-copilot with start_interview_copilot.bat, "
            "then: pip install certifi. Or set SSL_VERIFY=false in .env (last resort)."
        )
    if isinstance(exc, APIConnectionError):
        return f"Cannot reach OpenAI — check internet/VPN. ({exc})"
    return str(exc)


def _ssl_verify_setting() -> bool | str:
    if not config.SSL_VERIFY:
        return False
    if config.SSL_CA_FILE:
        return config.SSL_CA_FILE
    if config.IS_WINDOWS:
        return True
    return certifi.where()


def check_ssl_connectivity() -> tuple[bool, str]:
    """Quick probe before interview — returns (ok, message)."""
    _init_ssl()
    try:
        with httpx.Client(verify=_ssl_verify_setting(), timeout=15.0) as client:
            client.get("https://api.openai.com")
        return True, "SSL OK"
    except Exception as exc:
        text = str(exc).lower()
        if "certificate verify failed" in text or "ssl" in text:
            return False, (
                "SSL failed — run: .\\venv\\Scripts\\pip install truststore "
                "then restart. Or set SSL_VERIFY=false in .env (last resort)."
            )
        return False, f"Network: {exc}"


def _client() -> OpenAI:
    global _client_instance
    _init_ssl()
    if _client_instance is not None:
        return _client_instance
    if not config.openai_key_configured():
        raise ValueError(
            "OPENAI_API_KEY missing in interview-copilot/.env only (must start with sk-)"
        )
    http_client = httpx.Client(verify=_ssl_verify_setting(), timeout=120.0)
    _client_instance = OpenAI(
        api_key=config.OPENAI_API_KEY,
        http_client=http_client,
    )
    return _client_instance


def _audio_to_wav_bytes(samples: np.ndarray, sample_rate: int) -> bytes:
    audio = np.clip(samples, -1.0, 1.0)
    pcm = (audio * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm.tobytes())
    buf.seek(0)
    return buf.read()


def transcribe(samples: np.ndarray, sample_rate: int) -> str:
    client = _client()
    wav_bytes = _audio_to_wav_bytes(samples, sample_rate)
    bio = io.BytesIO(wav_bytes)
    bio.name = "chunk.wav"
    result = client.audio.transcriptions.create(
        model=config.OPENAI_TRANSCRIBE_MODEL,
        file=bio,
        language="en",
    )
    return (result.text or "").strip()


def should_use_coding_mode(question: str, force_coding: bool = False) -> bool:
    if force_coding:
        return True
    if config.CODING_MODE == "always":
        return True
    return is_coding_question(question)


def generate_answer(
    question: str,
    conversation: list[dict],
    force_coding: bool = False,
) -> ParsedResponse:
    coding = should_use_coding_mode(question, force_coding)
    client = _client()
    resume = config.load_resume_context() or "(No resume loaded — add local_data/resume_context.txt)"
    job_desc = ""
    if config.JOB_DESCRIPTION.strip():
        job_desc = f"Job focus:\n{config.JOB_DESCRIPTION.strip()}"

    if coding:
        lang = config.CODE_LANGUAGE
        system = CODING_PROMPT.format(
            lang=lang,
            resume=resume,
            role=config.JOB_ROLE,
            job_desc=job_desc,
        )
        user_msg = (
            f"Coding interview problem (from interviewer):\n{question}\n\n"
            "Give the full structured response for the candidate."
        )
        max_tokens = 2000
        temperature = 0.2
    else:
        system = SYSTEM_PROMPT.format(
            resume=resume,
            role=config.JOB_ROLE,
            job_desc=job_desc,
        )
        user_msg = f"Interviewer asked:\n{question}"
        max_tokens = 800
        temperature = 0.4

    messages = [{"role": "system", "content": system}]
    for turn in conversation[-6:]:
        messages.append(turn)
    messages.append({"role": "user", "content": user_msg})

    response = client.chat.completions.create(
        model=config.OPENAI_CHAT_MODEL,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    raw = (response.choices[0].message.content or "").strip()
    return parse_structured_response(raw, coding)


def solve_from_screenshot(
    image_jpeg: bytes,
    detail: str = "high",
) -> Tuple[str, ParsedResponse]:
    """Read problem from screen image and return coding solution."""
    client = _client()
    lang = config.CODE_LANGUAGE
    resume = config.load_resume_context() or ""
    job_desc = config.JOB_DESCRIPTION.strip()

    b64 = base64.standard_b64encode(image_jpeg).decode("ascii")
    instructions = VISION_SCREEN_PROMPT.format(lang=lang)
    extra = ""
    if resume:
        extra += f"\nCandidate background:\n{resume[:2000]}"
    if job_desc:
        extra += f"\nJob focus:\n{job_desc[:800]}"

    response = client.chat.completions.create(
        model=config.OPENAI_VISION_MODEL,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": instructions + extra},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{b64}",
                            "detail": detail,
                        },
                    },
                ],
            }
        ],
        temperature=0.2,
        max_tokens=2500,
    )
    raw = (response.choices[0].message.content or "").strip()
    problem, parsed = parse_vision_response(raw)
    parsed.is_coding = True

    prob_upper = (problem or "").strip().upper()
    looks_coding = _screen_looks_like_coding(problem, raw)

    if prob_upper == "NO_PROBLEM" and not looks_coding:
        raise ValueError(
            "No coding problem on screen. Open your coding tab (White-box / LeetCode) "
            "and press Scan screen (Ctrl+Shift+S)."
        )

    prob_text = problem if prob_upper != "NO_PROBLEM" else parsed.problem_text
    if not prob_text:
        prob_text = _extract_problem_fallback(raw)

    # Vision sometimes returns problem only — generate solution via chat model
    if (not parsed.code or len(parsed.approach.strip()) < 30) and prob_text:
        parsed = generate_answer(prob_text, [], force_coding=True)
        parsed.is_coding = True
        parsed.problem_text = prob_text
        problem = prob_text

    if not parsed.code and not parsed.approach.strip():
        raise ValueError(
            "Could not read the coding problem. Zoom the problem panel and scan again."
        )

    if not problem and prob_text:
        problem = prob_text

    return problem, parsed


def _screen_looks_like_coding(problem: str, raw: str) -> bool:
    blob = f"{problem}\n{raw}".lower()
    hints = (
        "def ",
        "problem statement",
        "implement",
        "write a function",
        "constraints",
        "examples",
        "classify_",
        "pass  #",
        "leetcode",
        "white-box",
        "whitebox",
        "coderpad",
        "hackerrank",
    )
    return any(h in blob for h in hints)


def _extract_problem_fallback(raw: str) -> str:
    m = re.search(
        r"===\s*PROBLEM\s*===\s*(.+?)(?====\s*(?:APPROACH|CODE|COMPLEXITY)|\Z)",
        raw,
        re.DOTALL | re.IGNORECASE,
    )
    if m:
        text = m.group(1).strip()
        if text.upper() != "NO_PROBLEM":
            return text
    return ""
