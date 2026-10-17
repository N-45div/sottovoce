"""Web app: upload a video, watch each line arrive, then review and fix any of them.

    uvicorn sottovoce.server:app --port 8080
"""

from __future__ import annotations

import asyncio
import ipaddress
import mimetypes
import json
import os
import re
import shutil
import socket
import urllib.error
import urllib.request
import uuid
from collections import Counter
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import connector, desk
from .agent_api import build_a2a
from .audiences import AUDIENCES
from .costs import cost
from .describe import GEMMA, TOKEN_FACTORY as TOKEN_FACTORY_BASE, GapResult, Settings, describe_gap, map_items
from .asr import Word, dialogue_around, transcribe
from .export import AIRED, export, holds, original
from .notes import descriptive_transcript, notes_parameters
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
    "transcript": "transcript.txt",  # the lesson as text: the teacher's words and every aired line
    "notes": "notes.txt",  # easy-read notes from the desk on Evolus, and their translation
}
# Media reads come off the Cloud Storage mount, so let browsers keep them a while.
# "private": a shared CDN (Firebase Hosting in front of Cloud Run) would otherwise
# cache the whole file, and it cut a 47.6 MB lesson off at 32 MiB.
# Short, because an edit re-exports the files (the app also cache-busts its URLs).
CACHE = {"Cache-Control": "private, max-age=300"}
running = asyncio.Semaphore(int(os.environ.get("SOTTOVOCE_PARALLEL_JOBS", "2")))
MODELS = {
    "describer": os.environ.get("SOTTOVOCE_DESCRIBER", GEMMA if os.environ.get("SOTTOVOCE_VERTEX_PROJECT") else "Gemma-4-31B-IT"),
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
    if job.status == "done":
        await write_notes(job)


notes_calls = asyncio.Semaphore(1)  # one lesson's notes at a time: Token Factory is shared
notes_errors: dict[str, str] = {}


def write_transcript(job: Job, script: Script) -> str | None:
    """The lesson as text, rewritten whenever a line changes."""
    words = job.dir / "source.words.json"
    if not words.exists():
        return None
    text = descriptive_transcript(job.title, job.audience, [Word(**w) for w in json.loads(words.read_text(encoding="utf-8"))], script.cues)
    (job.dir / FILES["transcript"]).write_text(text, encoding="utf-8")
    return text


async def write_notes(job: Job) -> None:
    """The transcript always; the desk's easy-read notes when Evolus is set up and there are none yet."""
    script = job.script()
    text = write_transcript(job, script) if script else None
    if not text or not desk.notes_ready() or (job.dir / FILES["notes"]).exists():
        return
    async with notes_calls:
        try:
            result = await desk.write_notes(text, notes_parameters(job.audience))
        except desk.DeskError as e:
            notes_errors[job.id] = str(e)
            print(f"notes for {job.id}: {e}", flush=True)
            return
    notes_errors.pop(job.id, None)
    parts = [result.get("notes", ""), result.get("translation", "")]
    (job.dir / FILES["notes"]).write_text("\n\n---\n\n".join(p.strip() for p in parts if p.strip()) + "\n", encoding="utf-8")


@asynccontextmanager
async def lifespan(app: FastAPI):
    (DATA / "jobs").mkdir(parents=True, exist_ok=True)
    load_jobs()
    # Lessons described before the notes existed get them now, one at a time.
    for job in [j for j in jobs.values() if j.status == "done"]:
        task = asyncio.create_task(write_notes(job))
        tasks.add(task)
        task.add_done_callback(tasks.discard)
    # ADK's A2A app attaches its routes in its own lifespan, so run that here and
    # put the routes ahead of the static files, which answer everything else.
    a2a = await build_a2a(PUBLIC_URL)
    # The MCP session manager runs once per instance, so each start builds its own.
    mcp_app.app = connector.build(
        jobs=jobs, start=_start_from_link, public_url=PUBLIC_URL,
        hosts=[urlsplit(u).netloc for u in (PUBLIC_URL, DIRECT_URL) if u] + ["localhost:*", "127.0.0.1:*", "testserver"],
    )
    async with a2a.router.lifespan_context(a2a), mcp_app.app.router.lifespan_context(mcp_app.app):
        app.router.routes[0:0] = a2a.routes
        yield


app = FastAPI(title="Sottovoce", lifespan=lifespan)


@app.post("/api/jobs")
async def create_job(
    video: UploadFile | None = File(None),
    audience: str = Form("it"),
    video_url: str = Form(""),
    title: str = Form(""),
) -> dict:
    """Describe a lesson: an uploaded video, or a link to one (how a request desk sends it)."""
    if audience not in AUDIENCES:
        raise HTTPException(400, f"audience must be one of {sorted(AUDIENCES)}")
    if (video is None) == (not video_url):
        raise HTTPException(400, "send a video file or a video_url, not both")
    name = video.filename if video else urlsplit(video_url).path.rsplit("/", 1)[-1]
    job = Job(uuid.uuid4().hex[:12], (title or Path(name or "video").stem)[:80], audience)
    job.dir.mkdir(parents=True)
    try:
        if video is not None:
            await _receive(video, job.dir / FILES["source"])
        else:
            await asyncio.to_thread(_download, video_url, job.dir / FILES["source"])
            await _check_video(job.dir / FILES["source"])
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
    spent = sum(cost(c.tokens, {**models, **c.models}) for c in script.cues) if script else 0.0
    # Who wrote the lines that were written: the main model, or a backup while it was busy.
    writers = Counter(c.models.get("describer", models["describer"]) for c in script.cues if c.line) if script else Counter()
    return {
        "id": job.id, "title": job.title, "audience": job.audience,
        "status": job.status, "error": job.error,
        "script": json.loads(script.to_json()) if script else None,
        "cost_usd": round(spent, 5),
        "cost_per_minute": round(spent / (script.duration / 60), 5) if script else None,
        "models": models,
        "writers": dict(writers.most_common()),
        "text": {name: (job.dir / FILES[name]).exists() for name in ("transcript", "notes")},
        "notes_error": notes_errors.get(job.id, ""),
    }


# Firebase Hosting ends a proxied request after 60 s, and a browser's EventSource
# gives up on the 503 that follows, so a lesson that took minutes stayed on
# "running". Each stream now ends by itself first; the browser reconnects and
# gets every event again from the start.
STREAM_SECONDS = 45.0


@app.get("/api/jobs/{job_id}/events")
async def job_events(job_id: str) -> StreamingResponse:
    job = _job(job_id)
    queue: asyncio.Queue = asyncio.Queue()
    for event in job.events:
        queue.put_nowait(event)
    listeners.setdefault(job_id, []).append(queue)

    async def stream():
        deadline = asyncio.get_running_loop().time() + STREAM_SECONDS
        try:
            yield "retry: 1000\n\n"
            while (left := deadline - asyncio.get_running_loop().time()) > 0:
                try:
                    event = await asyncio.wait_for(queue.get(), left)
                except TimeoutError:
                    return
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
    cue.models = {"describer": "teacher", **result.models}  # the teacher wrote it, unless the checker sent it back for a rewrite
    limit = 60.0 if AUDIENCES[job.audience].extended else cue.end - cue.start
    speech = await asyncio.to_thread(speak_within, cue.line, limit, job.audience)
    cue.audio = cue.audio or f"cue_{index:03d}.wav"
    (job.dir / "audio").mkdir(exist_ok=True)
    (job.dir / "audio" / cue.audio).write_bytes(speech.wav)
    record_speech(cue, speech)
    await _save(job, script)
    return asdict(cue)


# A child pauses the lesson and asks about the picture, or asks where things
# are. The answer comes from the frame on screen, the checker verifies it, and
# only a checked answer is spoken, like every line. The recorded question is
# transcribed and deleted at once.
ASK_WORDS, MAP_WORDS = 30, 40
MAX_QUESTION_BYTES = 2 * 1024 * 1024  # several seconds of speech
UNSURE = {
    "en": "I'm not sure about that. Ask your teacher.",
    "it": "Non ne sono sicuro. Chiedi al tuo insegnante.",
}
PLACE_WORDS = {"en": {"top": "at the top", "bottom": "at the bottom"}, "it": {"top": "in alto", "bottom": "in basso"}}
asking = asyncio.Semaphore(3)  # model and voice calls for questions, across all lessons
# A child is waiting: past this, the honest answer is "not sure", not silence.
# Token Factory is shared by every team in the hackathon and was slow at peak.
ASK_SECONDS = float(os.environ.get("SOTTOVOCE_ASK_SECONDS", "75"))


# The writer a waiting child gets first; empty keeps the main writer (Gemma 4, which
# answered a question in 17 s on Oct 17). On Oct 17 DeepSeek-V4-Flash-Vision also
# answered in about 3 s while DeepSeek-V4.1 sat at Token Factory's limit of 16 calls,
# so set SOTTOVOCE_ASK_WRITER=DeepSeek-V4-Flash-Vision-Exp to put speed first.
ASK_WRITER = os.environ.get("SOTTOVOCE_ASK_WRITER", "")


def _ask_settings() -> Settings:
    settings = Settings.from_env()
    d = settings.describer
    if not ASK_WRITER or ASK_WRITER == d.model or d.api_base != TOKEN_FACTORY_BASE:
        return settings
    chain = (d.model, *d.backups)
    return replace(settings, describer=replace(d, model=ASK_WRITER, backups=tuple(m for m in chain if m != ASK_WRITER)))


async def _in_time(work) -> GapResult | None:
    try:
        return await asyncio.wait_for(work, ASK_SECONDS)
    except TimeoutError:
        return None


def _done(job_id: str) -> tuple[Job, Script]:
    job = _job(job_id)
    script = job.script()
    if job.status != "done" or script is None:
        raise HTTPException(409, "the lesson is not described yet")
    return job, script


def _moment(script: Script, at: float, held: bool) -> float:
    """The lesson moment on screen at `at` in the player (a frozen frame inside a hold)."""
    if not held:
        return max(0.0, min(at, script.duration))
    aired = [c for c in script.cues if c.status in AIRED]
    return max(0.0, min(original(at, holds(aired)), script.duration))


def _said_before(job: Job, t: float) -> str:
    path = job.dir / "source.words.json"
    if not path.exists():
        return ""
    words = [Word(**w) for w in json.loads(path.read_text(encoding="utf-8"))]
    return dialogue_around(words, t, t)[0]


async def _frame_now(job: Job, t: float) -> list[bytes]:
    """The picture on screen: one frame, since a second earlier can be a different shot."""
    return [await asyncio.to_thread(extract_frame, job.dir / FILES["source"], t)]


async def _voice(job: Job, text: str, limit: float) -> str:
    speech = await asyncio.to_thread(speak_within, text, limit, job.audience)
    folder = job.dir / "asks"
    folder.mkdir(exist_ok=True)
    name = f"{uuid.uuid4().hex[:12]}.wav"
    (folder / name).write_bytes(speech.wav)
    return f"/files/{job.id}/asks/{name}"


async def _hear(job: Job, audio: UploadFile) -> str:
    """What the child asked, from their recording; the recording is deleted straight away."""
    folder = job.dir / "asks"
    folder.mkdir(exist_ok=True)
    path = folder / f"q_{uuid.uuid4().hex[:12]}.webm"
    data = await audio.read(MAX_QUESTION_BYTES + 1)
    if len(data) > MAX_QUESTION_BYTES:
        raise HTTPException(413, "the question is too long; ask in a few seconds")
    try:
        path.write_bytes(data)
        words = await asyncio.to_thread(transcribe, path, language=job.audience[:2])
    finally:
        path.unlink(missing_ok=True)
    return " ".join(w.text for w in words)


@app.post("/api/jobs/{job_id}/ask")
async def ask(
    job_id: str,
    at: float = Form(...),
    held: bool = Form(True),
    question: str = Form(""),
    audio: UploadFile | None = File(None),
) -> dict:
    """Answer a child's question about the picture on screen, checked, and spoken."""
    job, script = _done(job_id)
    async with asking:
        if audio is not None:
            question = await _hear(job, audio)
        question = " ".join(question.split())[:200]
        if not question:
            raise HTTPException(400, "no question heard; hold the button and ask again")
        t = _moment(script, at, held)
        result = await _in_time(describe_gap(
            await _frame_now(job, t), ASK_WORDS, job.audience, question=question, before=_said_before(job, t), max_rounds=2, quick=True, settings=_ask_settings()
        ))
        status = result.status if result else "timeout"
        lang = job.audience[:2]
        answer = result.line if status in ("verified", "not_on_screen") else UNSURE.get(lang, UNSURE["en"])
        audio_url = await _voice(job, answer, 30.0)
    return {
        "question": question, "answer": answer, "status": status, "at": t,
        "claims": result.claims if result else [], "models": result.models if result else {}, "audio": audio_url,
    }


@app.post("/api/jobs/{job_id}/map")
async def sound_map(job_id: str, at: float = Form(...), held: bool = Form(True)) -> dict:
    """Where each thing in the picture is, each name voiced on its own for stereo playback."""
    job, script = _done(job_id)
    async with asking:
        t = _moment(script, at, held)
        result = await _in_time(describe_gap(
            await _frame_now(job, t), MAP_WORDS, job.audience, sound_map=True, before=_said_before(job, t), max_rounds=2, quick=True, settings=_ask_settings()
        ))
        status = result.status if result else "timeout"
        items = map_items(result.line) if status == "verified" else []
        places = PLACE_WORDS.get(job.audience[:2], PLACE_WORDS["en"])
        spoken = [f"{item['name']}, {places[item['y']]}" if item["y"] in places else item["name"] for item in items]
        urls = await asyncio.gather(*(_voice(job, text, 8.0) for text in spoken))
    return {
        "status": status, "line": result.line if result else "", "at": t,
        "claims": result.claims if result else [], "models": result.models if result else {},
        "items": [{**item, "spoken": text, "audio": url} for item, text, url in zip(items, spoken, urls)],
    }


@app.get("/files/{job_id}/asks/{name}")
def ask_audio(job_id: str, name: str, request: Request) -> Response:
    """A spoken answer or sound-map name."""
    job = _job(job_id)
    if not re.fullmatch(r"[0-9a-f]{12}\.wav", name):
        raise HTTPException(404)
    path = job.dir / "asks" / name
    if not path.exists():
        raise HTTPException(404)
    return media(request, path, "audio/wav")


# The request desk runs on Evolus (desk.py). A request comes back as an execution for the
# page to follow: the workflow reads it with a model and downloads the video, which can take
# longer than the 60 s Firebase Hosting gives a proxied request.
desk_calls = asyncio.Semaphore(4)


@app.post("/api/desk")
async def write_to_desk(text: str = Form(...), conversation: str = Form("")) -> dict:
    """A teacher writes to the desk: a request with a video link, or a question."""
    if not desk.ready():
        raise HTTPException(503, "the request desk is not set up on this server")
    text = text.strip()[:2000]
    if not text:
        raise HTTPException(400, "write the request or the question")
    async with desk_calls:
        try:
            if desk.is_request(text):
                return {"kind": "request", "execution": await desk.start(text)}
            answer, conversation = await desk.ask(text, conversation)
        except desk.DeskError as e:
            raise HTTPException(502, str(e)) from None
    return {"kind": "answer", "answer": answer, "conversation": conversation}


@app.get("/api/desk/{execution}")
async def desk_request(execution: str) -> dict:
    """Where a request is; when done, the desk's reply and the lesson it started."""
    if not desk.ready():
        raise HTTPException(503, "the request desk is not set up on this server")
    try:
        run = await desk.follow(execution)
    except desk.DeskError as e:
        raise HTTPException(404 if str(e) == "no such request" else 502, str(e)) from None
    return {"status": run.status, "result": run.result, "error": run.error}


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
    await _check_video(source)


def _check_link(url: str) -> None:
    """Only https links to public addresses: a link must never reach inside our network."""
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        raise HTTPException(400, "give an https link to the video")
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(parts.hostname, parts.port or 443, proto=socket.IPPROTO_TCP)}
    except socket.gaierror:
        raise HTTPException(400, "the link's site could not be found") from None
    if not addresses or not all(ipaddress.ip_address(a).is_global for a in addresses):
        raise HTTPException(400, "the link must point to a public site")


