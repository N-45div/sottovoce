from sottovoce.voice import speakable


def test_quoted_headline_is_read_as_words():
    assert speakable('Il titolo "ROBOTICIST CREATES KILLER ROBOTS" appare.') == (
        'Il titolo "Roboticist Creates Killer Robots" appare.'
    )


def test_short_words_in_a_capital_title_follow_the_title():
    assert speakable('Compare "TEARS OF STEEL".') == 'Compare "Tears Of Steel".'
    assert speakable("40 YEARS LATER") == "40 Years Later"


def test_acronyms_and_ordinary_sentences_are_left_alone():
    assert speakable("A man watches RAI and AMD news.") == "A man watches RAI and AMD news."
    assert speakable("Un uomo è sul ponte.") == "Un uomo è sul ponte."
