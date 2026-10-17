"""The lesson as text, for a braille display or a screen reader.

The descriptive transcript is what the teacher said and every aired description, in lesson
order: the text alternative that WCAG 1.2.8 (Media Alternative) asks for. It is built here
from the transcript and the script, with no model, so every lesson has one.

The lesson notes come from the desk on Evolus (desk.py): Gemma 4 on AMD writes short,
easy-read notes for the child's age from the transcript, and an Evolus AI Tool translates
them into the other language, for a family or a support teacher who reads it.
"""

from __future__ import annotations

from .asr import Word
from .export import AIRED
from .pipeline import Cue

LABELS = {
    "en": {"title": "Described lesson", "teacher": "Teacher", "screen": "On screen"},
    "it": {"title": "Lezione descritta", "teacher": "Insegnante", "screen": "Sullo schermo"},
}
AGES = {"young": "5-8", "": "8-13", "teen": "14-18"}


def clock(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"


def descriptive_transcript(title: str, audience: str, words: list[Word], cues: list[Cue]) -> str:
    """The teacher's words in paragraphs, each aired description between them where it is heard."""
    labels = LABELS.get(audience[:2], LABELS["en"])
    lines = [f"{labels['title']}: {title}", ""]
    said: list[Word] = []

    def say() -> None:
        if said:
            lines.extend([f"[{clock(said[0].start)}] {labels['teacher']}: " + " ".join(w.text.strip() for w in said), ""])
            said.clear()

    aired = sorted((c for c in cues if c.status in AIRED and c.line), key=lambda c: c.start)
    queue = list(words)
    for cue in aired:
        while queue and queue[0].start < cue.start:
            said.append(queue.pop(0))
        say()
        lines.extend([f"[{clock(cue.start)}] {labels['screen']}: {cue.line}", ""])
    said.extend(queue)
    say()
    return "\n".join(lines).rstrip() + "\n"


def notes_parameters(audience: str) -> dict:
    """What the notes workflow needs to know: the language, the other one, and the age band."""
    language, _, level = audience.partition("-")
    return {"language": language, "other_language": "it" if language == "en" else "en", "age": AGES.get(level, "8-13")}
