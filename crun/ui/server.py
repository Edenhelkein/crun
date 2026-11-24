"""本地控制台：stdlib http.server + 单页前端，零依赖。

python -m crun.ui [--port 8777] [--work .]
"""
import argparse
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .. import __version__
from ..blacklist import RiskLedger, fingerprint
from ..engine import run_session
from ..policy import PolicyEngine
from ..routegen import RouteLibrary
from ..updater import apply as update_apply, check as update_check

HERE = os.path.dirname(os.path.abspath(__file__))
LOCK = threading.Lock()


def _work():
    return os.environ.get("CRUN_WORK", os.getcwd())


def state_summary():
    work = _work()
    led = RiskLedger(os.path.join(work, "ledger.json"))
    pol = PolicyEngine(os.path.join(work, "policy.json"))
    lib = RouteLibrary(os.path.join(work, "routes.json"))
    last = None
    p = os.path.join(work, "out", "session.json")
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
            last = {"audit": d.get("audit"), "route": d.get("route"),
                    "distance_m": d.get("session", {}).get("distance_m"),
                    "duration_s": d.get("session", {}).get("duration_s"),
                    "pace": d.get("session", {}).get("pace_s_per_km"),
                    "steps": d.get("steps", {}).get("total_steps")}
        except Exception:
            last = None
    return {
        "version": __version__,
        "ledger": list(led.entries.values()),
        "policy": pol.summary(),
        "routes": len(lib.routes),
        "last": last,
        "work": work,
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "crun-ui/1.2"

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            with open(os.path.join(HERE, "index.html"), "rb") as f:
                return self._send(200, f.read(), "text/html; charset=utf-8")
        if path == "/api/state":
            return self._send(200, state_summary())
        if path == "/api/export":
            p = os.path.join(_work(), "out", "session.json")
            if not os.path.exists(p):
                return self._send(404, {"error": "还没有生成过会话"})
            with open(p, "rb") as f:
                return self._send(200, f.read(), "application/json; charset=utf-8")
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        path = self.path.split("?")[0]
        n = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return self._send(400, {"error": "bad json"})

        if path == "/api/simulate":
            cfg = {
                "distance_m": float(body.get("distance", 2500)),
                "pace_s_per_km": float(body.get("pace", 360)),
                "account_id": body.get("account") or "ANON",
                "device_fp": body.get("device") or fingerprint("Xiaomi 23013RK75C", "UP1A", "a1b2c3"),
                "egress_ip": body.get("ip") or "",
                "mode": body.get("mode") or "campus_run",
                "tries": int(body.get("tries", 20)),
                "work_dir": _work(),
                "seed": body.get("seed"),
            }
            with LOCK:
                rep = run_session(cfg, out_dir=os.path.join(_work(), "out"))
            out = {"verdict": rep["verdict"], "policy": rep.get("policy"),
                   "route": rep.get("route"), "actions": rep.get("actions", [])}
            if "audit" in rep:
                au = rep["audit"]
                out["audit"] = {"score": au["score"], "verdict": au["verdict"],
                                "failed": au["failed"], "checks": au["checks"]}
                s = rep["session"]
                out["session"] = {"distance_m": s["distance_m"], "duration_s": s["duration_s"],
                                  "pace": s["pace_s_per_km"], "route_hash": s["route_hash"]}
                out["steps"] = {"total": rep["steps"]["total_steps"],
                                "cadence": rep["steps"]["avg_cadence_spm"],
                                "ratio": rep["steps"]["step_gps_ratio"]}
            else:
                out["reasons"] = rep.get("reasons", [])
                out["action"] = rep.get("action", "")
            return self._send(200, out)

        if path == "/api/observe":
            with LOCK:
                led = RiskLedger(os.path.join(_work(), "ledger.json"))
                hits = led.observe_response(body.get("text", ""), {
                    "device": body.get("device"), "account": body.get("account"), "ip": body.get("ip")})
                led.save()
            return self._send(200, {"hits": hits})

        if path == "/api/hit":
            with LOCK:
                led = RiskLedger(os.path.join(_work(), "ledger.json"))
                led.hit(body.get("kind", "device"), body.get("value", ""),
                        weight=float(body.get("weight", 3)), note="manual")
                led.save()
            return self._send(200, state_summary())

        if path == "/api/update/check":
            m = body.get("manifest")
            if not m:
                return self._send(400, {"error": "缺少清单地址"})
            try:
                return self._send(200, update_check(m))
            except Exception as e:
                return self._send(200, {"ok": False, "error": str(e)})

        if path == "/api/update/apply":
            m = body.get("manifest")
            try:
                info = update_check(m) if isinstance(m, str) else m
                root = os.path.dirname(os.path.dirname(HERE))
                res = update_apply(info, root, dry_run=bool(body.get("dry_run", True)),
                                   key=body.get("key"))
                return self._send(200, res)
            except Exception as e:
                return self._send(200, {"ok": False, "error": str(e)})

        return self._send(404, {"error": "not found"})


def main(argv=None):
    ap = argparse.ArgumentParser(prog="crun.ui")
    ap.add_argument("--port", type=int, default=8777)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--work", default=None)
    a = ap.parse_args(argv)
    if a.work:
        os.environ["CRUN_WORK"] = os.path.abspath(a.work)
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    print(f"crun ui: http://{a.host}:{a.port}/   work={_work()}  version={__version__}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
