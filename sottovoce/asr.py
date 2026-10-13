"""Find when people speak: word timings from faster-whisper, an open Whisper model.

The transcript does two jobs. Its word timings mark the pauses a description
can fill, and its text tells the describer what was said around each pause.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass
from functools import cache
from pathlib import Path

import numpy as np

SAMPLE_RATE = 16_000


@dataclass(frozen=True)
class Word:
    start: float
    end: float
    text: str


@cache
def _model(size: str):
    from faster_whisper import WhisperModel

    return WhisperModel(size, device="cpu", compute_type="int8")


def load_audio(video: Path | str) -> np.ndarray:
    """Decode the soundtrack to 16 kHz mono float samples with ffmpeg."""
    out = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(video), "-vn", "-ac", "1",
         "-ar", str(SAMPLE_RATE), "-f", "f32le", "-"],
        capture_output=True, check=True,
    )
    return np.frombuffer(out.stdout, dtype=np.float32)


def transcribe(video: Path | str, *, size: str = "small", language: str | None = None) -> list[Word]:
    """Return every spoken word with its start and end time, in seconds."""
    segments, _ = _model(size).transcribe(
        load_audio(video), word_timestamps=True, vad_filter=True, language=language
    )
    return [
        Word(round(w.start, 3), round(w.end, 3), w.word.strip())
        for segment in segments
        for w in segment.words or []
        if w.word.strip()
    ]


def transcribe_cached(video: Path | str, **kwargs) -> list[Word]:
    """Transcribe once per video file; later runs read the saved JSON."""
    video = Path(video)
    cache_file = video.with_suffix(".words.json")
    if cache_file.exists() and cache_file.stat().st_mtime >= video.stat().st_mtime:
        return [Word(**w) for w in json.loads(cache_file.read_text(encoding="utf-8"))]
    words = transcribe(video, **kwargs)
    cache_file.write_text(json.dumps([asdict(w) for w in words], ensure_ascii=False), encoding="utf-8")
    return words


def dialogue_around(words: list[Word], start: float, end: float, reach: float = 8.0) -> tuple[str, str]:
    """What was said in the `reach` seconds before a pause, and just after it."""
    before = " ".join(w.text for w in words if start - reach <= w.end <= start)
    after = " ".join(w.text for w in words if end <= w.start <= end + reach)
    return before, after
