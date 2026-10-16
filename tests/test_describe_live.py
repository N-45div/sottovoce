"""Live tests: real frames from a real film, real models on AMD Token Factory.

They need AMD_API_KEY and the test clip, and are skipped without them.
"""

import asyncio
import os
from dataclasses import replace

import pytest

from sottovoce.describe import Settings, count_words, describe_gap
from sottovoce.shots import extract_frame

from media import CLIP
BRIDGE = 30.0  # Tears of Steel: a couple argue on a bridge in Amsterdam

pytestmark = pytest.mark.skipif(
    not (os.environ.get("AMD_API_KEY") and CLIP.exists()),
    reason="needs AMD_API_KEY and the Tears of Steel test clip",
)


def test_real_frames_are_described_and_checked():
    frames = [extract_frame(CLIP, BRIDGE), extract_frame(CLIP, BRIDGE + 2)]
    result = asyncio.run(describe_gap(frames, words=14, audience="it"))

    assert result.line
    assert result.claims
    assert result.tokens["describer"][1] > 0
    assert result.tokens["verifier"][1] > 0
    if result.status == "verified":
        assert count_words(result.line) <= 14
        assert all(c["verdict"] == "supported" for c in result.claims)


def test_a_model_token_factory_no_longer_serves_falls_back_to_the_next():
    # Gemma-4-31B-IT was removed from Token Factory on Oct 16 and answers 400.
    settings = Settings.from_env()
    gone = replace(settings.describer, model="Gemma-4-31B-IT", backups=("DeepSeek-V4-Flash-Vision-Exp",))
    frames = [extract_frame(CLIP, BRIDGE)]
    result = asyncio.run(describe_gap(frames, words=14, audience="en", settings=replace(settings, describer=gone)))

    assert result.line
    assert result.tokens["describer"][1] > 0


@pytest.mark.skipif(not os.environ.get("SOTTOVOCE_VERTEX_PROJECT"), reason="needs SOTTOVOCE_VERTEX_PROJECT")
def test_gemma_on_vertex_writes_and_the_line_says_who_wrote_it():
    settings = Settings.from_env()
    frames = [extract_frame(CLIP, BRIDGE)]
    result = asyncio.run(describe_gap(frames, words=14, audience="en", settings=settings))

    assert settings.describer.model == "google/gemma-4-26b-a4b-it-maas"
    assert result.line
    # Gemma, or a DeepSeek backup on AMD when Vertex's shared queue is full, never a guess.
    assert result.models["describer"] in (settings.describer.model, *settings.describer.backups)
    assert result.models["verifier"].startswith("Qwen3.8")


def test_planted_error_is_caught_and_rewritten():
    draft = "Un elefante rosa balla su un palco illuminato."
    frames = [extract_frame(CLIP, BRIDGE)]
    result = asyncio.run(describe_gap(frames, words=14, audience="it", draft=draft))

    first = result.history[0]
    assert first["line"] == draft
    assert first["problems"]
    assert result.line != draft
    assert "describer" in result.tokens
