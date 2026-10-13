"""Write a description for one pause, check it against the frames, and fix it.

Built on Google's Agent Development Kit. The describer and the verifier are
two ADK agents on two different model families, both served on AMD GPUs by
AMD's Token Factory, so one model's blind spots are not repeated by the
other. Whether a line is good enough is decided by plain code, not a model.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Literal

from google.adk.agents import BaseAgent, LlmAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.events import Event, EventActions
from google.adk.models.lite_llm import LiteLlm
from google.adk.runners import InMemoryRunner
from google.genai import types
from pydantic import BaseModel, ConfigDict, ValidationError

from .audiences import AUDIENCES, Audience

TOKEN_FACTORY = "https://developer.amd.com.cn/radeon/api/v1"


@dataclass(frozen=True)
class Settings:
    api_base: str
    api_key: str
    describer: str
    verifier: str

    @classmethod
    def from_env(cls) -> Settings:
        key = os.environ.get("AMD_API_KEY", "")
        if not key:
            raise RuntimeError("set AMD_API_KEY to your AMD Token Factory key")
        return cls(
            api_base=os.environ.get("SOTTOVOCE_API_BASE", TOKEN_FACTORY),
            api_key=key,
            describer=os.environ.get("SOTTOVOCE_DESCRIBER", "Gemma-4-31B-IT"),
            verifier=os.environ.get("SOTTOVOCE_VERIFIER", "Qwen3.8-27B"),
        )

    def model(self, name: str) -> LiteLlm:
        return LiteLlm(model=f"openai/{name}", api_base=self.api_base, api_key=self.api_key)


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


def _describer_instruction(ctx: ReadonlyContext) -> str:
    s = ctx.state
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
    if s.get("feedback"):
        parts.append(s["feedback"])
    return "\n\n".join(parts)


def _verifier_instruction(ctx: ReadonlyContext) -> str:
    s = ctx.state
    return (
        "You check an audio description line against the keyframes.\n\n"
        f"Line: {s['line']}\n\n"
        "Split the line into short factual claims about what is on screen. For each "
        "claim give a verdict: 'supported' if a frame clearly shows it, 'contradicted' "
        "if the frames show otherwise, 'not_visible' if the frames cannot confirm it. "
        "A name counts as supported only if the dialogue says it.\n"
        f"Dialogue before: {s.get('before') or '(none)'}\n"
        f"Dialogue after: {s.get('after') or '(none)'}\n\n"
        'Reply with JSON only: {"claims": [{"text": "...", "verdict": "...", '
        '"frame": <1-based frame number or null>}]}'
    )


class GapDescriber(BaseAgent):
    """Describe, verify, and rewrite until the line is supported and fits."""

    describer: LlmAgent
    verifier: LlmAgent
    max_rounds: int = 3

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        state = ctx.session.state
        for round_ in range(1, self.max_rounds + 1):
            async for event in self.describer.run_async(ctx):
                yield event
            line = clean_line(state.get("line", ""))
            yield Event(
                author=self.name,
                invocation_id=ctx.invocation_id,
                actions=EventActions(state_delta={"line": line}),
            )

            async for event in self.verifier.run_async(ctx):
                yield event
            try:
                check = parse_check(state.get("check", ""))
            except ValueError as e:
                check, problems = Check(claims=[]), [f"verifier reply unreadable: {e}"]
            else:
                problems = [
                    f'"{c.text}" is {c.verdict.replace("_", " ")}'
                    for c in check.claims
                    if c.verdict != "supported"
                ]
            words = count_words(line)
            if words > state["words"]:
                problems.append(f"the line has {words} words, the limit is {state['words']}")

            verified = not problems and bool(check.claims)
            delta = {
                "line": line,
                "rounds": round_,
                "claims": [c.model_dump() for c in check.claims],
                "problems": problems,
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


def build_agent(settings: Settings, max_rounds: int = 3) -> GapDescriber:
    describer = LlmAgent(
        name="describer",
        model=settings.model(settings.describer),
        instruction=_describer_instruction,
        output_key="line",
        generate_content_config=types.GenerateContentConfig(temperature=0.3, max_output_tokens=400),
    )
    verifier = LlmAgent(
        name="verifier",
        model=settings.model(settings.verifier),
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
    tokens: dict[str, list[int]] = field(default_factory=dict)


async def describe_gap(
    frames: list[bytes],
    words: int,
    audience: Audience | str = "it",
    *,
    before: str = "",
    after: str = "",
    mime_type: str = "image/jpeg",
    settings: Settings | None = None,
    max_rounds: int = 3,
) -> GapResult:
    """Run the describe-verify loop for one pause and return the outcome."""
    if isinstance(audience, str):
        audience = AUDIENCES[audience]
    settings = settings or Settings.from_env()
    runner = InMemoryRunner(agent=build_agent(settings, max_rounds), app_name="sottovoce")
    session = await runner.session_service.create_session(
        app_name="sottovoce",
        user_id="describer",
        session_id=uuid.uuid4().hex,
        state={"words": words, "style": audience.style, "before": before, "after": after},
    )
    message = types.Content(
        role="user",
        parts=[types.Part.from_bytes(data=f, mime_type=mime_type) for f in frames]
        + [types.Part(text=f"{len(frames)} keyframes from the shots under this pause.")],
    )
    tokens: dict[str, list[int]] = {}
    async for event in runner.run_async(
        user_id="describer", session_id=session.id, new_message=message
    ):
        usage = event.usage_metadata
        if usage:
            used = tokens.setdefault(event.author, [0, 0])
            used[0] += usage.prompt_token_count or 0
            used[1] += usage.candidates_token_count or 0

    state = (await runner.session_service.get_session(
        app_name="sottovoce", user_id="describer", session_id=session.id
    )).state
    return GapResult(
        line=state.get("line", ""),
        status=state.get("status", "needs_review"),
        rounds=state.get("rounds", 0),
        claims=state.get("claims", []),
        problems=state.get("problems", []),
        tokens=tokens,
    )
