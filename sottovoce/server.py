"""Web app: upload a video, watch each line arrive, then review and fix any of them.

    uvicorn sottovoce.server:app --port 8080
"""

from __future__ import annotations

import asyncio
import mimetypes
import json
import os
import re
import shutil
import uuid
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .agent_api import build_a2a
from .audiences import AUDIENCES
from .costs import cost
from .describe import describe_gap
from .export import export
from .pipeline import Cue, Script, describe_video, record_speech
from .shots import duration, extract_frame
from .voice import speak_within

DATA = Path(os.environ.get("SOTTOVOCE_DATA", "data"))
PUBLIC_URL = os.environ.get("SOTTOVOCE_PUBLIC_URL", "http://localhost:8080")
MAX_SECONDS = float(os.environ.get("SOTTOVOCE_MAX_SECONDS", "300"))
# Cloud Run caps an HTTP/1 request at 32 MiB, so the hosted app sets this lower.
MAX_BYTES = int(os.environ.get("SOTTOVOCE_MAX_MB", "300")) * 1024 * 1024
FILES = {
    "source": "source.mp4",
    "described": "described.mp4",
    "narration": "narration.wav",
    "vtt": "descriptions.vtt",
    "script": "script.json",
}
# Media reads come off the Cloud Storage mount, so let browsers keep them a while.
# "private": a shared CDN (Firebase Hosting in front of Cloud Run) would otherwise
# cache the whole file, and it cut a 47.6 MB lesson off at 32 MiB.
# Short, because an edit re-exports the files (the app also cache-busts its URLs).
CACHE = {"Cache-Control": "private, max-age=300"}
running = asyncio.Semaphore(int(os.environ.get("SOTTOVOCE_PARALLEL_JOBS", "2")))
MODELS = {
    "describer": os.environ.get("SOTTOVOCE_DESCRIBER", "DeepSeek-V4.1-Flash"),
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    (DATA / "jobs").mkdir(parents=True, exist_ok=True)
    load_jobs()
    # ADK's A2A app attaches its routes in its own lifespan, so run that here and
    # put the routes ahead of the static files, which answer everything else.
    a2a = await build_a2a(PUBLIC_URL)
    async with a2a.router.lifespan_context(a2a):
        app.router.routes[0:0] = a2a.routes
        yield


app = FastAPI(title="Sottovoce", lifespan=lifespan)


@app.post("/api/jobs")
async def create_job(video: UploadFile = File(...), audience: str = Form("it")) -> dict:
    if audience not in AUDIENCES:
        raise HTTPException(400, f"audience must be one of {sorted(AUDIENCES)}")
    job = Job(uuid.uuid4().hex[:12], Path(video.filename or "video").stem[:80], audience)
    job.dir.mkdir(parents=True)
    try:
        await _receive(video, job.dir / FILES["source"])
    except HTTPException:
        shutil.rmtree(job.dir, ignore_errors=True)
        raise
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
    models = (script.models if script else None) or MODELS
    spent = sum(cost(c.tokens, models) for c in script.cues) if script else 0.0
    return {
        "id": job.id, "title": job.title, "audience": job.audience,
        "status": job.status, "error": job.error,
        "script": json.loads(script.to_json()) if script else None,
        "cost_usd": round(spent, 5),
        "cost_per_minute": round(spent / (script.duration / 60), 5) if script else None,
        "models": models,
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
def job_file(job_id: str, name: str, request: Request) -> Response:
    job = _job(job_id)
    if name not in FILES:
        raise HTTPException(404)
    path = job.dir / FILES[name]
    if not path.exists():
        raise HTTPException(404)
    return media(request, path)


@app.get("/files/{job_id}/audio/{name}")
def cue_audio(job_id: str, name: str, request: Request) -> Response:
    """One voiced line, so a page can play it on its own."""
    job = _job(job_id)
    if not re.fullmatch(r"cue_\d{3}\.wav", name):
        raise HTTPException(404)
    path = job.dir / "audio" / name
    if not path.exists():
        raise HTTPException(404)
    return media(request, path, "audio/wav")


# Cloud Run refuses an HTTP/1 response with a Content-Length over 32 MiB, and a
# browser opens a video with "Range: bytes=0-", which asks for the whole file:
# a 47 MB lesson came back as a 500. So ranges are answered in capped pieces
# (the browser asks for the next one), and a whole-file download is streamed
# in chunks without a Content-Length.
RANGE_CAP = 8 * 1024 * 1024
PROXY_LIMIT = 30 * 1024 * 1024
DIRECT_URL = os.environ.get("SOTTOVOCE_DIRECT_URL", "").rstrip("/")
_RANGE = re.compile(r"bytes=(\d*)-(\d*)")


def _read(path: Path, start: int, length: int):
    with path.open("rb") as f:
        f.seek(start)
        while length > 0:
            chunk = f.read(min(1 << 20, length))
            if not chunk:
                return
            length -= len(chunk)
            yield chunk


def media(request: Request, path: Path, media_type: str | None = None) -> Response:
    """Serve a file with byte ranges, never more than RANGE_CAP bytes per range."""
    size = path.stat().st_size
    media_type = media_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    headers = {**CACHE, "Accept-Ranges": "bytes"}
    match = _RANGE.fullmatch(request.headers.get("range", "").strip())
    if not match or not (match[1] or match[2]):
        forwarded = request.headers.get("x-forwarded-host", "")
        if size > PROXY_LIMIT and DIRECT_URL and forwarded and forwarded not in DIRECT_URL:
            # Behind Firebase Hosting a whole-file response stops at 32 MiB, so a
            # big download goes straight to the Cloud Run address instead.
            return RedirectResponse(f"{DIRECT_URL}{request.url.path}", status_code=307)
        return StreamingResponse(_read(path, 0, size), media_type=media_type, headers=headers)
    if match[1]:
        start = int(match[1])
        end = int(match[2]) if match[2] else size - 1
    else:  # "bytes=-N": the last N bytes
        start, end = max(0, size - int(match[2])), size - 1
    if start >= size or end < start:
        return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
    end = min(end, size - 1, start + RANGE_CAP - 1)
    length = end - start + 1
    headers |= {"Content-Range": f"bytes {start}-{end}/{size}", "Content-Length": str(length)}
    return StreamingResponse(_read(path, start, length), status_code=206, media_type=media_type, headers=headers)


class Edit(BaseModel):
    line: str


@app.post("/api/jobs/{job_id}/cues/{index}")
async def edit_cue(job_id: str, index: int, edit: Edit) -> dict:
    """Check a describer's own wording against the frames, then re-voice and re-mix."""
    job, script, cue = _cue(job_id, index)
    source = job.dir / FILES["source"]
    frames = [await asyncio.to_thread(extract_frame, source, t) for t in cue.frames]
    result = await describe_gap(
        frames, cue.words, job.audience, before=cue.before, after=cue.after,
        focus=cue.focus, draft=edit.line.strip(),
    )
    cue.line, cue.status, cue.claims, cue.history = result.line, result.status, result.claims, result.history
    limit = 60.0 if AUDIENCES[job.audience].extended else cue.end - cue.start
    speech = await asyncio.to_thread(speak_within, cue.line, limit, job.audience)
    cue.audio = cue.audio or f"cue_{index:03d}.wav"
    (job.dir / "audio").mkdir(exist_ok=True)
    (job.dir / "audio" / cue.audio).write_bytes(speech.wav)
    record_speech(cue, speech)
    await _save(job, script)
    return asdict(cue)


@app.post("/api/jobs/{job_id}/cues/{index}/approve")
async def approve_cue(job_id: str, index: int) -> dict:
    """A person signs off on a line the checker could not confirm."""
    job, script, cue = _cue(job_id, index)
    cue.status = "approved"
    await _save(job, script)
    return asdict(cue)


async def _receive(video: UploadFile, source: Path) -> None:
    """Save an upload, refusing anything too big, too long, or not a video."""
    size = 0
    with source.open("wb") as f:
        while chunk := await video.read(1 << 20):
            size += len(chunk)
            if size > MAX_BYTES:
                raise HTTPException(413, f"video larger than {MAX_BYTES >> 20} MB")
            f.write(chunk)
    try:
        seconds = await asyncio.to_thread(duration, source)
    except Exception:
        raise HTTPException(400, "not a video ffmpeg can read") from None
    if seconds > MAX_SECONDS:
        raise HTTPException(400, f"video is {seconds:.0f} s; the limit is {MAX_SECONDS:.0f} s")


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
