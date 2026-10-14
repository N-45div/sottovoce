
import pytest

from sottovoce.asr import transcribe_cached
from sottovoce.gaps import speech_spans
from sottovoce.pipeline import Cue, Script, plan
from sottovoce.shots import duration

from media import CLIP


def test_script_survives_a_json_round_trip():
    script = Script("film.mp4", "it", 12.0, [Cue(1.0, 4.0, 7, [1.5], line="Un ponte.")], {"plan": 0.1})
    assert Script.from_json(script.to_json()) == script


@pytest.mark.skipif(not CLIP.exists(), reason="test clip not downloaded")
def test_plan_on_the_real_film_never_talks_over_dialogue():
    total = duration(CLIP)
    words = transcribe_cached(CLIP)
    cues = plan(CLIP, words, total)
    speech = speech_spans([(w.start, w.end) for w in words])

    pauses = [c for c in cues if not c.focus]
    assert len(pauses) >= 8
    for cue in cues:
        assert 0.0 <= cue.start < cue.end <= total
        assert cue.words >= 3
        assert cue.frames
    for cue in pauses:  # a pause cue never talks over dialogue
        assert all(cue.end <= s.start or cue.start >= s.end for s in speech)
        assert all(cue.start - 1.0 <= t <= cue.end for t in cue.frames)
    for cue in cues:  # a pointing cue starts once the teacher's sentence has ended
        if cue.focus:
            assert any(abs(w.end - cue.start) < 0.05 for w in words)
    assert all(a.end <= b.start for a, b in zip(cues, cues[1:]))


@pytest.mark.skipif(not CLIP.exists(), reason="test clip not downloaded")
def test_a_pause_whose_models_all_fail_goes_to_a_person(tmp_path):
    import asyncio

    from sottovoce.describe import Endpoint, Settings
    from sottovoce.pipeline import write_lines

    # A real request to a server that is not there: no model can answer.
    dead = Endpoint("Gemma-4-31B-IT", "http://127.0.0.1:9/v1", "k")
    cue = Cue(10.0, 13.0, 7, [11.0])
    asyncio.run(write_lines(CLIP, [cue], "it", settings=Settings(dead, dead)))

    assert cue.status == "needs_review"
    assert cue.line == ""
    assert cue.history[0]["problems"][0].startswith("no model answered")


def test_a_line_too_long_for_its_pause_goes_to_a_person():
    from sottovoce.pipeline import record_speech
    from sottovoce.voice import Speech

    cue = Cue(10.0, 13.0, 7, [11.0], line="Una riga lunga.", status="verified")
    record_speech(cue, Speech(b"", 4.2, 1.1, False))

    assert cue.status == "needs_review"
    assert cue.history[-1]["problems"] == ["spoken in 4.2 s, the pause is 3.0 s"]


def test_a_line_that_fits_keeps_its_status():
    from sottovoce.pipeline import record_speech
    from sottovoce.voice import Speech

    cue = Cue(10.0, 13.0, 7, [11.0], line="Breve.", status="verified")
    record_speech(cue, Speech(b"", 1.5, 1.0, True))
    assert cue.status == "verified"
    assert cue.history == []


def test_a_pointing_sentence_gets_a_cue_unless_a_pause_follows_it():
    from sottovoce.asr import Word
    from sottovoce.gaps import Span
    from sottovoce.pipeline import POINT_DELAY, pointing_cues

    words = [Word(10.0, 10.4, "Look"), Word(10.5, 10.6, "at"), Word(10.7, 11.2, "this."), Word(11.3, 12.0, "Next.")]
    shots = [Span(0.0, 30.0)]

    [cue] = pointing_cues(words, shots, [])
    assert cue.start == pytest.approx(11.2 + POINT_DELAY)
    assert cue.focus == "Look at this."
    assert all(10.0 <= t <= 12.2 for t in cue.frames)

    pause_right_after = Cue(11.5, 14.0, 7, [12.0])
    assert pointing_cues(words, shots, [pause_right_after]) == []
