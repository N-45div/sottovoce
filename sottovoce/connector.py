"""Sottovoce as an MCP server, so an agent can run the service, not only talk about it.

The Evolus desk agent connects to it as a connector: from a chat it can start a described
lesson from a video link, follow it, list the lines waiting for a teacher and read the lesson
as text. Nothing here is more than the web app already offers anyone.

    server.py mounts it at /mcp/ (streamable HTTP).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette

AGES = {"5-8": "-young", "8-13": "", "14-18": "-teen"}
INSTRUCTIONS = (
    "Sottovoce describes lesson videos for blind and low-vision children: it pauses the lesson where the picture "
    "matters, writes a line for the child's age, checks every claim against the frames and voices only checked lines. "
    "Start a lesson with describe_lesson, then follow it with lesson_status: it usually takes a few minutes."
)


def build(*, jobs: dict, start: Callable[[str, str, str], Awaitable[str]], public_url: str, hosts: list[str]) -> Starlette:
    """The MCP app, over the app's own jobs and its way to start one from a link."""
    server = MCPServer(name="Sottovoce", instructions=INSTRUCTIONS, website_url=public_url)

    def lesson(lesson_id: str):
        job = jobs.get(lesson_id)
        if job is None:
            raise ToolError(f"no lesson {lesson_id!r}; list_lessons shows them")
        return job

    @server.tool()
    async def describe_lesson(video_url: str, language: Literal["en", "it"], age: Literal["5-8", "8-13", "14-18"], title: str = "") -> dict:
        """Start a described lesson from an https link to a video file (up to 5 minutes and 30 MB).
        language is what the child listens in; age is the child's age band. Returns the lesson id and its page."""
        lesson_id = await start(video_url, language + AGES[age], title)
        return {"lesson_id": lesson_id, "status": "queued", "link": f"{public_url}/app/#{lesson_id}"}

    @server.tool()
    def lesson_status(lesson_id: str) -> dict:
        """Where a lesson is, how many lines were checked, how many wait for a teacher, and its downloads when done."""
        job = lesson(lesson_id)
        script = job.script()
        cues = [c for c in script.cues if c.line] if script else []
        count = lambda status: sum(c.status == status for c in cues)  # noqa: E731
        done = job.status == "done"
        return {
            "lesson_id": job.id, "title": job.title, "audience": job.audience, "status": job.status, "error": job.error,
            "lines": len(cues), "verified": count("verified"), "approved": count("approved"), "needs_review": count("needs_review"),
            "link": f"{public_url}/app/#{job.id}",
            "downloads": {name: f"{public_url}/files/{job.id}/{name}" for name in ("described", "narration", "vtt", "transcript", "notes")
                          if done and (name not in ("transcript", "notes") or (job.dir / f"{name}.txt").exists())},
        }

    @server.tool()
    def lines_to_review(lesson_id: str) -> list[dict]:
        """The lines no child hears until a teacher approves or edits them, with the claims the checker could not confirm."""
        script = lesson(lesson_id).script()
        return [
            {"index": i, "at_seconds": round(c.start, 1), "line": c.line,
             "unconfirmed": [claim["text"] for claim in c.claims if claim.get("verdict") != "supported"]}
            for i, c in enumerate(script.cues if script else []) if c.status == "needs_review"
        ]

    @server.tool()
    def lesson_transcript(lesson_id: str) -> str:
        """The lesson as text: what the teacher said and every aired description, with times. Use it to answer
        questions about what was on screen."""
        path = lesson(lesson_id).dir / "transcript.txt"
        if not path.exists():
            raise ToolError("this lesson has no transcript yet; it is written when the lesson is done")
        return path.read_text(encoding="utf-8")

    @server.tool()
    def list_lessons() -> list[dict]:
        """Every lesson in the library, newest last."""
        return [{"lesson_id": j.id, "title": j.title, "audience": j.audience, "status": j.status} for j in jobs.values()]

    # Stateless: Cloud Run may start a fresh instance between two calls of one agent.
    return server.streamable_http_app(
        streamable_http_path="/", stateless_http=True, json_response=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=hosts, allowed_origins=[]),
    )
