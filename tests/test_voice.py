"""Live tests against Google Cloud Text-to-Speech. Skipped without GOOGLE_CLOUD_PROJECT."""

import os

import pytest

from sottovoce.voice import MAX_SPEEDUP, speak_within, wav_seconds

pytestmark = pytest.mark.skipif(
    not os.environ.get("GOOGLE_CLOUD_PROJECT"), reason="needs Google Cloud credentials"
)

LINE = "Un uomo e una donna si fronteggiano su un ponte di ferro."


def test_line_that_fits_is_spoken_at_normal_speed():
    speech = speak_within(LINE, limit=10.0)

    assert speech.fits
    assert speech.rate == 1.0
    assert 2.0 < speech.seconds < 10.0
    assert wav_seconds(speech.wav) == pytest.approx(speech.seconds)


def test_tight_pause_fits_or_is_flagged_honestly():
    # The voice varies take to take, so check what must always hold.
    natural = speak_within(LINE, limit=30.0).seconds
    limit = natural * 0.9
    speech = speak_within(LINE, limit=limit)

    assert 1.0 <= speech.rate <= MAX_SPEEDUP
    assert speech.fits == (speech.seconds <= limit)
    assert speech.fits or speech.rate == MAX_SPEEDUP


def test_impossible_pause_is_flagged_not_hidden():
    speech = speak_within(LINE, limit=1.0)

    assert not speech.fits
    assert speech.seconds > 1.0
    assert speech.rate == MAX_SPEEDUP


def test_english_voice():
    speech = speak_within("A man and a woman face each other on a bridge.", limit=10.0, audience="en")
    assert speech.fits


def test_padding_is_trimmed_but_words_are_kept():
    import numpy as np

    from sottovoce.voice import read_pcm, synthesize

    samples = read_pcm(synthesize(LINE))
    edge = int(0.04 * 24_000)
    assert np.abs(samples[:edge]).max() < 2000
    assert np.abs(samples).max() > 5000
