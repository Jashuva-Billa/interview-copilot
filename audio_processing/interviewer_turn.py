"""Accept final interviewer turns from streaming and snapshot transcription."""

import re
from time import monotonic

from .audio_capture import partial_indicates_unfinished

_FILLER = {
    "ah", "alright", "bye", "goodbye", "hello", "hey", "hi", "hmm",
    "mm", "no", "okay", "ok", "right", "sure", "thanks", "thank", "uh",
    "um", "yeah", "yes", "you",
}
_NOISE_LABEL = r"(?:noise|music|silence|inaudible|background noise|applause)"
_NOISE = re.compile(rf"\[{_NOISE_LABEL}\]|\({_NOISE_LABEL}\)", re.I)


class InterviewerTurn:
    def __init__(self) -> None:
        self._fragment = ""
        self._fragment_at = 0.0
        self._last_answered = ""
        self._answered_at = 0.0

    def accept(self, text: str, *, now: float | None = None) -> str:
        now = monotonic() if now is None else now
        text = " ".join(_NOISE.sub(" ", text).split())
        words = re.findall(r"\w+", text.casefold())
        if not words or set(words) <= _FILLER:
            return ""
        if self._fragment and now - self._fragment_at <= 8:
            if not text.casefold().startswith(self._fragment.casefold()):
                text = f"{self._fragment.rstrip('.,;')} {text}"
        self._fragment = ""
        if partial_indicates_unfinished(text):
            self._fragment, self._fragment_at = text, now
            return ""
        key = " ".join(re.findall(r"\w+", text.casefold()))
        if key == self._last_answered and now - self._answered_at <= 4:
            return ""
        self._last_answered, self._answered_at = key, now
        return text
