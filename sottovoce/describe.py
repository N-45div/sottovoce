"""Write a description for one pause, check it against the frames, and fix it.

Built on Google's Agent Development Kit. The describer and the verifier are
two ADK agents on two different model families, so one model's blind spots
are not repeated by the other: Gemma 4 on Google Cloud's Vertex AI writes
(with DeepSeek on AMD Token Factory behind it), and Qwen3.8 on AMD Token
Factory checks. Whether a line is good enough is decided by plain code, not
a model.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from functools import cache
from typing import Literal

import google.auth
import google.auth.transport.requests
from google.adk.agents import BaseAgent, LlmAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.events import Event, EventActions
from google.adk.models import BaseLlm, FallbackModel
from google.adk.models.lite_llm import LiteLlm
from google.adk.runners import InMemoryRunner
from google.genai import types
from pydantic import BaseModel, ConfigDict, ValidationError

from .audiences import AUDIENCES, Audience

TOKEN_FACTORY = "https://developer.amd.com.cn/radeon/api/v1"
WORD_SLACK = 1.2
GONE = frozenset({400, 404})  # how Token Factory answers for a model it no longer serves
# Gemma 4 on Vertex AI, served by Google with no endpoint of our own to run.
# Vertex offers the 26B-A4B as a managed model; the 31B is not one.
VERTEX = "https://aiplatform.googleapis.com/v1/projects/{project}/locations/global/endpoints/openapi"
GEMMA = "google/gemma-4-26b-a4b-it-maas"
GOOGLE = "google"  # as an api_key: a fresh access token from the Google Cloud credentials


@cache
def _google_credentials():
    credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    return credentials


def google_token() -> tuple[str, dict[str, str]]:
    """An access token for Vertex AI, and the quota header that user credentials need.

    On Cloud Run the service account's token needs no header. Run locally with
    user credentials, Vertex bills the quota project, which can be pinned with
    GOOGLE_CLOUD_QUOTA_PROJECT so other work on the machine does not move it.
    """
    credentials = _google_credentials()
    if not credentials.valid:
        credentials.refresh(google.auth.transport.requests.Request())
    quota = os.environ.get("GOOGLE_CLOUD_QUOTA_PROJECT") or getattr(credentials, "quota_project_id", None)
    return credentials.token, ({"x-goog-user-project": quota} if quota else {})


def short_model(name: str) -> str:
    """The model's own name, without the serving prefix Token Factory adds ("self-dploy/")."""
    return name.removeprefix("self-dploy/")


@dataclass(frozen=True)
class Endpoint:
    """One OpenAI-compatible model: Vertex AI, Token Factory, or vLLM on our own MI300X."""

    model: str
    api_base: str
    api_key: str
    extra_body: dict | None = None
    backups: tuple[str, ...] = ()  # used when the model is busy, down or gone
    backup_base: str = ""  # the backups' server, when it is not the model's own
    backup_key: str = ""

    def llm(self, quick: bool = False) -> BaseLlm:
        """The model, wrapped so a failure moves on to the next backup.

        On Oct 14 Token Factory's Gemma answered 503 "no available workers" for
        a while, which failed whole jobs until this fallback was added. On Oct 16
        Gemma was gone from Token Factory altogether and answered 400 "model not
        supported", which ADK's default (429 and 5xx only) does not fall back on.

        `quick` is for a child waiting on an answer: a busy model is not tried
        again (DeepSeek-V4.1 on Token Factory sat at its limit of 16 calls on
        Oct 16, and retrying it made one answer take 70 s); the next backup is
        the second try.
        """
        chain = [(self.model, self.api_base, self.api_key)]
        chain += [(name, self.backup_base or self.api_base, self.backup_key or self.api_key) for name in self.backups]
        models = [
            self._one(name, base, key, retries=0 if quick and i < len(chain) - 1 else 2)
            for i, (name, base, key) in enumerate(chain)
        ]
        if len(models) == 1:
            return models[0]
        return FallbackModel(models=models, retriable_status_codes=FallbackModel.DEFAULT_STATUS_CODES | GONE)

    def _one(self, name: str, api_base: str, api_key: str, retries: int = 2) -> LiteLlm:
        extra: dict = {"extra_body": self.extra_body} if self.extra_body else {}
        if api_key == GOOGLE:
            # Built per pause, so the token is fresh for the minute a pause takes.
            api_key, headers = google_token()
            if headers:
                extra["extra_headers"] = headers
        return LiteLlm(
            model=f"openai/{name}",
            api_base=api_base,
            api_key=api_key,
            num_retries=retries,  # Token Factory and Vertex both answer 429 when too many calls run at once
            **extra,
        )


def _names(value: str) -> tuple[str, ...]:
    return tuple(n.strip() for n in value.split(",") if n.strip())


