"""Live tests: the real Evolus workflow and desk agent (Gemma 4 on AMD Token Factory).

They need EVOLUS_API_KEY, EVOLUS_APP_ID, EVOLUS_DESK_WORKFLOW and EVOLUS_DESK_AGENT, and are
skipped without them. No lesson is started: the request leaves out the age.
"""

import asyncio
import time

import pytest

from sottovoce import desk

pytestmark = pytest.mark.skipif(not desk.ready(), reason="needs the Evolus desk settings")


def test_a_request_without_an_age_gets_one_reply_asking_for_it():
    async def run():
        execution = await desk.start("Hi, could you describe this lesson for my class? https://example.org/moon-phases.mp4")
        deadline = time.monotonic() + 240
        while time.monotonic() < deadline:
            await asyncio.sleep(3)
            result = await desk.follow(execution)
            if result.status in ("Completed", "Failed"):
                return result
        raise TimeoutError(execution)

    result = asyncio.run(run())
    assert result.status == "Completed", result.error
    assert result.result["status"] == "needs_info"
    assert result.result["missing"] == ["age"]  # English: the language the request is written in


def test_a_question_is_answered_from_the_knowledge_library():
    answer, _ = asyncio.run(desk.ask("Which WCAG success criterion asks for extended audio description?"))
    assert "1.2.7" in answer
