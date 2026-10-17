"""Load the three knowledge docs into the Evolus library as clean chunks, one per ## section.

    python chunks.py      # creates the library on the first run; its id goes to desk.json

The URL importer reads anything that is not a PDF as an HTML page: raw markdown comes back
"no_text_found", and GitHub's page view comes back with the site's menus in every chunk. So each
doc is imported from its GitHub page (that gives the document its manifest), its chunks are
deleted, and every ## section is added by hand as "<doc title>: <section>". Failed imports are
removed. Run it again after editing a doc: its chunks are replaced.
"""
import json
import os
import re
import time

from mcp import Client

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "desk.json")
KNOWLEDGE = os.path.join(os.path.dirname(HERE), "knowledge")
PAGE = "https://github.com/N-45div/sottovoce/blob/main/evolus/knowledge/{}"
DOCS = {
    "Audio description rules for children": "accessibility-rules.md",
    "How Sottovoce works": "sottovoce-guide.md",
    "How the request desk handles a teacher's request": "request-desk.md",
}
DONE, FAILED = 2, 3


def items(x):
    return (x.get("items") or x.get("data") or []) if isinstance(x, dict) else (x or [])


def sections(path):
    text = open(path, encoding="utf-8").read()
    head, *rest = re.split(r"^## ", text, flags=re.M)
    title = head.splitlines()[0].lstrip("# ").strip()
    lede = "\n".join(head.splitlines()[1:]).strip()
    for part in rest:
        name, _, body = part.partition("\n")
        yield f"{title}: {name.strip()}", (lede + "\n\n" if lede else "") + body.strip()


c = Client()
state = json.load(open(STATE)) if os.path.exists(STATE) else {}
if not state.get("memory"):
    state["memory"] = c.call("create_simple_memory", {"requestJson": json.dumps({"name": "Sottovoce request desk", "type": 0})})["id"]
    json.dump(state, open(STATE, "w"), indent=1)
MEMORY = state["memory"]
docs = items(c.call("list_memory_documents", {"memoryId": MEMORY}))
for doc in docs:
    if doc.get("ingestionStatus") == FAILED or doc["title"] not in DOCS:
        c.call("delete_memory_document", {"memoryId": MEMORY, "documentId": doc["id"]})
        print("removed", doc["title"], doc.get("ingestionError") or "")
docs = {d["title"]: d for d in items(c.call("list_memory_documents", {"memoryId": MEMORY}))}

for title, name in DOCS.items():
    doc = docs.get(title)
    if not doc:
        doc = c.call("import_memory_document_url", {"memoryId": MEMORY, "requestJson": json.dumps({"title": title, "url": PAGE.format(name)})})
        for _ in range(30):
            if doc.get("ingestionStatus") in (DONE, FAILED):
                break
            time.sleep(5)
            doc = [d for d in items(c.call("list_memory_documents", {"memoryId": MEMORY})) if d["id"] == doc["id"]][0]
        if doc.get("ingestionStatus") != DONE:
            raise SystemExit(f"{title}: ingestion {doc.get('ingestionStatus')} {doc.get('ingestionError')}")
    ref = {"memoryId": MEMORY, "documentId": doc["id"]}
    old = items(c.call("list_memory_document_chunks", ref))
    for chunk in old:
        c.call("delete_memory_chunk", {**ref, "chunkId": chunk["id"]})
    new = list(sections(os.path.join(KNOWLEDGE, name)))
    for heading, body in new:
        c.call("create_memory_chunk", {**ref, "requestJson": json.dumps({"title": heading, "body": body, "docType": "prose"})})
    print(f"{title}: {len(new)} chunks (replaced {len(old)})")
