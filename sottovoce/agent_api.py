"""Sottovoce as an A2A agent, served by Google ADK.

Another agent (a broadcaster's media library, an editing tool) sends the
keyframes of a pause as image parts, plus an optional JSON text part:

    {"words": 20, "audience": "en", "before": "...", "after": "...", "focus": "Look at this graph.", "draft": "..."}

It gets back one JSON text part: the line, whether every claim in it was
confirmed in the frames, each claim's verdict, and the rounds it took.
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from dataclasses import asdict

from google.adk.a2a.utils.agent_card_builder import AgentCardBuilder
from google.adk.a2a.utils.agent_to_a2a import to_a2a
from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event
from google.genai import types
from starlette.applications import Starlette

from .audiences import AUDIENCES
from .describe import describe_gap

DEFAULT_WORDS = 14


def read_request(content: types.Content | None) -> tuple[list[tuple[bytes, str]], dict]:
    """Split a request into its images and its options."""
    images, text = [], []
    for part in (content.parts if content else None) or []:
        blob = part.inline_data
        if blob and blob.data and (blob.mime_type or "").startswith("image/"):
            images.append((blob.data, blob.mime_type))
        elif part.text:
            text.append(part.text)
    joined = "\n".join(text)
    start, end = joined.find("{"), joined.rfind("}")
    options = {}
    if 0 <= start < end:
        try:
            options = json.loads(joined[start : end + 1])
        except json.JSONDecodeError:
            options = {}
    return images, options if isinstance(options, dict) else {}


class DescribeFramesAgent(BaseAgent):
    """Write one line of audio description for a pause and check it against the frames."""

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        images, options = read_request(ctx.user_content)
        audience = options.get("audience", "it")
        if not images or audience not in AUDIENCES:
            reply = {"error": f"send 1-6 keyframes as images; audience is one of {sorted(AUDIENCES)}"}
        else:
            result = await describe_gap(
                [data for data, _ in images[:6]],
                int(options.get("words", DEFAULT_WORDS)),
                audience,
                before=str(options.get("before", "")),
                after=str(options.get("after", "")),
                draft=str(options.get("draft", "")),
                focus=str(options.get("focus", "")),
                mime_type=images[0][1],
            )
            reply = asdict(result)
        yield Event(
            author=self.name,
            invocation_id=ctx.invocation_id,
            content=types.Content(
                role="model", parts=[types.Part(text=json.dumps(reply, ensure_ascii=False))]
            ),
        )


agent = DescribeFramesAgent(
    name="sottovoce",
    description=(
        "Writes one line of audio description for the keyframes of a pause in the "
        "dialogue, has a second vision model check every claim in it against the "
        "frames, and returns the line with each claim's verdict. Vision models run "
        "on AMD Instinct GPUs through AMD Token Factory."
    ),
)


async def build_a2a(public_url: str) -> Starlette:
    """An A2A app serving /a2a and /a2a/.well-known/agent-card.json.

    Its routes appear once its lifespan has run.
    """
    card = await AgentCardBuilder(agent=agent, rpc_url=f"{public_url.rstrip('/')}/a2a").build()
    return to_a2a(agent, agent_card=card, rpc_path="a2a")
