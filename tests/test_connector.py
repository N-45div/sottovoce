"""The MCP connector an agent uses to run Sottovoce, called the way an MCP client calls it."""

import json

import pytest
from fastapi.testclient import TestClient

from sottovoce import server

JOB = "0123456789ab"


@pytest.fixture
def client(tmp_path, monkeypatch):
    job_dir = tmp_path / "jobs" / JOB
    job_dir.mkdir(parents=True)
    (job_dir / "job.json").write_text(json.dumps({"id": JOB, "title": "Moon Phases", "audience": "en", "status": "done", "error": ""}))
    (job_dir / "transcript.txt").write_text("Described lesson: Moon Phases\n\n[00:00] On screen: The word STEM.\n", encoding="utf-8")
    monkeypatch.setattr(server, "DATA", tmp_path)
    monkeypatch.setattr(server.desk, "NOTES", "")  # no Evolus calls from these tests
    server.jobs.clear()
    with TestClient(server.app) as c:
        yield c


def rpc(client, method, params=None, host="testserver"):
    r = client.post("/mcp/", json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
                    headers={"Accept": "application/json, text/event-stream", "Host": host})
    return r


def call(client, tool, **arguments):
    body = rpc(client, "tools/call", {"name": tool, "arguments": arguments}).json()["result"]
    text = "".join(part.get("text", "") for part in body["content"])
    return body.get("isError", False), text


def test_an_agent_sees_the_five_tools(client):
    r = rpc(client, "tools/list")
    assert r.status_code == 200
    names = {t["name"] for t in r.json()["result"]["tools"]}
    assert names == {"describe_lesson", "lesson_status", "lines_to_review", "lesson_transcript", "list_lessons"}


def test_an_agent_can_list_lessons_and_read_one_as_text(client):
    error, text = call(client, "list_lessons")
    assert not error and JOB in text and "Moon Phases" in text
    error, text = call(client, "lesson_transcript", lesson_id=JOB)
    assert not error and "On screen: The word STEM." in text


def test_an_unknown_lesson_is_an_error_the_agent_can_read(client):
    error, text = call(client, "lesson_status", lesson_id="ffffffffffff")
    assert error and "no lesson" in text


def test_a_lesson_starts_only_from_an_https_link(client):
    error, text = call(client, "describe_lesson", video_url="http://example.org/a.mp4", language="en", age="8-13")
    assert error and "https" in text
    assert list(server.jobs) == [JOB]  # nothing was started


def test_only_our_own_hosts_reach_the_connector(client):
    assert rpc(client, "tools/list", host="evil.example").status_code in (400, 421)
