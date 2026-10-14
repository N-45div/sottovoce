"""Find the moments a teacher points at the screen: "look at this", "guardate", "ecco".

A blind child hears "as you can see, this goes up" and has no idea what "this"
is. Those moments need a description even when the teacher never pauses, so the
video holds right after the sentence and the description says what was shown.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .asr import Word

# Whole phrases, matched on word boundaries in lower case.
PHRASES = (
    # English
    "look at", "look here", "as you can see", "you can see", "see how", "watch this",
    "watch what", "notice", "over here", "right here", "like this", "this one", "these",
    # Italian
    "guardate", "guarda", "guardiamo", "vedete", "come vedete", "potete vedere", "ecco",
    "osservate", "notate", "qui", "questo", "questa", "questi", "queste",
)
_PATTERN = re.compile(r"\b(" + "|".join(re.escape(p) for p in PHRASES) + r")\b")
_END = re.compile(r"[.?!…]$")


@dataclass(frozen=True)
class Moment:
    start: float  # when the pointing sentence began
    end: float  # when it ended: the video holds here
    sentence: str


def sentences(words: list[Word], gap: float = 0.6) -> list[list[Word]]:
    """Group words into sentences: end punctuation, or a silence of `gap` seconds."""
    out: list[list[Word]] = []
    current: list[Word] = []
    for i, word in enumerate(words):
        current.append(word)
        nxt = words[i + 1] if i + 1 < len(words) else None
        if _END.search(word.text) or nxt is None or nxt.start - word.end >= gap:
            out.append(current)
            current = []
    return out


def pointing_moments(words: list[Word], *, min_gap: float = 12.0) -> list[Moment]:
    """Sentences where the teacher points at something, at most one every `min_gap` s."""
    moments: list[Moment] = []
    for sentence in sentences(words):
        text = " ".join(w.text for w in sentence)
        if not _PATTERN.search(re.sub(r"[^\w\s']", " ", text.lower())):
            continue
        if moments and sentence[0].start - moments[-1].end < min_gap:
            continue
        moments.append(Moment(sentence[0].start, sentence[-1].end, text))
    return moments
