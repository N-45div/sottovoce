"""Build the Evolus "Lesson notes" workflow and its notes agent (an existing workflow of that name
is deleted; the agent is reused from desk.json).

    python build_notes.py

  Write the notes (AgentCall: the notes agent, Gemma 4 on AMD, for the lesson's language and age)
    -> Translate the notes (AiTool translate, into the other language)
    -> Put them together (Script)
    -> Result (Output)

Sottovoce runs it on every described lesson's transcript, with the parameters language,
other_language and age. The notes agent is also a sub-agent of the desk agent.
"""
import json
import os

from mcp import Client

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "desk.json")
NAME = "Lesson notes"
state = json.load(open(STATE))
c = Client()


def items(x):
    return (x.get("items") or x.get("data") or []) if isinstance(x, dict) else (x or [])


if not state.get("notes_agent"):
    a = c.call("create_agent", {"requestJson": json.dumps({
        "name": "Sottovoce lesson notes", "language": "en", "tags": ["sottovoce"],
        "description": "Writes easy-read lesson notes for a blind or low-vision child from a described lesson's transcript.",
        "prompt": open(os.path.join(HERE, "notes_prompt.md"), encoding="utf-8").read().strip(),
        "modelKey": "own/gemma-4-31b-it", "fallbackModelKeys": ["own/deepseek-v4.1-flash"],
    })})
    state["notes_agent"] = a.get("agentId") or a.get("id")
    c.call("add_subagent", {"orchestratorAgentId": state["agent"], "subAgentId": state["notes_agent"], "subAgentName": "lesson_notes",
                            "promptDescription": "Writes easy-read notes for a blind or low-vision child from a described lesson's transcript. "
                                                 "Give it the transcript, the language (en or it) and the child's age band."})
    json.dump(state, open(STATE, "w"), indent=1)
    print("notes agent", state["notes_agent"], "(sub-agent of the desk)")

for w in items(c.call("list_workflows", {})):
    if w.get("name") == NAME:
        c.call("delete_workflow", {"workflowId": w["id"]})
        print("deleted the old workflow", w["id"])

wf = c.call("create_workflow", {"requestJson": json.dumps({
    "name": NAME, "isActive": True, "tags": ["sottovoce"],
    "description": "A described lesson's transcript becomes easy-read notes for the child, and their translation for the family.",
    "parameters": [
        {"name": "language", "description": "The child's language", "required": True, "allowedValues": ["en", "it"]},
        {"name": "other_language", "description": "The language of the translation", "required": True, "allowedValues": ["en", "it"]},
        {"name": "age", "description": "The child's age band", "required": True, "allowedValues": ["5-8", "8-13", "14-18"]},
    ],
    "enableAuditKpi": False, "auditCompareBaseline": 0, "multiFileMode": 0, "emailProviderType": 0,
    "emailPollingEnabled": False, "emailPollingIntervalSeconds": 300, "emailMarkAsRead": False, "imapPort": 993, "imapUseSsl": True,
})})
wid = wf["id"]
print("workflow", wid)


def step(name, kind, sources=(), config=None, **extra):
    body = {"name": name, "stepType": kind, **extra}
    if sources:
        body["inputStepIds"] = list(sources)
        body.setdefault("inputMode", "PreviousOutput")
    if config is not None:
        body["stepConfigJson"] = json.dumps(config)
    s = c.call("add_workflow_step", {"workflowId": wid, "requestJson": json.dumps(body)})
    print(f"  {kind:<9} {name}: {s['id']}")
    return s["id"]


write = step("Write the notes", "AgentCall", agentId=state["notes_agent"],
             prompt="Language: {{param:language}} (en = English, it = Italian). The child is aged {{param:age}}. The described lesson:")
translate = step("Translate the notes", "AiTool", [write], {"toolSlug": "translate", "options": {"target": "{{param:other_language}}", "style": "natural"}})
together = step("Put them together", "Script", [write, translate], {"script": (
    "return { notes: sources[0].text, translation: sources[1].text, language: params.language, "
    "other_language: params.other_language, age: params.age };")})
out = step("Result", "Output", [together])
state.update({"notes_workflow": wid, "notes_steps": {"write": write, "translate": translate, "together": together, "output": out}})
json.dump(state, open(STATE, "w"), indent=1)
