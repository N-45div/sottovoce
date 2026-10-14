
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

    assert len(cues) >= 8
    for cue in cues:
        assert 0.0 <= cue.start < cue.end <= total
        assert cue.words >= 3
        assert all(cue.end <= s.start or cue.start >= s.end for s in speech)
        assert cue.frames
        assert all(cue.start - 1.0 <= t <= cue.end for t in cue.frames)
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
