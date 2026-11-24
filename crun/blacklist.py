"""黑名单 / 风控账本。

三层实体：device / account / ip / route。
状态机：clean -> watch -> flagged -> banned（按命中权重累积，带 TTL 衰减）。
服务端一旦回风控话术，直接把账号+设备钉成 flagged 并写冷却期，避免"继续跑=加证据"。
"""
import hashlib
import json
import os
import re
import time

STATUS_RANK = {"clean": 0, "watch": 1, "flagged": 2, "banned": 3}

RISK_PATTERNS = [
    r"风控", r"作弊", r"异常(?:行为|轨迹|数据|运动)", r"封禁", r"黑名单", r"禁止(?:参加|使用)",
    r"违规", r"risk", r"ban(?:ned)?", r"illegal", r"invalid_sign", r"suspicious",
    r"速度异常", r"轨迹异常", r"设备异常", r"多账号",
]

TTL_DAYS = {"device": 120, "account": 180, "ip": 30, "route": 45}


def fingerprint(device_model, build_id, android_id, serial_hash=""):
    raw = f"{device_model}|{build_id}|{android_id}|{serial_hash}".encode()
    return hashlib.sha256(raw).hexdigest()[:24]


class RiskLedger:
    def __init__(self, path=None, ttl_days=None, now=None):
        self.path = path
        self.ttl = dict(TTL_DAYS)
        if ttl_days:
            self.ttl.update(ttl_days)
        self.entries = {}
        self._now = now or time.time()
        if path and os.path.exists(path):
            self.load()

    # ---------- 基础 ----------
    def _key(self, kind, value):
        return f"{kind}:{value}"

    def _get(self, kind, value):
        e = self.entries.get(self._key(kind, value))
        if e and self._now - e["last_hit"] > self.ttl.get(kind, 60) * 86400:
            return None
        return e

    def hit(self, kind, value, weight=1.0, note="", status=None):
        if not value:
            return
        k = self._key(kind, value)
        e = self._get(kind, value)
        if e is None:
            e = {"kind": kind, "value": value, "score": 0.0, "hits": 0,
                 "status": "clean", "first_hit": self._now, "last_hit": self._now, "notes": []}
            self.entries[k] = e
        e["score"] += weight
        e["hits"] += 1
        e["last_hit"] = self._now
        if note:
            e["notes"] = (e["notes"] + [note])[-8:]
        if status:
            e["status"] = status
        elif e["score"] >= 6.0 and STATUS_RANK[e["status"]] < 2:
            e["status"] = "flagged"
        elif e["score"] >= 2.5 and e["status"] == "clean":
            e["status"] = "watch"
        return e

    def status(self, kind, value):
        e = self._get(kind, value)
        return e["status"] if e else "clean"

    def is_blocked(self, kind, value):
        return STATUS_RANK[self.status(kind, value)] >= 2

    def purge(self):
        dead = [k for k, e in self.entries.items()
                if self._now - e["last_hit"] > self.ttl.get(e["kind"], 60) * 86400]
        for k in dead:
            del self.entries[k]
        return len(dead)

    # ---------- 服务端反馈解析 ----------
    def observe_response(self, text, ctx):
        """ctx: {device, account, ip}。命中风控话术 -> 直接 flagged。"""
        hit_terms = [p for p in RISK_PATTERNS if re.search(p, text or "", re.I)]
        if not hit_terms:
            return []
        out = []
        for kind in ("account", "device"):
            v = ctx.get(kind)
            if v:
                self.hit(kind, v, weight=8.0, note=f"server:{hit_terms[0]}", status="flagged")
                out.append({"kind": kind, "value": v, "matched": hit_terms[:3]})
        if ctx.get("ip"):
            self.hit("ip", ctx["ip"], weight=3.0, note="server-risk-ip")
            out.append({"kind": "ip", "value": ctx["ip"], "matched": hit_terms[:3]})
        return out

    # ---------- 决策 ----------
    def decide(self, ctx, route_hash=None):
        reasons, verdict = [], "RUN"
        for kind in ("device", "account"):
            v = ctx.get(kind)
            st = self.status(kind, v) if v else "clean"
            if STATUS_RANK[st] >= 3:
                return "ABORT", [f"{kind} 已封禁（banned）"]
            if STATUS_RANK[st] == 2:
                verdict = "ABORT"
                reasons.append(f"{kind} 处于 flagged，继续执行会累积证据")
            elif STATUS_RANK[st] == 1:
                verdict = "THROTTLE" if verdict == "RUN" else verdict
                reasons.append(f"{kind} 处于观察期，需更换网络/时间窗")
        ip = ctx.get("ip")
        if ip and STATUS_RANK[self.status("ip", ip)] >= 2:
            verdict = "THROTTLE" if verdict == "RUN" else verdict
            reasons.append("出口 IP 已被标记")
        if route_hash and STATUS_RANK[self.status("route", route_hash)] >= 1:
            verdict = "THROTTLE" if verdict == "RUN" else verdict
            reasons.append("该轨迹指纹历史命中过，需换线")
        return verdict, reasons

    # ---------- 持久化 ----------
    def save(self, path=None):
        p = path or self.path
        if not p:
            return
        os.makedirs(os.path.dirname(os.path.abspath(p)), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"now": self._now, "entries": list(self.entries.values())}, f,
                      ensure_ascii=False, indent=2)

    def load(self, path=None):
        p = path or self.path
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        for e in data.get("entries", []):
            self.entries[self._key(e["kind"], e["value"])] = e
        return self