class _CheckedRedirects(urllib.request.HTTPRedirectHandler):
    max_redirections = 3

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _check_link(newurl)  # every hop, or a redirect could lead inside
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _download(url: str, source: Path) -> None:
    """Fetch a video from a public https link, refusing anything too big."""
    _check_link(url)
    request = urllib.request.Request(url, headers={"User-Agent": "Sottovoce/1.0 (lesson audio description)"})
    try:
        with urllib.request.build_opener(_CheckedRedirects).open(request, timeout=30) as r, source.open("wb") as f:
            size = 0
            while chunk := r.read(1 << 20):
                size += len(chunk)
                if size > MAX_BYTES:
                    raise HTTPException(413, f"video larger than {MAX_BYTES >> 20} MB")
                f.write(chunk)
    except urllib.error.HTTPError as e:
        raise HTTPException(400, f"the link answered {e.code}") from None
    except (urllib.error.URLError, TimeoutError):
        raise HTTPException(400, "the link could not be reached") from None


async def _check_video(source: Path) -> None:
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
    write_transcript(job, script)


async def _start_from_link(video_url: str, audience: str, title: str) -> str:
    """For the MCP connector: a lesson from a link, with the same checks as POST /api/jobs."""
    try:
        return (await create_job(video=None, audience=audience, video_url=video_url, title=title))["id"]
    except HTTPException as e:
        raise connector.ToolError(e.detail) from None


class _Current:
    """The MCP app of the running instance (built in lifespan)."""

    app = None

    async def __call__(self, scope, receive, send):
        await self.app(scope, receive, send)


# An agent can run Sottovoce through MCP (connector.py): the Evolus desk agent connects here.
mcp_app = _Current()
app.mount("/mcp", mcp_app)
app.mount("/", StaticFiles(directory=Path(__file__).parent / "web", html=True), name="web")
