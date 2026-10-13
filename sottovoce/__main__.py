"""Command line: python -m sottovoce VIDEO --audience it --out DIR"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time

from .audiences import AUDIENCES
from .export import export
from .pipeline import Cue, describe_video


def main() -> None:
    parser = argparse.ArgumentParser(prog="sottovoce", description="Audio description for a video.")
    parser.add_argument("video")
    parser.add_argument("--audience", default="it", choices=sorted(AUDIENCES))
    parser.add_argument("--out", default="outputs")
    parser.add_argument("--concurrency", type=int, default=3)
    args = parser.parse_args()

    started = time.perf_counter()

    def show(i: int, cue: Cue) -> None:
        mark = "ok" if cue.status == "verified" else "REVIEW"
        print(f"[{cue.start:7.2f}s] {mark:6} r{len(cue.history)} {cue.line}", flush=True)

    script = asyncio.run(
        describe_video(args.video, args.out, args.audience, concurrency=args.concurrency, on_cue=show)
    )
    files = export(script, args.out)
    verified = sum(c.status == "verified" for c in script.cues)
    print(
        f"\n{len(script.cues)} lines, {verified} verified, in {time.perf_counter() - started:.0f}s "
        f"{script.timings}",
        file=sys.stderr,
    )
    for name, path in files.items():
        print(f"{name}: {path}", file=sys.stderr)


if __name__ == "__main__":
    main()
