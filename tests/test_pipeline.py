
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
