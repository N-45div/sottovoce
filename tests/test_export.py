import json
import subprocess

import numpy as np
import pytest

from sottovoce.export import export, hold_frames, holds, narration, shift, timestamp, to_vtt
from sottovoce.pipeline import Cue, Script
from sottovoce.voice import SAMPLE_RATE, write_wav

from media import CLIP


def tone(seconds: float) -> bytes:
    """A real 440 Hz signal standing in for a spoken line."""
    t = np.arange(int(seconds * SAMPLE_RATE)) / SAMPLE_RATE
    return write_wav((np.sin(2 * np.pi * 440 * t) * 8000).astype(np.int16))


def test_timestamp():
    assert timestamp(3725.5) == "01:02:05.500"
    assert timestamp(0.0) == "00:00:00.000"


def test_vtt_has_one_cue_per_spoken_line_ending_when_the_voice_ends():
    cues = [Cue(1.0, 6.0, 12, [], line="Un ponte.", seconds=2.25), Cue(8.0, 9.0, 3, [])]
    assert to_vtt(cues) == "WEBVTT\n\n1\n00:00:01.000 --> 00:00:03.250\nUn ponte.\n"


def test_narration_places_each_line_at_its_cue(tmp_path):
    (tmp_path / "a.wav").write_bytes(tone(1.0))
    track = narration([Cue(2.0, 4.0, 5, [], audio="a.wav", seconds=1.0)], tmp_path, total=5.0)

    assert len(track) == 5 * SAMPLE_RATE + 1
    assert not track[: 2 * SAMPLE_RATE].any()
    assert track[2 * SAMPLE_RATE : 3 * SAMPLE_RATE].any()
    assert not track[3 * SAMPLE_RATE + 10 :].any()


def test_a_line_running_past_the_end_is_cut_not_crashed(tmp_path):
    (tmp_path / "a.wav").write_bytes(tone(3.0))
    track = narration([Cue(4.0, 5.0, 3, [], audio="a.wav", seconds=3.0)], tmp_path, total=5.0)
    assert len(track) == 5 * SAMPLE_RATE + 1


@pytest.mark.skipif(not CLIP.exists(), reason="test clip not downloaded")
def test_export_mixes_a_real_clip(tmp_path):
    clip = tmp_path / "clip.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-t", "20", "-i", str(CLIP), "-c", "copy", str(clip)], check=True)
    (tmp_path / "audio").mkdir()
    (tmp_path / "audio" / "cue_000.wav").write_bytes(tone(2.0))
    cue = Cue(12.0, 15.0, 7, [12.5], line="I motori del razzo.", audio="cue_000.wav", seconds=2.0)
    files = export(Script(str(clip), "it", 20.0, [cue]), tmp_path)

    probe = json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type",
         "-of", "json", str(files["video"])],
        capture_output=True, text=True, check=True,
    ).stdout)
    assert {s["codec_type"] for s in probe["streams"]} == {"video", "audio"}
    assert float(probe["format"]["duration"]) == pytest.approx(20.0, abs=0.2)
    assert "I motori del razzo." in files["vtt"].read_text(encoding="utf-8")
    assert files["narration"].stat().st_size > 20 * SAMPLE_RATE * 2


def test_only_lines_longer_than_their_pause_hold_the_picture():
    cues = [
        Cue(2.0, 4.0, 5, [], audio="a.wav", seconds=1.5),
        Cue(10.0, 12.0, 5, [], audio="b.wav", seconds=5.0),
        Cue(20.0, 21.0, 5, []),
    ]
    assert holds(cues) == [(12.0, 3.3)]


def test_times_after_a_hold_move_later_by_its_length():
    held = [(12.0, 3.3), (30.0, 1.0)]
    assert shift(5.0, held) == 5.0
    assert shift(12.0, held) == 15.3
    assert shift(40.0, held) == 44.3


@pytest.mark.skipif(not CLIP.exists(), reason="test clip not downloaded")
def test_held_video_grows_by_the_holds(tmp_path):
    out = tmp_path / "held.mp4"
    hold_frames(CLIP, [(3.0, 2.0), (6.0, 1.5)], 8.0, out)
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(out)],
        capture_output=True, text=True, check=True,
    )
    assert float(probe.stdout) == pytest.approx(8.0 + 2.0 + 1.5, abs=0.15)
