"""Transcript cleanup for the legacy WebSocket STT backend.

The active implementation intentionally preserves provider transcripts verbatim.
Keep this module dependency-light so the backend can start without an LLM client.
"""


async def llm_cleaning(context: str, current_text: str) -> str:
    """Return the original transcript without introducing model-generated drift."""
    return current_text