@dataclass(frozen=True)
class Settings:
    describer: Endpoint
    verifier: Endpoint

    @classmethod
    def from_env(cls) -> Settings:
        """Read the two endpoints from the environment.

        With SOTTOVOCE_VERTEX_PROJECT set, Gemma 4 on that project's Vertex AI
        writes, and DeepSeek on AMD Token Factory takes over when Vertex is busy.
        Without it the describer runs on Token Factory too. Either can point at
        our own vLLM server instead, with SOTTOVOCE_DESCRIBER_BASE and _KEY.
        Backups are comma-separated model names on Token Factory.
        """
        env = os.environ.get
        key = env("AMD_API_KEY", "")
        if not key:
            raise RuntimeError("set AMD_API_KEY to your AMD Token Factory key")
        effort = env("SOTTOVOCE_VERIFIER_EFFORT", "low")
        vertex = env("SOTTOVOCE_VERTEX_PROJECT", "")
        return cls(
            describer=Endpoint(
                model=env("SOTTOVOCE_DESCRIBER", GEMMA if vertex else "DeepSeek-V4.1-Flash"),
                api_base=env("SOTTOVOCE_DESCRIBER_BASE", VERTEX.format(project=vertex) if vertex else TOKEN_FACTORY),
                api_key=env("SOTTOVOCE_DESCRIBER_KEY", GOOGLE if vertex else key),
                backups=_names(env(
                    "SOTTOVOCE_DESCRIBER_BACKUPS",
                    "DeepSeek-V4.1-Flash,DeepSeek-V4-Flash-Vision-Exp" if vertex else "DeepSeek-V4-Flash-Vision-Exp",
                )),
                backup_base=TOKEN_FACTORY,
                backup_key=key,
            ),
            verifier=Endpoint(
                # Keep the checker in a different family from every describer, so
                # the two never share blind spots.
                model=env("SOTTOVOCE_VERIFIER", "Qwen3.8-27B"),
                api_base=TOKEN_FACTORY,
                api_key=key,
                # Measured on Qwen3.8-27B: default reasoning took 35 s, "low" 15 s with the
                # same verdicts, and thinking off (4.5 s) called a true claim contradicted.
                extra_body={"reasoning_effort": effort} if effort else None,
                backups=_names(env("SOTTOVOCE_VERIFIER_BACKUPS", "Qwen3.8-Flash-Next")),
            ),
        )


class Claim(BaseModel):
    model_config = ConfigDict(extra="ignore")

    text: str
    verdict: Literal["supported", "contradicted", "not_visible"]
    frame: int | None = None


class Check(BaseModel):
    model_config = ConfigDict(extra="ignore")

    claims: list[Claim]


