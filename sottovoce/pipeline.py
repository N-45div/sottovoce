"""From a video file to a voiced audio-description script.

1. Transcribe the dialogue and find the pauses (CPU, faster-whisper).
2. Find the shots and pick keyframes for each pause (ffmpeg).
3. Write and check a line for every pause (two vision models on AMD
   Token Factory, run through Google ADK), a few pauses at a time.
4. Voice each line to fit its pause (Google Cloud Text-to-Speech).
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .asr import Word, dialogue_around, transcribe_cached
from .audiences import AUDIENCES
from .describe import Settings, describe_gap
from .gaps import find_gaps, speech_spans, split_long
from .pointing import pointing_moments
from .shots import detect_cuts, duration, extract_frame, frame_times, is_black, shots_from_cuts
from .voice import Speech, speak_within

# Word budget per second of pause. The trimmed it-IT Chirp 3 HD voice speaks about
# 3.5 words a second; budgeting 2.8 leaves room to breathe, and the voice step
# measures the real length of every line anyway.
WORDS_PER_SECOND = 2.8


@dataclass
class Cue:
    start: float
    end: float
    words: int
    frames: list[float]
    before: str = ""
    after: str = ""
    line: str = ""
    status: str = "pending"
    claims: list[dict] = field(default_factory=list)
    history: list[dict] = field(default_factory=list)
    tokens: dict[str, list[int]] = field(default_factory=dict)
    seconds: float = 0.0
    rate: float = 1.0
    fits: bool = True
    audio: str = ""
    focus: str = ""  # what the teacher said while pointing, for a pointing cue


@dataclass
class Script:
    video: str
    audience: str
    duration: float
    cues: list[Cue]
    timings: dict[str, float] = field(default_factory=dict)
    models: dict[str, str] = field(default_factory=dict)  # agent -> model that ran it

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, text: str) -> Script:
        data = json.loads(text)
        data["cues"] = [Cue(**c) for c in data["cues"]]
        return cls(**data)


EXTENDED_WORDS = 22  # the picture waits for the line, so it can say more
# A pointing cue sits just after the teacher's sentence: a short delay so no word
# is clipped, and a tiny window, because the picture holds there anyway.
POINT_DELAY = 0.02
POINT_WINDOW = 0.04


def plan(video: Path | str, words: list[Word], total: float, audience: str = "it") -> list[Cue]:
    """Decide where descriptions go and which frames each one looks at."""
    speech = speech_spans([(w.start, w.end) for w in words])
    gaps = split_long(
        find_gaps(speech, total, words_per_second=WORDS_PER_SECOND),
        words_per_second=WORDS_PER_SECOND,
    )
    shots = shots_from_cuts(detect_cuts(video), total)
    extended = AUDIENCES[audience].extended
    cues = []
    for gap in gaps:
        before, after = dialogue_around(words, gap.start, gap.end)
        times = frame_times(shots, gap.start, gap.end)
        budget = max(gap.words, EXTENDED_WORDS) if extended else gap.words
        cues.append(Cue(gap.start, gap.end, budget, times, before, after))
    if extended:
        cues += pointing_cues(words, shots, cues)
    return sorted(cues, key=lambda c: c.start)


def pointing_cues(words: list[Word], shots, gap_cues: list[Cue]) -> list[Cue]:
    """A cue right after every sentence where the teacher points at the screen.

    The cue is a sliver of time just after the sentence ends; the picture holds
    there while the line is spoken. Its frames come from the sentence itself,
    which is when the thing being pointed at is on screen. A pointing sentence
    already followed by a pause is described in that pause instead.
    """
    out = []
    for moment in pointing_moments(words):
        if any(-0.5 <= c.start - moment.end <= 2.0 for c in gap_cues):
            continue
        at = moment.end + POINT_DELAY
        times = frame_times(shots, moment.start, moment.end + 1.0, lead=0.0)
        before, after = dialogue_around(words, moment.start, at)
        out.append(Cue(at, at + POINT_WINDOW, EXTENDED_WORDS, times, before, after, focus=moment.sentence))
    return out


async def write_lines(
    video: Path | str,
    cues: list[Cue],
    audience: str,
    *,
    settings: Settings | None = None,
    concurrency: int = 3,
    on_cue: Callable[[int, Cue], None] | None = None,
) -> None:
    """Write and check a line for every cue, `concurrency` cues at a time."""
    settings = settings or Settings.from_env()
    gate = asyncio.Semaphore(concurrency)

    async def one(i: int, cue: Cue) -> None:
        dark = await asyncio.gather(*(asyncio.to_thread(is_black, video, t) for t in cue.frames))
        cue.frames = [t for t, black in zip(cue.frames, dark) if not black]
        if not cue.frames:
            cue.status = "skipped"  # only black on screen: nothing to describe
            if on_cue:
                on_cue(i, cue)
            return
        try:
            async with gate:
                frames = await asyncio.gather(*(asyncio.to_thread(extract_frame, video, t) for t in cue.frames))
                result = await describe_gap(
                    list(frames), cue.words, audience,
                    before=cue.before, after=cue.after, focus=cue.focus, settings=settings,
                )
        except Exception as e:  # noqa: BLE001 - one pause failing must not sink the video
            # Every model for this pause failed even after the backups; a person
            # writes the line in the editor instead.
            cue.status = "needs_review"
            cue.history = [{"round": 0, "line": "", "problems": [f"no model answered: {type(e).__name__}"]}]
        else:
            cue.line, cue.status = result.line, result.status
            cue.claims, cue.history, cue.tokens = result.claims, result.history, result.tokens
        if on_cue:
            on_cue(i, cue)

    await asyncio.gather(*(one(i, c) for i, c in enumerate(cues)))


def voice_lines(cues: list[Cue], audience: str, out_dir: Path) -> None:
    """Speak every written line into `out_dir`, fitted to its pause.

    Extended description holds the picture instead, so its lines are spoken at
    their natural pace however long they run.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    extended = AUDIENCES[audience].extended

    def one(i: int, cue: Cue) -> None:
        if not cue.line:
            return
        limit = 60.0 if extended else cue.end - cue.start
        speech = speak_within(cue.line, limit, audience)
        cue.audio = cue.audio or f"cue_{i:03d}.wav"
        (out_dir / cue.audio).write_bytes(speech.wav)
        record_speech(cue, speech)

    with ThreadPoolExecutor(4) as pool:
        list(pool.map(one, range(len(cues)), cues))


