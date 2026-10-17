"""Build the Evolus "Describe a lesson" workflow from scratch (an existing one of that name is deleted).

    python build_desk.py            # with the agent step in front, if desk.json names an agent
    python build_desk.py --no-agent # input is the agent's JSON reading, for testing the rest

  Read the request (AgentCall: the desk agent, Gemma 4 on AMD, structured output)
    -> Check the request (Script: check.js)
    -> Ready? (If)
         true -> Start the described lesson (Webhook: POST Sottovoce /api/jobs with the video link)
    -> Reply to the teacher (Script: reply.js, reads the check and the start)
    -> Result (Output)

The ids go to desk.json.
"""
import json
import os
import sys

from mcp import Client

HERE = os.path.dirname(os.path.abspath(__file__))
NAME = "Describe a lesson"
SOTTOVOCE = "https://sottovoce-ai.web.app/api/jobs"
state = json.load(open(os.path.join(HERE, "desk.json"))) if os.path.exists(os.path.join(HERE, "desk.json")) else {}
agent = None if "--no-agent" in sys.argv else state.get("agent")
c = Client()


def items(x):
    return (x.get("items") or x.get("data") or []) if isinstance(x, dict) else (x or [])


for w in items(c.call("list_workflows", {})):
    if w.get("name") == NAME:
        c.call("delete_workflow", {"workflowId": w["id"]})
        print("deleted the old workflow", w["id"])

wf = c.call("create_workflow", {"requestJson": json.dumps({
    "name": NAME, "isActive": True, "tags": ["sottovoce"],
    "description": "A teacher's request in plain words becomes a described lesson on Sottovoce, or one short reply asking for what is missing.",
    "enableAuditKpi": False, "auditCompareBaseline": 0, "multiFileMode": 0, "emailProviderType": 0,
    "emailPollingEnabled": False, "emailPollingIntervalSeconds": 300, "emailMarkAsRead": False, "imapPort": 993, "imapUseSsl": True,
})})
wid = wf["id"]
print("workflow", wid)


def step(name, kind, sources=(), branches=None, config=None, **extra):
    body = {"name": name, "stepType": kind, **extra}
    if sources:
        body["inputStepIds"] = list(sources)
        body.setdefault("inputMode", "PreviousOutput")
    if branches:
        body["inputBranches"] = branches
    if config is not None:
        body["stepConfigJson"] = json.dumps(config)
    s = c.call("add_workflow_step", {"workflowId": wid, "requestJson": json.dumps(body)})
    print(f"  {kind:<8} {name}: {s['id']}")
    return s["id"]


read = step("Read the request", "AgentCall", agentId=agent, outputStructureId=state["structure"],
            prompt="A teacher wrote this request. Read it and fill in every field.") if agent else None
check = step("Check the request", "Script", [read] if read else [], config={"script": open(os.path.join(HERE, "check.js"), encoding="utf-8").read()})
ready = step("Ready?", "If", [check], config={"mode": "guided", "conditions": [{"field": "ready", "operator": "isTrue"}], "combine": "and"})
template = json.dumps({"video_url": f"{{{{step:{check}.video_url}}}}", "audience": f"{{{{step:{check}.audience}}}}", "title": f"{{{{step:{check}.title}}}}"})
start = step("Start the described lesson", "Webhook", [ready], {ready: "true"},
             config={"method": "POST", "url": SOTTOVOCE, "bodyMode": "template", "bodyTemplate": template, "sendAs": "form", "responseType": "json",
                     "responseStructure": json.dumps({"id": "0123456789ab"})})
reply = step("Reply to the teacher", "Script", [check, start], config={"script": open(os.path.join(HERE, "reply.js"), encoding="utf-8").read()})
out = step("Result", "Output", [reply])
state.update({"workflow": wid, "steps": {"read": read, "check": check, "ready": ready, "start": start, "reply": reply, "output": out}})
json.dump(state, open(os.path.join(HERE, "desk.json"), "w"), indent=1)
