"""Find the shot changes in a video and pick the keyframes for each pause.

The describer must see what is on screen while a description is spoken, and
a moment before it. A pause can span several shots, so it gets one keyframe
from each shot it touches, capped so the request stays small.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from .gaps import Span

_PTS = re.compile(r"pts_time:([0-9.]+)")


def duration(video: Path | str) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video)],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def detect_cuts(video: Path | str, threshold: float = 0.3) -> list[float]:
    """Return the times where the picture changes enough to count as a new shot."""
    out = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-i", str(video), "-an",
            "-vf", f"select='gt(scene,{threshold})',showinfo", "-f", "null", "-",
        ],
        capture_output=True, text=True, check=True,
    )
    return sorted({round(float(m), 3) for m in _PTS.findall(out.stderr)})


def shots_from_cuts(cuts: list[float], total: float) -> list[Span]:
    """Turn cut times into shots that cover the whole video."""
    edges = [0.0, *(c for c in sorted(cuts) if 0.0 < c < total), total]
    return [Span(a, b) for a, b in zip(edges, edges[1:]) if b > a]


def frame_times(
    shots: list[Span],
    start: float,
    end: float,
    *,
    lead: float = 1.0,
    max_frames: int = 4,
) -> list[float]:
    """Times to sample for a pause: the middle of each shot it touches.

    The window opens `lead` seconds before the pause, so the describer sees
    what led into it. A single long shot gets two frames, to show movement.
    """
    w0, w1 = max(0.0, start - lead), end
    if w1 <= w0:
        return []
    parts = [(max(s.start, w0), min(s.end, w1)) for s in shots if s.end > w0 and s.start < w1]
    if len(parts) == 1:
        a, b = parts[0]
        times = [a + (b - a) / 3, a + 2 * (b - a) / 3]
    else:
        times = [(a + b) / 2 for a, b in parts]
    if len(times) > max_frames:
        # Keep evenly spaced frames and always the last one, which is closest to the words.
        step = (len(times) - 1) / (max_frames - 1)
        times = [times[round(i * step)] for i in range(max_frames)]
    return [round(t, 2) for t in times]


def extract_frame(video: Path | str, at: float, width: int = 768) -> bytes:
    """Return one JPEG frame at `at` seconds, scaled to `width` pixels wide."""
    out = subprocess.run(
        [
            "ffmpeg", "-v", "error", "-ss", f"{at:.3f}", "-i", str(video),
            "-frames:v", "1", "-vf", f"scale={width}:-2", "-q:v", "3",
            "-f", "image2pipe", "-vcodec", "mjpeg", "-",
        ],
        capture_output=True, check=True,
    )
    return out.stdout


def is_black(video: Path | str, at: float, *, ceiling: int = 40) -> bool:
    """Whether the frame at `at` seconds is black: no pixel brighter than `ceiling`.

    A pause that opens on black gave the describer two black frames, and it
    answered "Please provide the keyframes", so black frames are dropped first.
    The brightest pixel decides, not the average: a small white title on black
    averages 16.8 against 15.3 for pure black.
    """
    out = subprocess.run(
        [
            "ffmpeg", "-v", "error", "-ss", f"{at:.3f}", "-i", str(video),
            "-frames:v", "1", "-vf", "scale=128:-2,format=gray", "-f", "rawvideo", "-",
        ],
        capture_output=True, check=True,
    )
    return not out.stdout or max(out.stdout) <= ceiling
