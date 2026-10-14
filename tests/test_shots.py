
import pytest

from sottovoce.gaps import Span
from sottovoce.shots import detect_cuts, duration, extract_frame, frame_times, shots_from_cuts

from media import CLIP
needs_clip = pytest.mark.skipif(not CLIP.exists(), reason="test clip not downloaded")


def test_cuts_become_shots_covering_the_video():
    assert shots_from_cuts([4.0, 9.5], 12.0) == [Span(0.0, 4.0), Span(4.0, 9.5), Span(9.5, 12.0)]


def test_cuts_outside_the_video_are_ignored():
    assert shots_from_cuts([0.0, 20.0], 12.0) == [Span(0.0, 12.0)]


def test_one_long_shot_gets_two_frames():
    assert frame_times([Span(0.0, 30.0)], 10.0, 13.0) == [10.33, 11.67]


def test_each_shot_in_the_window_gets_its_middle_frame():
    shots = [Span(0.0, 10.0), Span(10.0, 12.0), Span(12.0, 30.0)]
    assert frame_times(shots, 9.0, 14.0) == [9.0, 11.0, 13.0]


def test_too_many_shots_are_thinned_keeping_the_last():
    shots = [Span(float(i), float(i + 1)) for i in range(10)]
    times = frame_times(shots, 1.0, 10.0, max_frames=4)
    assert len(times) == 4
    assert times[-1] == 9.5


@needs_clip
def test_real_clip_has_cuts_and_frames():
    total = duration(CLIP)
    cuts = detect_cuts(CLIP)
    shots = shots_from_cuts(cuts, total)

    assert 149 < total < 151
    assert len(cuts) >= 5
    assert shots[0].start == 0.0
    assert shots[-1].end == total

    jpeg = extract_frame(CLIP, 20.0)
    assert jpeg[:2] == b"\xff\xd8"
    assert len(jpeg) > 10_000
