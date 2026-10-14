"""The web API against a real finished job (the Italian Tears of Steel run)."""

import json
import shutil

import pytest
from fastapi.testclient import TestClient

from sottovoce import server

from media import CLIP, RUN
JOB = "0123456789ab"

pytestmark = pytest.mark.skipif(not (RUN / "script.json").exists(), reason="needs a finished run")


@pytest.fixture
def client(tmp_path, monkeypatch):
    job_dir = tmp_path / "jobs" / JOB
    shutil.copytree(RUN, job_dir)
    shutil.copy(CLIP, job_dir / "source.mp4")
    (job_dir / "job.json").write_text(json.dumps(
        {"id": JOB, "title": "Tears of Steel", "audience": "it", "status": "done", "error": ""}
    ))
    monkeypatch.setattr(server, "DATA", tmp_path)
    server.jobs.clear()
    with TestClient(server.app) as c:
        yield c


def test_library_lists_the_finished_job(client):
    assert client.get("/api/jobs").json() == [
        {"id": JOB, "title": "Tears of Steel", "audience": "it", "status": "done"}
    ]


def test_job_reports_lines_and_what_they_cost(client):
    job = client.get(f"/api/jobs/{JOB}").json()
    assert job["status"] == "done"
    assert len(job["script"]["cues"]) == 16
    assert 0 < job["cost_per_minute"] < 0.01


def test_only_known_files_are_served(client):
    assert client.get(f"/files/{JOB}/vtt").text.startswith("WEBVTT")
    assert client.get(f"/files/{JOB}/job.json").status_code == 404
    assert client.get(f"/files/{JOB}/..%2Fjob.json").status_code == 404
    assert client.get("/files/nope/vtt").status_code == 404


def test_a_person_can_approve_a_line(client):
    cues = client.get(f"/api/jobs/{JOB}").json()["script"]["cues"]
    index = next(i for i, c in enumerate(cues) if c["status"] == "needs_review")
    assert client.post(f"/api/jobs/{JOB}/cues/{index}/approve").json()["status"] == "approved"
    assert client.get(f"/api/jobs/{JOB}").json()["script"]["cues"][index]["status"] == "approved"


def test_editing_a_missing_line_is_a_404(client):
    assert client.post(f"/api/jobs/{JOB}/cues/99", json={"line": "x"}).status_code == 404


def test_a_file_that_is_not_a_video_is_refused(client):
    response = client.post(
        "/api/jobs", files={"video": ("notes.mp4", b"not a video", "video/mp4")}, data={"audience": "it"}
    )
    assert response.status_code == 400


def test_an_unknown_audience_is_refused(client):
    response = client.post(
        "/api/jobs", files={"video": ("a.mp4", b"x", "video/mp4")}, data={"audience": "fr"}
    )
    assert response.status_code == 400


def test_a_refused_upload_leaves_nothing_behind(client):
    client.post("/api/jobs", files={"video": ("x.mp4", b"junk", "video/mp4")}, data={"audience": "it"})
    assert [p.name for p in (server.DATA / "jobs").iterdir()] == [JOB]


def test_a2a_agent_card_points_at_the_a2a_route(client):
    card = client.get("/a2a/.well-known/agent-card.json").json()
    assert card["name"] == "sottovoce"
    assert card["supportedInterfaces"][0]["url"].endswith("/a2a")
    assert "AMD" in card["description"]


def test_cost_uses_the_models_that_wrote_the_job(client):
    script_path = server.DATA / "jobs" / JOB / "script.json"
    script = json.loads(script_path.read_text(encoding="utf-8"))
    script["models"] = {"describer": "DeepSeek-V4-Flash-Vision-Exp", "verifier": "Qwen3.8-27B"}
    script_path.write_text(json.dumps(script), encoding="utf-8")
    deepseek = client.get(f"/api/jobs/{JOB}").json()

    script["models"] = {"describer": "Gemma-4-31B-IT", "verifier": "Qwen3.8-27B"}
    script_path.write_text(json.dumps(script), encoding="utf-8")
    gemma = client.get(f"/api/jobs/{JOB}").json()

    assert deepseek["models"]["describer"] == "DeepSeek-V4-Flash-Vision-Exp"
    assert deepseek["cost_usd"] > gemma["cost_usd"] > 0


def test_a_single_voiced_line_can_be_fetched_and_nothing_else(client):
    response = client.get(f"/files/{JOB}/audio/cue_001.wav")
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    assert response.content[:4] == b"RIFF"
    assert client.get(f"/files/{JOB}/audio/..%2Fscript.json").status_code == 404
    assert client.get(f"/files/{JOB}/audio/job.json").status_code == 404


def test_every_page_and_its_assets_are_served(client):
    for path in ("/", "/app/"):
        page = client.get(path)
        assert page.status_code == 200, path
        assert "text/html" in page.headers["content-type"]
        assert "Describe a lesson" in page.text
    for asset in ("/assets/site.css", "/assets/landing.css", "/assets/landing.js", "/assets/app.css",
                  "/assets/app.js", "/assets/logo.svg", "/assets/hero-poster.jpg", "/assets/evidence.json"):
        assert client.get(asset).status_code == 200, asset
