"""Word timestamp generation and interval-based speaker assignment."""

from __future__ import annotations

import re

from .models import SpeakerSegment, SpeakerWordGroup, TranscriptSegment, WordTimestamp

_WORD_RE = re.compile(r"\S+")


class WordAligner:
    """Associates transcript words with time and speaker intervals."""

    def align_words(self, transcript: TranscriptSegment) -> tuple[WordTimestamp, ...]:
        if transcript.words:
            return transcript.words
        matches = list(_WORD_RE.finditer(transcript.text))
        if not matches:
            return ()
        duration = max(0.05, transcript.end - transcript.start)
        step = duration / len(matches)
        words: list[WordTimestamp] = []
        for index, match in enumerate(matches):
            start = transcript.start + index * step
            end = transcript.start + (index + 1) * step
            words.append(
                WordTimestamp(
                    word=match.group(0),
                    start=start,
                    end=end,
                    confidence=transcript.confidence,
                )
            )
        return tuple(words)

    def assign_speakers(
        self,
        words: tuple[WordTimestamp, ...],
        speaker_segments: tuple[SpeakerSegment, ...],
    ) -> tuple[SpeakerWordGroup, ...]:
        groups: list[SpeakerWordGroup] = []
        current_speaker = ""
        current_words: list[WordTimestamp] = []
        current_confidences: list[float] = []

        for word in words:
            speaker, confidence = self._best_speaker_for_word(word, speaker_segments)
            if speaker != current_speaker and current_words:
                groups.append(
                    SpeakerWordGroup(
                        speaker=current_speaker,
                        words=tuple(current_words),
                        confidence=_avg(current_confidences),
                    )
                )
                current_words = []
                current_confidences = []
            current_speaker = speaker
            current_words.append(word)
            if confidence is not None:
                current_confidences.append(confidence)

        if current_words:
            groups.append(
                SpeakerWordGroup(
                    speaker=current_speaker or "SPEAKER_00",
                    words=tuple(current_words),
                    confidence=_avg(current_confidences),
                )
            )
        return tuple(groups)

    def _best_speaker_for_word(
        self,
        word: WordTimestamp,
        speaker_segments: tuple[SpeakerSegment, ...],
    ) -> tuple[str, float | None]:
        best: SpeakerSegment | None = None
        best_overlap = 0.0
        for segment in speaker_segments:
            overlap = max(0.0, min(word.end, segment.end) - max(word.start, segment.start))
            if overlap > best_overlap:
                best_overlap = overlap
                best = segment
        if best is None:
            return "SPEAKER_00", 0.25
        return best.speaker, best.confidence


def _avg(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None

