"""The lesson as text: the teacher's words and the aired lines, in the order a child hears them."""

from sottovoce.asr import Word
from sottovoce.notes import descriptive_transcript, notes_parameters
from sottovoce.pipeline import Cue


def said(*timed):
    return [Word(t, t + 0.4, text) for t, text in timed]


def cue(start, line, status="verified"):
    return Cue(start=start, end=start + 1, words=10, frames=[start], line=line, status=status)


def test_each_line_sits_between_the_words_said_before_and_after_it():
    words = said((1.0, "Look"), (1.5, "at"), (2.0, "this."), (6.0, "It"), (6.5, "is"), (7.0, "round."))
    text = descriptive_transcript("Moon Phases", "en", words, [cue(3.0, "A white ball on a stick.")])
    assert text.splitlines() == [
        "Described lesson: Moon Phases", "",
        "[00:01] Teacher: Look at this.", "",
        "[00:03] On screen: A white ball on a stick.", "",
        "[00:06] Teacher: It is round.",
    ]


def test_only_lines_a_child_heard_are_in_it():
    text = descriptive_transcript("Area", "it", said((0.5, "Guardate.")), [
        cue(1.0, "Un cubo blu."), cue(2.0, "A wrong claim.", status="needs_review"), cue(3.0, "", status="skipped"),
    ])
    assert "Un cubo blu." in text and "wrong claim" not in text
    assert text.startswith("Lezione descritta: Area") and "Sullo schermo:" in text


def test_a_lesson_that_opens_with_a_picture_starts_with_its_line():
    text = descriptive_transcript("Moon", "en", said((5.0, "Hello.")), [cue(0.0, "The word STEM.")])
    assert text.splitlines()[2] == "[00:00] On screen: The word STEM."


def test_the_notes_are_asked_for_in_the_lessons_language_and_age_and_translated_into_the_other():
    assert notes_parameters("en-young") == {"language": "en", "other_language": "it", "age": "5-8"}
    assert notes_parameters("it") == {"language": "it", "other_language": "en", "age": "8-13"}
    assert notes_parameters("it-teen") == {"language": "it", "other_language": "en", "age": "14-18"}
