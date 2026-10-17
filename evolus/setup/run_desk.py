"""Run the desk workflow through the Evolus REST API, the way Sottovoce calls it, and print the result.

    python run_desk.py "request text"
"""
import json
import os
import sys
import time

import requests

KEY = os.environ["EVOLUS_API_KEY"].strip()
APP = os.environ["EVOLUS_APP_ID"].strip()
API = "https://api.evolus.ai/api/v1"
H = {"X-ApiKey": KEY, "X-Application-Id": APP}
wid = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "desk.json")))["workflow"]

t0 = time.time()
r = requests.post(f"{API}/workflows/{wid}/execute", headers=H, files={"input": (None, sys.argv[1])}, timeout=60)
print(r.status_code, r.text[:300])
r.raise_for_status()
eid = r.json()["executionId"]
while True:
    time.sleep(3)
    e = requests.get(f"{API}/workflows/{wid}/executions/{eid}", headers=H, timeout=60).json()
    if e.get("status") in ("Completed", "Failed") or time.time() - t0 > 300:
        break
print(f"{e.get('status')} in {time.time() - t0:.1f}s")
print(json.dumps(e, indent=1, ensure_ascii=False)[:int(os.environ.get("MAX", "4000"))])
