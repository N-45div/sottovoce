from pathlib import Path

import pytest

from sottovoce.asr import Word, dialogue_around, transcribe

CLIP = Path(r"C:\Users\DivijN\sottovoce-media\tos_bridge_150s.mp4")


def test_dialogue_around_a_pause():
    words = [Word(1.0, 1.5, "Ciao"), Word(2.0, 2.4, "Tom."), Word(9.0, 9.5, "Andiamo.")]
    assert dialogue_around(words, 3.0, 8.5) == ("Ciao Tom.", "Andiamo.")


def test_dialogue_far_from_the_pause_is_left_out():
    words = [Word(0.0, 0.5, "Lontano."), Word(30.0, 30.5, "Dopo.")]
    assert dialogue_around(words, 12.0, 15.0, reach=5.0) == ("", "")


@pytest.mark.skipif(not CLIP.exists(), reason="test clip not downloaded")
def test_real_film_dialogue_is_transcribed_with_timings():
    words = transcribe(CLIP)
    text = " ".join(w.text for w in words).lower()

    assert len(words) > 50
    assert "robot hand" in text
    assert all(w.end >= w.start for w in words)
    assert words == sorted(words, key=lambda w: w.start)
