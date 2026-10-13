"""Web app: upload a video, watch each line arrive, then review and fix any of them.

    uvicorn sottovoce.server:app --port 8080
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .audiences import AUDIENCES
from .costs import cost
from .describe import describe_gap
from .export import export
from .pipeline import Cue, Script, describe_video
from .shots import duration, extract_frame
from .voice import speak_within

DATA = Path(os.environ.get("SOTTOVOCE_DATA", "data"))
MAX_SECONDS = float(os.environ.get("SOTTOVOCE_MAX_SECONDS", "300"))
MAX_BYTES = 300 * 1024 * 1024
FILES = {
    "source": "source.mp4",
    "described": "described.mp4",
    "narration": "narration.wav",
    "vtt": "descriptions.vtt",
    "script": "script.json",
}
running = asyncio.Semaphore(int(os.environ.get("SOTTOVOCE_PARALLEL_JOBS", "2")))
MODELS = {
    "describer": os.environ.get("SOTTOVOCE_DESCRIBER", "DeepSeek-V4-Flash-Vision-Exp"),
    "verifier": os.environ.get("SOTTOVOCE_VERIFIER", "Qwen3.8-27B"),
}


@dataclass
class Job:
    id: str
    title: str
    audience: str
    status: str = "queued"
    error: str = ""
    events: list[dict] = field(default_factory=list)

    @property
    def dir(self) -> Path:
        return DATA / "jobs" / self.id

    def save(self) -> None:
        meta = {k: v for k, v in asdict(self).items() if k != "events"}
        (self.dir / "job.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")

    def script(self) -> Script | None:
        path = self.dir / FILES["script"]
        return Script.from_json(path.read_text(encoding="utf-8")) if path.exists() else None


jobs: dict[str, Job] = {}
listeners: dict[str, list[asyncio.Queue]] = {}
tasks: set[asyncio.Task] = set()


def load_jobs() -> None:
    for meta in sorted((DATA / "jobs").glob("*/job.json")):
        job = Job(**json.loads(meta.read_text(encoding="utf-8")))
        if job.status in ("queued", "running"):
            job.status, job.error = "failed", "the server restarted during this job"
        jobs[job.id] = job


def publish(job: Job, event: dict) -> None:
    job.events.append(event)
    for queue in listeners.get(job.id, []):
        queue.put_nowait(event)


async def run_job(job: Job) -> None:
    async with running:
        job.status = "running"
        job.save()
        publish(job, {"type": "status", "status": "running"})
        try:
            def on_cue(i: int, cue: Cue) -> None:
                publish(job, {"type": "cue", "index": i, "cue": asdict(cue)})

            script = await describe_video(
                job.dir / FILES["source"], job.dir, job.audience, on_cue=on_cue
            )
            await asyncio.to_thread(export, script, job.dir)
            job.status = "done"
        except Exception as e:  # noqa: BLE001 - any failure is reported on the job
            job.status, job.error = "failed", f"{type(e).__name__}: {e}"
        job.save()
        publish(job, {"type": "status", "status": job.status, "error": job.error})


app = FastAPI(title="Sottovoce")


@app.on_event("startup")
def startup() -> None:
    (DATA / "jobs").mkdir(parents=True, exist_ok=True)
    load_jobs()


@app.post("/api/jobs")
async def create_job(video: UploadFile = File(...), audience: str = Form("it")) -> dict:
    if audience not in AUDIENCES:
        raise HTTPException(400, f"audience must be one of {sorted(AUDIENCES)}")
    job = Job(uuid.uuid4().hex[:12], Path(video.filename or "video").stem[:80], audience)
    job.dir.mkdir(parents=True)
    source = job.dir / FILES["source"]
    size = 0
    with source.open("wb") as f:
        while chunk := await video.read(1 << 20):
            size += len(chunk)
            if size > MAX_BYTES:
                raise HTTPException(413, "video larger than 300 MB")
            f.write(chunk)
    try:
        seconds = await asyncio.to_thread(duration, source)
    except Exception:
        raise HTTPException(400, "not a video ffmpeg can read") from None
    if seconds > MAX_SECONDS:
        raise HTTPException(400, f"video is {seconds:.0f} s; the limit is {MAX_SECONDS:.0f} s")
    jobs[job.id] = job
    job.save()
    task = asyncio.create_task(run_job(job))
    tasks.add(task)  # asyncio keeps only weak references to tasks
    task.add_done_callback(tasks.discard)
    return {"id": job.id}


@app.get("/api/jobs")
def list_jobs() -> list[dict]:
    return [
        {"id": j.id, "title": j.title, "audience": j.audience, "status": j.status}
        for j in jobs.values()
    ]


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    job = _job(job_id)
    script = job.script()
    spent = sum(cost(c.tokens, MODELS) for c in script.cues) if script else 0.0
    return {
        "id": job.id, "title": job.title, "audience": job.audience,
        "status": job.status, "error": job.error,
        "script": json.loads(script.to_json()) if script else None,
        "cost_usd": round(spent, 5),
        "cost_per_minute": round(spent / (script.duration / 60), 5) if script else None,
        "models": MODELS,
    }


@app.get("/api/jobs/{job_id}/events")
async def job_events(job_id: str) -> StreamingResponse:
    job = _job(job_id)
    queue: asyncio.Queue = asyncio.Queue()
    for event in job.events:
        queue.put_nowait(event)
    listeners.setdefault(job_id, []).append(queue)

    async def stream():
        try:
            while True:
                event = await queue.get()
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                if event.get("type") == "status" and event["status"] in ("done", "failed"):
                    return
        finally:
            listeners[job_id].remove(queue)

    if job.status in ("done", "failed") and not job.events:
        queue.put_nowait({"type": "status", "status": job.status, "error": job.error})
    return StreamingResponse(stream(), media_type="text/event-stream")


@app.get("/files/{job_id}/{name}")
def job_file(job_id: str, name: str) -> FileResponse:
    job = _job(job_id)
    if name not in FILES:
        raise HTTPException(404)
    path = job.dir / FILES[name]
    if not path.exists():
        raise HTTPException(404)
    return FileResponse(path)


class Edit(BaseModel):
    line: str


@app.post("/api/jobs/{job_id}/cues/{index}")
async def edit_cue(job_id: str, index: int, edit: Edit) -> dict:
    """Check a describer's own wording against the frames, then re-voice and re-mix."""
    job, script, cue = _cue(job_id, index)
    source = job.dir / FILES["source"]
    frames = [await asyncio.to_thread(extract_frame, source, t) for t in cue.frames]
    result = await describe_gap(
        frames, cue.words, job.audience, before=cue.before, after=cue.after, draft=edit.line.strip()
    )
    cue.line, cue.status, cue.claims, cue.history = result.line, result.status, result.claims, result.history
    speech = await asyncio.to_thread(speak_within, cue.line, cue.end - cue.start, job.audience)
    cue.audio = cue.audio or f"cue_{index:03d}.wav"
    (job.dir / "audio" / cue.audio).write_bytes(speech.wav)
    cue.seconds, cue.rate, cue.fits = round(speech.seconds, 3), speech.rate, speech.fits
    await _save(job, script)
    return asdict(cue)


@app.post("/api/jobs/{job_id}/cues/{index}/approve")
async def approve_cue(job_id: str, index: int) -> dict:
    """A person signs off on a line the checker could not confirm."""
    job, script, cue = _cue(job_id, index)
    cue.status = "approved"
    await _save(job, script)
    return asdict(cue)


def _job(job_id: str) -> Job:
    if job_id not in jobs:
        raise HTTPException(404, "no such job")
    return jobs[job_id]


def _cue(job_id: str, index: int) -> tuple[Job, Script, Cue]:
    job = _job(job_id)
    script = job.script()
    if job.status != "done" or script is None:
        raise HTTPException(409, "the job is not finished")
    if not 0 <= index < len(script.cues):
        raise HTTPException(404, "no such line")
    return job, script, script.cues[index]


async def _save(job: Job, script: Script) -> None:
    script.video = str(job.dir / FILES["source"])  # jobs can move between machines
    (job.dir / FILES["script"]).write_text(script.to_json(), encoding="utf-8")
    await asyncio.to_thread(export, script, job.dir)


app.mount("/", StaticFiles(directory=Path(__file__).parent / "web", html=True), name="web")
