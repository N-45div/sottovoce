"""Find the pauses in the dialogue where a description can be spoken.

A description must never talk over a line of dialogue. It starts a moment
after a line ends and finishes a moment before the next one begins. Its
length is capped by a word budget derived from the voice's speaking rate.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Span:
    """A stretch of continuous speech, in seconds."""

    start: float
    end: float

    @property
    def length(self) -> float:
        return self.end - self.start


@dataclass(frozen=True)
class Gap:
    """A pause that can hold a description of up to `words` words."""

    start: float
    end: float
    words: int

    @property
    def length(self) -> float:
        return self.end - self.start


def speech_spans(words: list[tuple[float, float]], join_under: float = 0.35) -> list[Span]:
    """Merge word timestamps into spans of continuous speech.

    Words less than `join_under` seconds apart belong to the same span, so a
    breath inside a sentence never counts as a pause.
    """
    spans: list[Span] = []
    for start, end in sorted(words):
        if end < start:
            raise ValueError(f"word ends before it starts: {start}-{end}")
        if spans and start - spans[-1].end < join_under:
            last = spans[-1]
            spans[-1] = Span(last.start, max(last.end, end))
        else:
            spans.append(Span(start, end))
    return spans


def find_gaps(
    speech: list[Span],
    duration: float,
    *,
    words_per_second: float = 2.5,
    after_speech: float = 0.25,
    before_speech: float = 0.35,
    min_words: int = 3,
) -> list[Gap]:
    """Return the pauses long enough to hold at least `min_words` words.

    A description starts `after_speech` seconds after a line ends and must
    finish `before_speech` seconds before the next line starts. The start
    and the end of the video need no padding.
    """
    if duration < 0:
        raise ValueError(f"duration must not be negative: {duration}")
    if words_per_second <= 0:
        raise ValueError(f"words_per_second must be positive: {words_per_second}")

    gaps: list[Gap] = []
    spoken_until: float | None = None
    for span in [*sorted(speech, key=lambda s: s.start), None]:
        start = 0.0 if spoken_until is None else spoken_until + after_speech
        end = duration if span is None else span.start - before_speech
        start, end = max(start, 0.0), min(end, duration)
        words = int((end - start) * words_per_second) if end > start else 0
        if words >= min_words:
            gaps.append(Gap(round(start, 3), round(end, 3), words))
        if span is not None:
            spoken_until = span.end if spoken_until is None else max(spoken_until, span.end)
    return gaps


def split_long(
    gaps: list[Gap],
    *,
    max_len: float = 10.0,
    rest: float = 1.5,
    words_per_second: float = 2.5,
    min_words: int = 3,
) -> list[Gap]:
    """Split pauses longer than `max_len` into shorter ones.

    A long silent scene is then described as it unfolds, not in one sentence
    at its start. Every piece but the last ends with `rest` seconds of quiet,
    so the narration never runs wall to wall.
    """
    out: list[Gap] = []
    for gap in gaps:
        if gap.length <= max_len:
            out.append(gap)
            continue
        n = math.ceil(gap.length / max_len)
        step = gap.length / n
        for i in range(n):
            start = gap.start + i * step
            end = gap.start + (i + 1) * step - (rest if i < n - 1 else 0.0)
            words = int((end - start) * words_per_second)
            if words >= min_words:
                out.append(Gap(round(start, 3), round(end, 3), words))
    return out
