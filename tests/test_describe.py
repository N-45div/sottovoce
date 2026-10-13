import asyncio
import base64
import json

import pytest

from fake_llm import FakeLLM, system_text
from sottovoce.describe import Settings, clean_line, count_words, describe_gap, parse_check

DESCRIBER, VERIFIER = "Gemma-4-31B-IT", "Qwen3.8-27B"
FRAME = b"\x89PNG fake frame bytes"
LINE = "Un quadrato rosso accanto a un rettangolo giallo."


def verdicts(*pairs):
    return json.dumps({"claims": [{"text": t, "verdict": v, "frame": 1} for t, v in pairs]})


ALL_SUPPORTED = verdicts(("quadrato rosso", "supported"), ("rettangolo giallo", "supported"))


def run(fake, **kwargs):
    settings = Settings(fake.base_url, "test-key", DESCRIBER, VERIFIER)
    kwargs.setdefault("words", 12)
    return asyncio.run(describe_gap([FRAME], settings=settings, mime_type="image/png", **kwargs))


@pytest.fixture
def scripted():
    fakes = []

    def make(describer_lines, verifier_replies):
        lines, replies = iter(describer_lines), iter(verifier_replies)
        fake = FakeLLM(lambda model, body: next(lines) if model == DESCRIBER else next(replies))
        fakes.append(fake)
        return fake

    yield make
    for fake in fakes:
        fake.close()


def test_supported_line_is_verified_in_one_round(scripted):
    fake = scripted([LINE], [ALL_SUPPORTED])
    result = run(fake, before="Andiamo.", after="Aspetta!")

    assert result.status == "verified"
    assert result.rounds == 1
    assert result.line == LINE
    assert result.problems == []
    assert set(result.tokens) == {"describer", "verifier"}

    request = fake.calls(DESCRIBER)[0]
    images = [
        part["image_url"]["url"]
        for message in request["messages"]
        if isinstance(message["content"], list)
        for part in message["content"]
        if part.get("type") == "image_url"
    ]
    assert images == ["data:image/png;base64," + base64.b64encode(FRAME).decode()]
    assert "Andiamo." in system_text(request)
    assert "at most 12 words" in system_text(request)
    assert LINE in system_text(fake.calls(VERIFIER)[0])


def test_contradicted_claim_is_sent_back_and_fixed(scripted):
    wrong = "Un quadrato verde accanto a un rettangolo giallo."
    fake = scripted(
        [wrong, LINE],
        [verdicts(("quadrato verde", "contradicted")), ALL_SUPPORTED],
    )
    result = run(fake)

    assert result.status == "verified"
    assert result.rounds == 2
    assert result.line == LINE
    feedback = system_text(fake.calls(DESCRIBER)[1])
    assert '"quadrato verde" is contradicted' in feedback
    assert wrong in feedback


def test_line_over_the_word_budget_is_shortened(scripted):
    long_line = "Un grande quadrato rosso brillante sta fermo accanto a un alto rettangolo giallo."
    fake = scripted([long_line, LINE], [ALL_SUPPORTED, ALL_SUPPORTED])
    result = run(fake, words=8)

    assert result.rounds == 2
    assert result.status == "verified"
    assert "the limit is 8" in system_text(fake.calls(DESCRIBER)[1])


def test_unfixable_line_goes_to_a_person(scripted):
    fake = scripted([LINE, LINE], [verdicts(("quadrato rosso", "not_visible"))] * 2)
    result = run(fake, max_rounds=2)

    assert result.status == "needs_review"
    assert result.rounds == 2
    assert result.problems == ['"quadrato rosso" is not visible']


def test_unreadable_verifier_reply_never_counts_as_verified(scripted):
    fake = scripted([LINE], ["I think it looks fine."])
    result = run(fake, max_rounds=1)

    assert result.status == "needs_review"
    assert "verifier reply unreadable" in result.problems[0]


def test_parse_check_reads_json_inside_code_fences():
    check = parse_check('```json\n{"claims": [{"text": "a", "verdict": "supported"}]}\n```')
    assert check.claims[0].verdict == "supported"


def test_parse_check_rejects_unknown_verdicts():
    with pytest.raises(ValueError):
        parse_check('{"claims": [{"text": "a", "verdict": "maybe"}]}')


def test_clean_line_and_count_words():
    assert clean_line('\n  **"L\'uomo apre la porta."**\nextra') == "L'uomo apre la porta."
    assert count_words("L'uomo apre la porta.") == 4
