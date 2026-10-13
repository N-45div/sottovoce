"""Measure the checker on real lines: how many planted errors it catches, how many good lines it flags.

    python -m sottovoce.bench outputs/script.json [--seed 7]

Each verified line from a real run is checked twice more against its own
frames: once unchanged (a flag there is a false alarm), and once with one
planted error (a flag there is a catch). The planted errors swap a person, an
object, a place or a colour for something that is not on screen, or add an
object that is not there.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from .describe import Settings, describe_gap
from .pipeline import Script
from .shots import extract_frame

SWAPS = {
    "it": {
        "uomo": "bambino", "donna": "anziana", "fucile": "ombrello", "cervello": "cuore",
        "ponte": "spiaggia", "razzo": "treno", "città": "foresta", "balcone": "barca",
        "dirigibile": "elefante", "rosso": "verde", "giallo": "viola", "blu": "arancione",
        "notte": "mezzogiorno", "luci": "candele", "schermo": "lago", "torri": "palme",
    },
    "en": {
        "man": "child", "woman": "old woman", "rifle": "umbrella", "brain": "heart",
        "bridge": "beach", "rocket": "train", "city": "forest", "balcony": "boat",
        "airship": "elephant", "red": "green", "yellow": "purple", "blue": "orange",
        "night": "noon", "lights": "candles", "screen": "lake", "towers": "palm trees",
    },
}
INSERTS = {
    "it": " Un cane bianco dorme accanto.",
    "en": " A white dog sleeps nearby.",
}


def plant_error(line: str, language: str, rng: random.Random) -> tuple[str, str]:
    """Return the line with one false detail, and a note of what was changed."""
    swaps = SWAPS[language]
    found = [w for w in swaps if re.search(rf"\b{re.escape(w)}\b", line, re.IGNORECASE)]
    if found:
        word = rng.choice(found)
        changed = re.sub(rf"\b{re.escape(word)}\b", swaps[word], line, count=1, flags=re.IGNORECASE)
        return changed, f"{word} -> {swaps[word]}"
    return line.rstrip() + INSERTS[language], "inserted an object"


@dataclass
class Trial:
    cue: float
    kind: str  # "original" or "planted"
    line: str
    change: str
    flagged: bool
    problems: list[str]


async def run(script: Script, *, seed: int = 7, concurrency: int = 3) -> list[Trial]:
    language = "en" if script.audience == "en" else "it"
    rng = random.Random(seed)
    settings = Settings.from_env()
    gate = asyncio.Semaphore(concurrency)
    jobs = []
    for cue in script.cues:
        if cue.status != "verified":
            continue
        planted, change = plant_error(cue.line, language, rng)
        jobs += [(cue, "original", cue.line, ""), (cue, "planted", planted, change)]

    async def one(cue, kind, line, change) -> Trial:
        async with gate:
            frames = [await asyncio.to_thread(extract_frame, script.video, t) for t in cue.frames]
            result = await describe_gap(
                frames, cue.words, script.audience, before=cue.before, after=cue.after,
                draft=line, max_rounds=1, settings=settings,
            )
        problems = result.history[0]["problems"] if result.history else ["no verdict"]
        return Trial(cue.start, kind, line, change, bool(problems), problems)

    return list(await asyncio.gather(*(one(*job) for job in jobs)))


def summarize(trials: list[Trial]) -> dict:
    planted = [t for t in trials if t.kind == "planted"]
    original = [t for t in trials if t.kind == "original"]
    caught = sum(t.flagged for t in planted)
    false_alarms = sum(t.flagged for t in original)
    return {
        "lines": len(original),
        "planted_errors": len(planted),
        "caught": caught,
        "catch_rate": round(caught / len(planted), 3) if planted else None,
        "false_alarms": false_alarms,
        "false_alarm_rate": round(false_alarms / len(original), 3) if original else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(prog="sottovoce.bench")
    parser.add_argument("script")
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    path = Path(args.script)
    script = Script.from_json(path.read_text(encoding="utf-8"))
    trials = asyncio.run(run(script, seed=args.seed))
    for t in sorted(trials, key=lambda t: (t.cue, t.kind)):
        mark = "FLAG" if t.flagged else "pass"
        print(f"[{t.cue:7.2f}s] {t.kind:8} {mark}  {t.change:24} {t.line}")
    summary = summarize(trials)
    print(json.dumps(summary, indent=2))
    out = path.with_name("bench.json")
    out.write_text(
        json.dumps({"summary": summary, "trials": [asdict(t) for t in trials]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
