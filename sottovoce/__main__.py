"""Command line: python -m sottovoce VIDEO --audience it [--out DIR | --library DATA_DIR]"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
import time
import uuid
from pathlib import Path

from .audiences import AUDIENCES
from .export import export
from .pipeline import Cue, describe_video


def main() -> None:
    parser = argparse.ArgumentParser(prog="sottovoce", description="Audio description for a video.")
    parser.add_argument("video")
    parser.add_argument("--audience", default="it", choices=sorted(AUDIENCES))
    parser.add_argument("--out", default="outputs", help="folder for the results")
    parser.add_argument("--library", help="the web app's data folder: add the result as a finished job")
    parser.add_argument("--title", help="title in the web app library")
    parser.add_argument("--concurrency", type=int, default=3)
    args = parser.parse_args()

    video, out = Path(args.video), Path(args.out)
    job = None
    if args.library:
        job = {
            "id": uuid.uuid4().hex[:12],
            "title": args.title or video.stem,
            "audience": args.audience,
            "status": "done",
            "error": "",
        }
        out = Path(args.library) / "jobs" / job["id"]
        out.mkdir(parents=True)
        video = Path(shutil.copy(video, out / "source.mp4"))

    started = time.perf_counter()

    def show(i: int, cue: Cue) -> None:
        mark = "ok" if cue.status == "verified" else "REVIEW"
        print(f"[{cue.start:7.2f}s] {mark:6} r{len(cue.history)} {cue.line}", flush=True)

    script = asyncio.run(
        describe_video(video, out, args.audience, concurrency=args.concurrency, on_cue=show)
    )
    files = export(script, out)
    if job:
        (out / "job.json").write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
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
