from sottovoce.asr import Word
from sottovoce.pointing import pointing_moments, sentences


def words(*items):
    """(start, end, text) triples to Words."""
    return [Word(s, e, t) for s, e, t in items]


LESSON = words(
    (0.0, 0.4, "Today"), (0.5, 0.9, "we"), (1.0, 1.5, "study"), (1.6, 2.2, "plants."),
    (2.4, 2.8, "Look"), (2.9, 3.0, "at"), (3.1, 3.5, "this"), (3.6, 4.2, "leaf."),
    (4.4, 4.8, "It"), (4.9, 5.4, "breathes."),
)


def test_words_are_grouped_into_sentences_at_full_stops():
    assert [len(s) for s in sentences(LESSON)] == [4, 4, 2]


def test_a_long_silence_also_ends_a_sentence():
    split = sentences(words((0.0, 0.5, "so"), (2.0, 2.4, "then")))
    assert [len(s) for s in split] == [1, 1]


def test_the_teacher_pointing_is_found_and_ends_where_the_sentence_ends():
    [moment] = pointing_moments(LESSON)
    assert moment.start == 2.4
    assert moment.end == 4.2
    assert moment.sentence == "Look at this leaf."


def test_italian_pointing_is_found():
    lesson = words((0.0, 0.5, "Guardate"), (0.6, 1.0, "il"), (1.1, 1.8, "grafico."))
    assert [m.sentence for m in pointing_moments(lesson)] == ["Guardate il grafico."]


def test_pointing_is_matched_on_whole_words():
    lesson = words((0.0, 0.5, "Theseus"), (0.6, 1.0, "sailed."), (1.2, 1.6, "Quindi"), (1.7, 2.0, "basta."))
    assert pointing_moments(lesson) == []


def test_pointing_moments_are_spaced_out():
    lesson = words(
        (0.0, 1.0, "Look at this."), (2.0, 3.0, "And this one."), (20.0, 21.0, "Now look here."),
    )
    assert [m.start for m in pointing_moments(lesson, min_gap=12.0)] == [0.0, 20.0]
