"""Turn a voiced script into files people use: a mixed MP4, a narration track, WebVTT."""

from __future__ import annotations

import subprocess
from dataclasses import replace
from pathlib import Path

import numpy as np

from .audiences import AUDIENCES
from .pipeline import Cue, Script
from .voice import SAMPLE_RATE, read_pcm, write_wav

# Measured on Tears of Steel: the rocket launch averages -8.3 dB and the voice -20 dB.
# Ducking by 10 dB left the voice under the bed, so duck by 14 dB and lift the
# voice 6 dB through a limiter.
DUCK = 0.2
VOICE_GAIN_DB = 6


def timestamp(seconds: float) -> str:
    ms = round(seconds * 1000)
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def to_vtt(cues: list[Cue]) -> str:
    """A WebVTT track for <track kind="descriptions">, one cue per spoken line."""
    out = ["WEBVTT", ""]
    for n, cue in enumerate((c for c in cues if c.line), start=1):
        end = cue.start + (cue.seconds or cue.end - cue.start)
        out += [str(n), f"{timestamp(cue.start)} --> {timestamp(end)}", cue.line, ""]
    return "\n".join(out)


def narration(cues: list[Cue], audio_dir: Path, total: float) -> np.ndarray:
    """Every voiced line placed at its cue time on one silent track."""
    track = np.zeros(int(total * SAMPLE_RATE) + 1, dtype=np.int32)
    for cue in cues:
        if not cue.audio:
            continue
        samples = read_pcm((audio_dir / cue.audio).read_bytes())
        at = int(cue.start * SAMPLE_RATE)
        part = samples[: max(0, len(track) - at)]
        track[at : at + len(part)] += part
    return np.clip(track, -32768, 32767).astype(np.int16)


def mix(video: Path, narration_wav: Path, cues: list[Cue], out: Path, duck: float = DUCK) -> None:
    """Lower the programme under each line and lay the narration on top."""
    windows = [(c.start, c.start + c.seconds) for c in cues if c.audio]
    under = "+".join(f"between(t,{a - 0.15:.2f},{b + 0.25:.2f})" for a, b in windows) or "0"
    graph = (
        f"[0:a]aformat=sample_rates=48000:channel_layouts=stereo,"
        f"volume='if({under},{duck},1)':eval=frame[bed];"
        f"[1:a]aformat=sample_rates=48000:channel_layouts=stereo,"
        f"volume={VOICE_GAIN_DB}dB,alimiter=limit=0.95[ad];"
        f"[bed][ad]amix=inputs=2:normalize=0:duration=first[out]"
    )
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-y", "-i", str(video), "-i", str(narration_wav),
            "-filter_complex", graph, "-map", "0:v", "-map", "[out]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out),
        ],
        check=True,
    )


HOLD_PAD = 0.3  # seconds of quiet after a held line, before the film resumes


def holds(cues: list[Cue]) -> list[tuple[float, float]]:
    """Where extended description holds the picture, and for how long.

    A line longer than its pause holds the last frame of the pause until the
    line ends, so the film never talks over it.
    """
    return [
        (cue.end, round(cue.seconds - (cue.end - cue.start) + HOLD_PAD, 3))
        for cue in cues
        if cue.audio and cue.seconds > cue.end - cue.start
    ]


def shift(t: float, held: list[tuple[float, float]]) -> float:
    """Where time `t` of the original lands once the holds are inserted."""
    return round(t + sum(extra for at, extra in held if at <= t), 3)


def hold_frames(video: Path, held: list[tuple[float, float]], total: float, out: Path) -> None:
    """Re-cut the video with each hold: a frozen frame and silence."""
    edges = [0.0, *(at for at, _ in held), total]
    extras = [extra for _, extra in held] + [0.0]
    parts, labels = [], []
    for i, (a, b) in enumerate(zip(edges, edges[1:])):
        pad_v = f",tpad=stop_mode=clone:stop_duration={extras[i]}" if extras[i] else ""
        pad_a = f",apad=pad_dur={extras[i]}" if extras[i] else ""
        parts.append(f"[0:v]trim=start={a}:end={b},setpts=PTS-STARTPTS{pad_v}[v{i}]")
        parts.append(
            f"[0:a]atrim=start={a}:end={b},asetpts=PTS-STARTPTS,"
            f"aformat=sample_rates=48000:channel_layouts=stereo{pad_a}[a{i}]"
        )
        labels.append(f"[v{i}][a{i}]")
    graph = ";".join(parts) + f";{''.join(labels)}concat=n={len(labels)}:v=1:a=1[v][a]"
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-y", "-i", str(video), "-filter_complex", graph,
            "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
            "-c:a", "aac", "-b:a", "192k", str(out),
        ],
        check=True,
    )


def export(script: Script, out_dir: Path | str) -> dict[str, Path]:
    """Write described.mp4, narration.wav and descriptions.vtt into `out_dir`."""
    out_dir = Path(out_dir)
    files = {
        "video": out_dir / "described.mp4",
        "narration": out_dir / "narration.wav",
        "vtt": out_dir / "descriptions.vtt",
    }
    video, cues, total = Path(script.video), script.cues, script.duration
    held = holds(cues) if AUDIENCES[script.audience].extended else []
    if held:
        video = out_dir / "held.mp4"
        hold_frames(Path(script.video), held, total, video)
        cues = [
            replace(c, start=shift(c.start, held), end=shift(c.start, held) + max(c.end - c.start, c.seconds))
            for c in cues
        ]
        total += sum(extra for _, extra in held)
    files["vtt"].write_text(to_vtt(cues), encoding="utf-8")
    files["narration"].write_bytes(write_wav(narration(cues, out_dir / "audio", total)))
    mix(video, files["narration"], cues, files["video"])
    return files