def parse_check(text: str) -> Check:
    """Read the verifier's JSON, tolerating code fences and text around it."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError(f"no JSON object in verifier reply: {text[:200]!r}")
    try:
        return Check.model_validate(json.loads(text[start : end + 1]))
    except (json.JSONDecodeError, ValidationError) as e:
        raise ValueError(f"bad verifier reply: {e}") from e


def count_words(text: str) -> int:
    return len(re.findall(r"[\w'’-]+", text))


def clean_line(text: str) -> str:
    """Keep the first non-empty line, without quotes or markdown."""
    for line in text.splitlines():
        line = line.strip().strip("*_`\"'«»“”").strip()
        if line:
            return line
    return ""


# The honest answer when the picture does not show what a child asked about.
NOT_SEEN = {
    "en": "I can't see that in this picture. Ask your teacher.",
    "it": "Non lo vedo in questa immagine. Chiedi al tuo insegnante.",
}
# A sound map line: "Earth (left, middle); the moon (right, middle); "NOT TO SCALE" (right, top)".
_PLACE = re.compile(r"([^;()]+)\((left|middle|centre|center|right), ?(top|middle|centre|center|bottom)\)", re.I)
_ACROSS = {"left": -0.8, "middle": 0.0, "centre": 0.0, "center": 0.0, "right": 0.8}


def map_items(line: str) -> list[dict]:
    """The things in a sound map line, each with where it sits: x from -0.8 (left) to 0.8 (right)."""
    items = []
    for name, across, down in _PLACE.findall(line):
        down = down.lower()
        items.append({
            "name": name.strip(" ,"),
            "x": _ACROSS[across.lower()],
            "y": "middle" if down in ("centre", "center") else down,
        })
    return items


def _on_demand_instruction(s) -> list[str]:
    """The child paused the lesson: answer their question, or map where things are."""
    if s.get("question"):
        return [
            "A child who cannot see the screen has paused a lesson video to ask about the "
            "picture. The keyframes show what is on screen now.",
            s["style"],
            f'The child asks: "{s["question"]}"',
            f"Answer in at most {s['words']} words, from the keyframes only. If the keyframes do not "
            f"show the answer, or the question is not about the picture, reply exactly: {s['not_seen']} "
            "Reply with the answer only.",
        ]
    # A sound map: where each thing is, so a child with headphones hears the layout.
    return [
        "List what is on screen for a child who cannot see it, so they can hear where each "
        "thing is. The keyframes show what is on screen now.",
        s["style"],
        "Name the 2 to 5 main things from left to right, in exactly this form and nothing else: "
        "name (left|middle|right, top|middle|bottom); name (left|middle|right, top|middle|bottom). "
        "Write the positions in these English words whatever the language; use short, simple "
        "names and put any written words in quotes.",
    ]


def _describer_instruction(ctx: ReadonlyContext) -> str:
    s = ctx.state
    if s.get("question") or s.get("sound_map"):
        parts = _on_demand_instruction(s)
        if s.get("before"):
            parts.append(f"What the teacher said just before: {s['before']}")
        if s.get("feedback"):
            parts.append(s["feedback"])
        return "\n\n".join(parts)
    parts = [
        "You write audio description: one line spoken in a pause in the dialogue, "
        "for people who cannot see the screen. The keyframes come from the shots "
        "under this pause, in order.",
        s["style"],
        f"Use at most {s['words']} words. Reply with the line only.",
    ]
    if s.get("before"):
        parts.append(f"Dialogue just before the pause: {s['before']}")
    if s.get("after"):
        parts.append(f"Dialogue just after the pause: {s['after']}")
    if s.get("focus"):
        parts.append(
            f'The teacher just said: "{s["focus"]}". They are pointing at something on '
            "screen: say exactly what it is, so a child who cannot see knows what they mean."
        )
    if s.get("feedback"):
        parts.append(s["feedback"])
    return "\n\n".join(parts)


def _verifier_instruction(ctx: ReadonlyContext) -> str:
    s = ctx.state
    # The first version merged words into loose claims and passed swaps like
    # "train engines" for rocket engines (8 of 14 planted errors caught); every
    # noun now gets its own claim, worded with the line's own words.
    return (
        "You are a strict fact checker for audio description. Compare the line with "
        "the keyframes.\n\n"
        f"Line: {s['line']}\n\n"
        "Split the line into atomic claims: one claim for every person (with any age "
        "or gender word), object, vehicle, place, colour, number, action and quoted "
        "text. Keep the line's own words in each claim, so 'i motori del razzo' becomes "
        "'the engines are rocket engines'.\n"
        "Verdicts: 'supported' if a frame clearly shows exactly this; 'contradicted' if "
        "the frames show something different (another kind of object, vehicle or "
        "place, another age or gender, another colour, other text); 'not_visible' if no "
        "frame can confirm it. If any word in a claim is wrong, the claim is "
        "contradicted. A name counts as supported only if the dialogue says it.\n"
        f"Dialogue before: {s.get('before') or '(none)'}\n"
        f"Dialogue after: {s.get('after') or '(none)'}\n\n"
        'Reply with JSON only: {"claims": [{"text": "...", "verdict": "...", '
        '"frame": <1-based frame number or null>}]}'
    )


def judge(line: str, reply: str, limit: int) -> tuple[Check, list[str]]:
    """List what is wrong with a line, from the verifier's reply and the word budget."""
    try:
        check = parse_check(reply)
    except ValueError as e:
        return Check(claims=[]), [f"verifier reply unreadable: {e}"]
    problems = [
        f'"{c.text}" is {c.verdict.replace("_", " ")}' for c in check.claims if c.verdict != "supported"
    ]
    # The budget is an estimate and models count words loosely; the voice step
    # measures the real spoken length, so a word or two over is left to it.
    words = count_words(line)
    if words > limit * WORD_SLACK:
        problems.append(f"the line has {words} words, the limit is {limit}")
    return check, problems


