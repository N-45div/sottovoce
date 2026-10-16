"""The request desk's own rules, before anything reaches Evolus."""

import pytest
from fastapi.testclient import TestClient

from sottovoce import desk, server


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DATA", tmp_path)
    server.jobs.clear()
    with TestClient(server.app) as c:
        yield c


@pytest.fixture
def set_up(monkeypatch):
    for name in ("KEY", "APP", "WORKFLOW", "AGENT"):
        monkeypatch.setattr(desk, name, f"not-a-real-{name.lower()}")


def test_without_a_key_the_desk_says_it_is_not_set_up(client, monkeypatch):
    monkeypatch.setattr(desk, "KEY", "")
    assert client.post("/api/desk", data={"text": "hello"}).status_code == 503
    assert client.get("/api/desk/00000000-0000-0000-0000-000000000000").status_code == 503


def test_an_empty_message_is_refused(client, set_up):
    assert client.post("/api/desk", data={"text": "   "}).status_code == 400


def test_only_an_evolus_execution_id_is_followed(client, set_up):
    assert client.get("/api/desk/..%2F..%2Fagents").status_code == 404
    assert client.get("/api/desk/not-an-id").status_code == 404


@pytest.mark.parametrize("text, request_", [
    ("Please describe https://example.org/moon.mp4 for my 7-year-old", True),
    ("Descrivi questa lezione per Marco, 9 anni: https://example.org/lezione.mp4", True),
    ("Does ADA Title II require audio description?", False),
    ("the video is at http://example.org/a.mp4", False),  # only https links are fetched
])
def test_a_video_link_makes_a_request_and_anything_else_a_question(text, request_):
    assert desk.is_request(text) is request_


def test_a_failed_run_says_why_sottovoce_refused_the_video():
    error = "The endpoint step 'Start the described lesson' received HTTP 400: {\"detail\":\"not a video ffmpeg can read\"}"
    assert desk._reason(error) == "Sottovoce could not use the video: not a video ffmpeg can read."
    assert "try again" in desk._reason("Hangfire job timed out")
