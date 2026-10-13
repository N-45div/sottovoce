"""A tiny OpenAI-compatible server on localhost that replays scripted replies."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakeLLM:
    """Answers /chat/completions with `reply(model, body)` and records every request."""

    def __init__(self, reply: Callable[[str, dict], str]):
        self.reply = reply
        self.requests: list[dict] = []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802 - http.server naming
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                fake.requests.append(body)
                content = fake.reply(body["model"], body)
                payload = json.dumps({
                    "id": f"fake-{len(fake.requests)}",
                    "object": "chat.completion",
                    "created": 0,
                    "model": body["model"],
                    "choices": [{
                        "index": 0,
                        "message": {"role": "assistant", "content": content},
                        "finish_reason": "stop",
                    }],
                    "usage": {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110},
                }).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}/v1"

    def calls(self, model: str) -> list[dict]:
        return [r for r in self.requests if r["model"] == model]

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def system_text(body: dict) -> str:
    return " ".join(
        m["content"] if isinstance(m["content"], str) else json.dumps(m["content"])
        for m in body["messages"]
        if m["role"] in ("system", "developer")
    )
