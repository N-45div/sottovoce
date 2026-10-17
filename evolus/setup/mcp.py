"""A minimal client for the Evolus MCP server (streamable HTTP): list tools, or call one.

    python mcp.py tools
    python mcp.py schema TOOL_NAME...
    python mcp.py call TOOL_NAME '{"arg": "value"}'     (or @args.json)

$AMD_KEY in the arguments becomes AMD_API_KEY; neither key ever comes back in the output.
Needs EVOLUS_API_KEY and EVOLUS_APP_ID.
"""
import json
import os
import sys
import time

import requests

KEY = os.environ["EVOLUS_API_KEY"].strip()
APP = os.environ["EVOLUS_APP_ID"].strip()
AMD = os.environ.get("AMD_API_KEY", "").strip() or "unused"
URL = "https://api.evolus.ai/mcp"
HEADERS = {"X-ApiKey": KEY, "X-Application-Id": APP, "Content-Type": "application/json", "Accept": "application/json, text/event-stream"}


class Client:
    def __init__(self):
        self.s = requests.Session()
        self.headers = dict(HEADERS)
        self.n = 0
        self.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "sottovoce", "version": "1"}})
        self.s.post(URL, json={"jsonrpc": "2.0", "method": "notifications/initialized"}, headers=self.headers, timeout=60)

    def rpc(self, method, params=None):
        self.n += 1
        for wait in (5, 15, 30, 60, 0):
            r = self.s.post(URL, json={"jsonrpc": "2.0", "id": self.n, "method": method, "params": params or {}}, headers=self.headers, timeout=180)
            if r.status_code != 429 or not wait:
                break
            time.sleep(int(r.headers.get("retry-after") or wait))
        r.raise_for_status()
        if "mcp-session-id" in r.headers:
            self.headers["mcp-session-id"] = r.headers["mcp-session-id"]
        if r.headers.get("content-type", "").startswith("text/event-stream"):
            for line in r.text.splitlines():
                if line.startswith("data:"):
                    return json.loads(line[5:])
            return {}
        return r.json() if r.text else {}

    def tools(self):
        return self.rpc("tools/list").get("result", {}).get("tools", [])

    def call(self, name, args):
        """The tool's text answer, parsed as JSON when it is JSON."""
        out = self.rpc("tools/call", {"name": name, "arguments": json.loads(json.dumps(args).replace("$AMD_KEY", AMD))})
        result = out.get("result", out)
        text = "".join(c.get("text", "") for c in result.get("content", [])) if isinstance(result, dict) else str(result)
        if isinstance(result, dict) and result.get("isError"):
            raise RuntimeError(f"{name}: {redact(text)[:2000]}")
        try:
            return json.loads(text)
        except ValueError:
            return text


def redact(text):
    for secret in (AMD, KEY):
        text = text.replace(secret, "***")
    return text


if __name__ == "__main__":
    c = Client()
    if sys.argv[1] == "tools":
        tools = c.tools()
        print(len(tools), "tools")
        for t in tools:
            print("-", t["name"], ":", (t.get("description") or "").split("\n")[0][:150])
    elif sys.argv[1] == "schema":
        for t in c.tools():
            if t["name"] in sys.argv[2:]:
                print(t["name"], json.dumps(t.get("inputSchema"), indent=1)[:3000])
    elif sys.argv[1] == "call":
        raw = sys.argv[3] if len(sys.argv) > 3 else "{}"
        if raw.startswith("@"):
            raw = open(raw[1:], encoding="utf-8").read()
        out = c.call(sys.argv[2], json.loads(raw))
        print(redact(json.dumps(out, indent=1, ensure_ascii=False))[:int(os.environ.get("MCP_MAX", "6000"))])
