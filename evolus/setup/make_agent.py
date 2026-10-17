"""Create the desk agent on the workspace's own model, attach the library, give it the "Lesson request"
output structure; ids go to desk.json.

    python make_agent.py own/gemma-4-31b-it own/deepseek-v4.1-flash   # the model, then fallbacks
"""
import json
import os
import sys

from mcp import Client

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "desk.json")
state = json.load(open(STATE)) if os.path.exists(STATE) else {}
c = Client()
prompt = open(os.path.join(HERE, "agent_prompt.md"), encoding="utf-8").read().strip()
model, *fallbacks = sys.argv[1:]
req = {"name": "Sottovoce request desk", "language": "en", "isChatVisible": True, "tags": ["sottovoce"], "prompt": prompt,
       "description": "Turns a teacher's request into a described lesson, and answers questions about described lessons from the knowledge library.",
       "modelKey": model, "fallbackModelKeys": fallbacks or None}
if state.get("agent"):
    a = c.call("update_agent", {"agentId": state["agent"], "requestJson": json.dumps(req)})
else:
    a = c.call("create_agent", {"requestJson": json.dumps(req)})
state["agent"] = a.get("agentId") or a.get("id") or state.get("agent")
if not state.get("memory_attached"):
    c.call("attach_memory_to_agent", {"agentId": state["agent"], "memoryId": state["memory"]})
    state["memory_attached"] = True
if not state.get("structure"):
    # What "Read the request" fills in: only what the request says, the rest left empty.
    structure = {
        "title": "Lesson request", "canUseOCR": False, "maxCorrections": 2,
        "checkScript": open(os.path.join(HERE, "request_structure.js"), encoding="utf-8").read(),
        "structure": json.dumps({"video_url": "", "language": "", "age": "", "title": "", "needed_by": "", "email": "", "focus": ""}),
        "userPrompt": (
            "Fill in every field from the request, using only what it says; leave a field empty when the request does not give it. "
            "video_url: the https link to the video, copied exactly. "
            "language: the language the child listens in, en or it; if none is named, the language the request is written in. "
            "age: the child's age band, 5-8, 8-13 or 14-18, from an age or a class (year 2 or seconda elementare: 5-8; "
            "a 9-year-old or quarta elementare: 8-13; high school or liceo: 14-18). "
            "title: a short title for the lesson. needed_by: the date of the lesson, as written. "
            "email: the teacher's email, if given. focus: what the teacher wants described with care. "
            "Never copy a child's name into any field."
        ),
    }
    out = c.call("create_output_structure", {"agentId": state["agent"], "format": "json", "structureJson": json.dumps(structure)})
    state["structure"] = out.get("id") or out.get("outputStructureId")
json.dump(state, open(STATE, "w"), indent=1)
print("agent", state["agent"], "on", model, "fallbacks", fallbacks, "structure", state.get("structure"))
