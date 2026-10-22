"""Parse structured LLM output into overlay sections."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class ParsedResponse:
    is_coding: bool
    approach: str
    code: str
    complexity: str
    edge_cases: str
    full_text: str
    problem_text: str = ""


_SECTION_RE = re.compile(
    r"===\s*(PROBLEM|APPROACH|COMPLEXITY|CODE|EDGE_CASES)\s*===\s*",
    re.IGNORECASE,
)


def _strip_code_fences(text: str) -> str:
    text = text.strip()
    m = re.match(r"^```[\w]*\n?(.*?)```\s*$", text, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return text.replace("```", "").strip()


def parse_structured_response(raw: str, is_coding: bool) -> ParsedResponse:
    if not is_coding:
        return ParsedResponse(
            is_coding=False,
            approach=raw,
            code="",
            complexity="",
            edge_cases="",
            full_text=raw,
            problem_text="",
        )

    parts: dict[str, str] = {}
    markers = list(_SECTION_RE.finditer(raw))
    if not markers:
        code_match = re.search(r"```[\w]*\n(.*?)```", raw, re.DOTALL)
        code = _strip_code_fences(code_match.group(0)) if code_match else ""
        approach = raw[: code_match.start()].strip() if code_match else raw
        return ParsedResponse(
            is_coding=True,
            approach=approach or raw,
            code=code,
            complexity="",
            edge_cases="",
            full_text=raw,
            problem_text="",
        )

    for i, match in enumerate(markers):
        key = match.group(1).upper()
        start = match.end()
        end = markers[i + 1].start() if i + 1 < len(markers) else len(raw)
        parts[key] = raw[start:end].strip()

    problem = parts.get("PROBLEM", "").strip()

    code = _strip_code_fences(parts.get("CODE", ""))
    approach = parts.get("APPROACH", "")
    complexity = parts.get("COMPLEXITY", "")
    edge = parts.get("EDGE_CASES", "")

    display_parts = []
    if approach:
        display_parts.append(approach)
    if complexity:
        display_parts.append(f"Complexity:\n{complexity}")
    if edge:
        display_parts.append(f"Edge cases:\n{edge}")

    full = raw
    if problem and problem.upper() != "NO_PROBLEM":
        full = f"Problem:\n{problem}\n\n{raw}"

    return ParsedResponse(
        is_coding=True,
        approach="\n\n".join(display_parts) or raw,
        code=code,
        complexity=complexity,
        edge_cases=edge,
        full_text=full,
        problem_text=problem if problem.upper() != "NO_PROBLEM" else "",
    )


def parse_vision_response(raw: str) -> tuple[str, ParsedResponse]:
    """Extract problem text and coding response from vision model output."""
    markers = list(_SECTION_RE.finditer(raw))
    problem = ""
    if markers:
        for i, match in enumerate(markers):
            if match.group(1).upper() != "PROBLEM":
                continue
            start = match.end()
            end = markers[i + 1].start() if i + 1 < len(markers) else len(raw)
            problem = raw[start:end].strip()
            break

    parsed = parse_structured_response(raw, is_coding=True)
    if problem and problem.upper() != "NO_PROBLEM":
        parsed.problem_text = problem
    return problem, parsed
