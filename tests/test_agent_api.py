import base64
import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from google.genai import types

from sottovoce import server
from sottovoce.agent_api import read_request
from sottovoce.shots import extract_frame

CLIP = Path(r"C:\Users\DivijN\sottovoce-media\tos_bridge_150s.mp4")


def test_request_splits_images_from_options():
    content = types.Content(role="user", parts=[
        types.Part.from_bytes(data=b"jpeg", mime_type="image/jpeg"),
        types.Part(text='Please describe: {"words": 9, "audience": "en"}'),
    ])
    assert read_request(content) == ([(b"jpeg", "image/jpeg")], {"words": 9, "audience": "en"})


def test_request_without_options_or_with_broken_json_gets_defaults():
    content = types.Content(role="user", parts=[types.Part(text="describe {this")])
    assert read_request(content) == ([], {})
    assert read_request(None) == ([], {})


@pytest.mark.skipif(
    not (os.environ.get("AMD_API_KEY") and CLIP.exists()), reason="needs AMD_API_KEY and the test clip"
)
def test_another_agent_gets_a_checked_line_over_a2a(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DATA", tmp_path)
    frames = [extract_frame(CLIP, t) for t in (118.8, 121.0)]
    request = {
        "jsonrpc": "2.0", "id": 1, "method": "SendMessage",
        "params": {"message": {
            "messageId": "test-1", "role": "ROLE_USER",
            "parts": [
                *({"raw": base64.b64encode(f).decode(), "mediaType": "image/jpeg"} for f in frames),
                {"text": json.dumps({"words": 12, "audience": "en"})},
            ],
        }},
    }
    with TestClient(server.app) as client:
        task = client.post("/a2a", json=request, headers={"A2A-Version": "1.0"}).json()["result"]["task"]

    assert task["status"]["state"] == "TASK_STATE_COMPLETED"
    reply = json.loads(task["artifacts"][0]["parts"][0]["text"])
    assert reply["line"]
    assert reply["claims"]
    assert reply["status"] in ("verified", "needs_review")
