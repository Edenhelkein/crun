"""轮询 GitHub Actions 运行状态（抖音…不是，DNS 被污染所以走 api.github.com + 固定 IP）。"""
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PIN = {"api.github.com": "20.205.243.168", "objects.githubusercontent.com": "185.199.108.133"}
_o = socket.getaddrinfo
socket.getaddrinfo = lambda h, p, *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (PIN[h], p))] if h in PIN else _o(h, p, *a, **k)

TK = open(os.path.join(ROOT, ".gh_token"), encoding="utf-8").read().strip()
REPO = sys.argv[1] if len(sys.argv) > 1 else "Edenhelkein/crun"
WAIT = int(sys.argv[2]) if len(sys.argv) > 2 else 300


def api(path):
    req = urllib.request.Request("https://api.github.com" + path, headers={
        "Authorization": f"token {TK}", "Accept": "application/vnd.github+json", "User-Agent": "crun"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return {"_err": e.code, "_msg": e.read().decode("utf-8", "ignore")[:300]}


deadline = time.time() + WAIT
last = None
while time.time() < deadline:
    runs = api(f"/repos/{REPO}/actions/runs?per_page=3")
    if "_err" in runs:
        print("API 错误:", runs["_err"], runs["_msg"])
        break
    items = runs.get("workflow_runs", [])
    if not items:
        print("还没有 workflow run（可能 Actions 未开启）…")
        time.sleep(10)
        continue
    r = items[0]
    line = f"{r['name']} #{r['run_number']} status={r['status']} conclusion={r['conclusion']}"
    if line != last:
        print(line, flush=True)
        last = line
    if r["status"] == "completed":
        jobs = api(f"/repos/{REPO}/actions/runs/{r['id']}/jobs")
        for j in jobs.get("jobs", []):
            print(f"  job {j['name']}: {j['conclusion']}")
            for s in j.get("steps", []):
                if s.get("conclusion") not in (None, "success", "skipped"):
                    print(f"    × {s['name']}: {s.get('conclusion')}")
        print("URL:", r["html_url"])
        break
    time.sleep(10)
else:
    print("等待超时，去网页看：https://github.com/%s/actions" % REPO)
