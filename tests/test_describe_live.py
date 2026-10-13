"""Live tests: real frames from a real film, real models on AMD Token Factory.

They need AMD_API_KEY and the test clip, and are skipped without them.
"""

import asyncio
import os
from pathlib import Path

import pytest

from sottovoce.describe import count_words, describe_gap
from sottovoce.shots import extract_frame

CLIP = Path(r"C:\Users\DivijN\sottovoce-media\tos_bridge_150s.mp4")
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


def test_planted_error_is_caught_and_rewritten():
    draft = "Un elefante rosa balla su un palco illuminato."
    frames = [extract_frame(CLIP, BRIDGE)]
    result = asyncio.run(describe_gap(frames, words=14, audience="it", draft=draft))

    first = result.history[0]
    assert first["line"] == draft
    assert first["problems"]
    assert result.line != draft
    assert "describer" in result.tokens
