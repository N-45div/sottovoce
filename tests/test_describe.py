import pytest

from sottovoce.describe import Settings, clean_line, count_words, parse_check


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