def record_speech(cue: Cue, speech: Speech) -> None:
    """Store how the line was spoken. A line that runs over its pause would talk
    over the next dialogue, so it goes to a person to shorten."""
    cue.seconds, cue.rate, cue.fits = round(speech.seconds, 3), speech.rate, speech.fits
    if not speech.fits:
        cue.status = "needs_review"
        cue.history = [*cue.history, {
            "round": len(cue.history) + 1,
            "line": cue.line,
            "problems": [f"spoken in {speech.seconds:.1f} s, the pause is {cue.end - cue.start:.1f} s"],
        }]


async def describe_video(
    video: Path | str,
    out_dir: Path | str,
    audience: str = "it",
    *,
    settings: Settings | None = None,
    concurrency: int = 3,
    on_cue: Callable[[int, Cue], None] | None = None,
) -> Script:
    """Run every stage and save the script next to the voiced lines."""
    video, out_dir = Path(video), Path(out_dir)
    settings = settings or Settings.from_env()
    timings: dict[str, float] = {}

    t = time.perf_counter()
    total = duration(video)
    words = await asyncio.to_thread(transcribe_cached, video)
    timings["transcribe"] = time.perf_counter() - t

    t = time.perf_counter()
    cues = await asyncio.to_thread(plan, video, words, total, audience)
    timings["plan"] = time.perf_counter() - t

    t = time.perf_counter()
    await write_lines(video, cues, audience, settings=settings, concurrency=concurrency, on_cue=on_cue)
    timings["describe"] = time.perf_counter() - t

    t = time.perf_counter()
    await asyncio.to_thread(voice_lines, cues, audience, out_dir / "audio")
    timings["voice"] = time.perf_counter() - t

    script = Script(
        str(video), audience, total, cues,
        timings={k: round(v, 2) for k, v in timings.items()},
        models={"describer": settings.describer.model, "verifier": settings.verifier.model},
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "script.json").write_text(script.to_json(), encoding="utf-8")
    return script
