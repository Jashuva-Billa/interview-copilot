"""Prompt construction for finalized interviewer questions."""

from __future__ import annotations

INTERVIEW_COPILOT_PROMPT = """You are an interview copilot.

The following is a question asked by the interviewer.

Generate a concise, technically accurate answer suitable for speaking during a real interview.

Use the candidate's known experience when relevant.

Do not invent projects, technologies, metrics, responsibilities, or experience.

Prefer a 30-90 second answer unless the question requires more detail.

For technical questions:
- explain the architecture
- mention relevant technologies
- explain why they were used
- mention trade-offs where useful
- include production considerations

For behavioral questions:
- use STAR structure where appropriate

For coding questions:
- explain approach first
- provide concise implementation guidance
- mention complexity

Question:
{question}

Recent context:
{context}

Candidate context:
{candidate_context}
"""


def build_interview_user_prompt(
    *,
    question: str,
    conversation: list[dict],
    candidate_context: str,
    max_turns: int = 5,
) -> str:
    recent = []
    for turn in conversation[-max_turns:]:
        role = "Candidate" if turn.get("role") == "assistant" else "Interviewer"
        content = str(turn.get("content", "")).strip()
        if content:
            recent.append(f"{role}: {content}")
    return INTERVIEW_COPILOT_PROMPT.format(
        question=question,
        context="\n".join(recent) or "(No recent context)",
        candidate_context=candidate_context or "(No candidate context loaded)",
    )

