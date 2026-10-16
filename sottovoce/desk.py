"""The request desk, on Evolus: a teacher writes in plain words, and the desk does the rest.

A request with a video link goes to the Evolus workflow "Describe a lesson": the desk agent
(Gemma 4 on AMD Token Factory, connected to Evolus as the workspace's own model) reads the
link, language and age, a script checks them, and the workflow starts the described lesson
here through POST /api/jobs, or answers with what is missing. Anything else is a question for
the same agent, which answers from the Evolus knowledge library (WCAG, ADA Title II, the
Italian and EU rules, how Sottovoce works).

Evolus REST takes X-ApiKey + X-Application-Id; the agent's chat is OpenAI-compatible, with the
model named "<application id>:<agent id>". Nothing is set up without EVOLUS_API_KEY.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass

import httpx

API = os.environ.get("EVOLUS_API", "https://api.evolus.ai")
KEY = os.environ.get("EVOLUS_API_KEY", "")
APP = os.environ.get("EVOLUS_APP_ID", "")
WORKFLOW = os.environ.get("EVOLUS_DESK_WORKFLOW", "")
AGENT = os.environ.get("EVOLUS_DESK_AGENT", "")
EXECUTION = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
LINK = re.compile(r"https://\S+")


class DeskError(Exception):
    """Evolus refused or failed; the message is safe to show."""


@dataclass
class Run:
    status: str  # Pending, Running, Completed or Failed
    result: dict | None = None
    error: str = ""


def ready() -> bool:
    return bool(KEY and APP and WORKFLOW and AGENT)


def is_request(text: str) -> bool:
    """A message with a video link is a request; anything else is a question."""
    return bool(LINK.search(text))


def _headers() -> dict:
    return {"X-ApiKey": KEY, "X-Application-Id": APP}


async def _call(what: str, method: str, path: str, timeout: float = 30, **kwargs) -> httpx.Response:
    try:
        async with httpx.AsyncClient(base_url=API, timeout=timeout) as client:
            response = await client.request(method, path, **kwargs)
    except httpx.TimeoutException:
        raise DeskError("the desk is busy; try again in a minute") from None
    except httpx.HTTPError:
        raise DeskError("the desk could not be reached; try again in a minute") from None
    if response.status_code >= 400:
        raise DeskError(f"the desk could not {what} (Evolus {response.status_code})")
    return response


async def start(text: str) -> str:
    """Send a request to the workflow; the execution id, to follow it."""
    r = await _call("take the request", "POST", f"/api/v1/workflows/{WORKFLOW}/execute", headers=_headers(), files={"input": (None, text)})
    return r.json()["executionId"]


async def follow(execution: str) -> Run:
    """Where the request is; when done, the workflow's answer."""
    if not EXECUTION.fullmatch(execution):
        raise DeskError("no such request")
    r = await _call("find the request", "GET", f"/api/v1/workflows/{WORKFLOW}/executions/{execution}", headers=_headers())
    run = r.json()
    if run.get("status") == "Failed":
        return Run("Failed", error=_reason(run.get("error") or ""))
    if run.get("status") != "Completed":
        return Run(run.get("status") or "Pending")
    try:
        return Run("Completed", json.loads(run.get("output") or ""))
    except ValueError:
        return Run("Failed", error="the desk's answer could not be read")


def _reason(error: str) -> str:
    """Why a request failed, in a teacher's words: Sottovoce's own refusal when there is one."""
    said = re.search(r'"detail"\s*:\s*"([^"]{1,200})"', error)
    if said:
        return f"Sottovoce could not use the video: {said.group(1)}."
    return "the desk could not finish this request; try again, or upload the video here"


async def ask(question: str, conversation: str = "") -> tuple[str, str]:
    """The agent's answer from the knowledge library, and the conversation id to continue it."""
    headers = {"Authorization": f"Bearer {KEY}"}
    if conversation and EXECUTION.fullmatch(conversation):
        headers["X-Conversation-Id"] = conversation
    body = {"model": f"{APP}:{AGENT}", "messages": [{"role": "user", "content": question}]}
    # under the 60 s Firebase Hosting gives a proxied request
    r = await _call("answer", "POST", "/v1/chat/completions", timeout=50, headers=headers, json=body)
    answer = r.json()["choices"][0]["message"]["content"] or ""
    return answer.strip(), r.headers.get("X-Conversation-Id", "")