class GapDescriber(BaseAgent):
    """Describe, verify, and rewrite until the line is supported and fits."""

    describer: LlmAgent
    verifier: LlmAgent
    max_rounds: int = 3

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        state = ctx.session.state
        for round_ in range(1, self.max_rounds + 1):
            if round_ == 1 and state.get("draft"):
                # A describer's own line, or one from an existing script: check it first.
                line = clean_line(state["draft"])
            else:
                async for event in self.describer.run_async(ctx):
                    yield event
                line = clean_line(state.get("line", ""))
            yield Event(
                author=self.name,
                invocation_id=ctx.invocation_id,
                actions=EventActions(state_delta={"line": line}),
            )
            if state.get("question") and line.startswith(state["not_seen"][:18]):
                # Nothing to check: the honest answer is that the picture does not show it.
                yield Event(
                    author=self.name,
                    invocation_id=ctx.invocation_id,
                    actions=EventActions(state_delta={"line": state["not_seen"], "rounds": round_, "status": "not_on_screen"}),
                )
                return

            async for event in self.verifier.run_async(ctx):
                yield event
            check, problems = judge(line, state.get("check", ""), state["words"])
            verified = not problems and bool(check.claims)
            delta = {
                "line": line,
                "rounds": round_,
                "claims": [c.model_dump() for c in check.claims],
                "problems": problems,
                "history": [
                    *state.get("history", []),
                    {"round": round_, "line": line, "problems": problems},
                ],
                "status": "verified" if verified else "needs_review",
                "feedback": (
                    f'Your last line was: "{line}". Rewrite it and fix these problems: '
                    + "; ".join(problems)
                    + ". Keep only what the frames show."
                ),
            }
            yield Event(
                author=self.name,
                invocation_id=ctx.invocation_id,
                actions=EventActions(state_delta=delta),
            )
            if verified:
                return


def build_agent(settings: Settings, max_rounds: int = 3, quick: bool = False) -> GapDescriber:
    describer = LlmAgent(
        name="describer",
        model=settings.describer.llm(quick),
        instruction=_describer_instruction,
        output_key="line",
        generate_content_config=types.GenerateContentConfig(temperature=0.3, max_output_tokens=400),
    )
    verifier = LlmAgent(
        name="verifier",
        model=settings.verifier.llm(quick),
        instruction=_verifier_instruction,
        output_key="check",
        generate_content_config=types.GenerateContentConfig(temperature=0.0, max_output_tokens=800),
    )
    return GapDescriber(
        name="gap_describer",
        describer=describer,
        verifier=verifier,
        sub_agents=[describer, verifier],
        max_rounds=max_rounds,
    )


@dataclass
class GapResult:
    line: str
    status: str
    rounds: int
    claims: list[dict]
    problems: list[str]
    history: list[dict] = field(default_factory=list)
    tokens: dict[str, list[int]] = field(default_factory=dict)
    models: dict[str, str] = field(default_factory=dict)  # agent -> the model that answered, backups included


async def describe_gap(
    frames: list[bytes],
    words: int,
    audience: Audience | str = "it",
    *,
    before: str = "",
    after: str = "",
    mime_type: str = "image/jpeg",
    draft: str = "",
    focus: str = "",
    question: str = "",
    sound_map: bool = False,
    settings: Settings | None = None,
    max_rounds: int = 3,
    quick: bool = False,
) -> GapResult:
    """Run the describe-verify loop for one pause and return the outcome.

    With `draft`, the first round checks that line instead of writing one.
    With `focus`, the teacher has just pointed at something ("look at this"),
    and the line says what it is. With `question`, a child paused the lesson
    to ask about the picture; with `sound_map`, the line says where each thing
    is (see map_items). Either way the checker verifies it before it is spoken.
    """
    if isinstance(audience, str):
        audience = AUDIENCES[audience]
    settings = settings or Settings.from_env()
    runner = InMemoryRunner(agent=build_agent(settings, max_rounds, quick), app_name="sottovoce")
    session = await runner.session_service.create_session(
        app_name="sottovoce",
        user_id="describer",
        session_id=uuid.uuid4().hex,
        state={
            "words": words,
            "style": audience.style,
            "before": before,
            "after": after,
            "draft": draft,
            "focus": focus,
            "question": question,
            "sound_map": sound_map,
            "not_seen": NOT_SEEN.get(audience.key[:2], NOT_SEEN["en"]),
        },
    )
    message = types.Content(
        role="user",
        parts=[types.Part.from_bytes(data=f, mime_type=mime_type) for f in frames]
        + [types.Part(text=f"{len(frames)} keyframes from the shots under this pause.")],
    )
    tokens: dict[str, list[int]] = {}
    models: dict[str, str] = {}
    async for event in runner.run_async(
        user_id="describer", session_id=session.id, new_message=message
    ):
        usage = event.usage_metadata
        if usage:
            used = tokens.setdefault(event.author, [0, 0])
            used[0] += usage.prompt_token_count or 0
            used[1] += usage.candidates_token_count or 0
        if event.model_version:
            models[event.author] = short_model(event.model_version)

    state = (await runner.session_service.get_session(
        app_name="sottovoce", user_id="describer", session_id=session.id
    )).state
    return GapResult(
        line=state.get("line", ""),
        status=state.get("status", "needs_review"),
        rounds=state.get("rounds", 0),
        claims=state.get("claims", []),
        problems=state.get("problems", []),
        history=state.get("history", []),
        tokens=tokens,
        models=models,
    )
