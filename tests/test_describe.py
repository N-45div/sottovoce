import pytest

from sottovoce.describe import Settings, clean_line, count_words, judge, parse_check


def test_parse_check_reads_json_inside_code_fences():
    check = parse_check('```json\n{"claims": [{"text": "a", "verdict": "supported"}]}\n```')
    assert check.claims[0].verdict == "supported"


def test_parse_check_rejects_unknown_verdicts():
    with pytest.raises(ValueError):
        parse_check('{"claims": [{"text": "a", "verdict": "maybe"}]}')


def test_parse_check_rejects_prose():
    with pytest.raises(ValueError):
        parse_check("I think it looks fine.")


def test_clean_line_and_count_words():
    assert clean_line('\n  **"L\'uomo apre la porta."**\nextra') == "L'uomo apre la porta."
    assert count_words("L'uomo apre la porta.") == 4


def test_settings_default_to_token_factory(monkeypatch):
    monkeypatch.setenv("AMD_API_KEY", "k")
    monkeypatch.setenv("SOTTOVOCE_DESCRIBER_BASE", "http://gpu:8000/v1")
    settings = Settings.from_env()

    assert settings.describer.api_base == "http://gpu:8000/v1"
    assert settings.verifier.api_base.startswith("https://developer.amd.com.cn")
    assert settings.verifier.extra_body == {"reasoning_effort": "low"}


def test_settings_need_a_key(monkeypatch):
    monkeypatch.delenv("AMD_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        Settings.from_env()


SUPPORTED = '{"claims": [{"text": "un ponte", "verdict": "supported"}]}'


def test_judge_passes_a_supported_line_within_budget():
    check, problems = judge("Un uomo su un ponte.", SUPPORTED, limit=5)
    assert problems == []
    assert len(check.claims) == 1


def test_judge_lets_a_line_one_word_over_through():
    assert judge("Un uomo cammina su un ponte.", SUPPORTED, limit=5)[1] == []


def test_judge_flags_a_line_far_over_budget():
    problems = judge("Un uomo alto cammina piano su un ponte di ferro.", SUPPORTED, limit=5)[1]
    assert problems == ["the line has 10 words, the limit is 5"]


def test_judge_lists_each_unsupported_claim():
    reply = (
        '{"claims": [{"text": "un ponte", "verdict": "supported"},'
        ' {"text": "un elefante", "verdict": "contradicted"},'
        ' {"text": "di notte", "verdict": "not_visible"}]}'
    )
    problems = judge("Un elefante su un ponte di notte.", reply, limit=10)[1]
    assert problems == ['"un elefante" is contradicted', '"di notte" is not visible']


def test_backups_wrap_the_model_in_an_adk_fallback(monkeypatch):
    from google.adk.models import FallbackModel
    from google.adk.models.lite_llm import LiteLlm

    monkeypatch.setenv("AMD_API_KEY", "k")
    settings = Settings.from_env()

    assert settings.describer.backups == ("DeepSeek-V4-Flash-Vision-Exp",)
    assert isinstance(settings.describer.llm(), FallbackModel)
    monkeypatch.setenv("SOTTOVOCE_DESCRIBER_BACKUPS", "")
    assert isinstance(Settings.from_env().describer.llm(), LiteLlm)
