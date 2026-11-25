"""平台约束模型（来自实测的三条硬规则）。

1. 不能双设备登录       -> 一个账号绑定一台设备，换设备 = 账号异常
2. 只能请求学校开设的模式 -> 模式白名单，其它模式请求本身就是风控特征
3. 不能多次尝试密码     -> 失败计数 + 锁定，绝不做重试/喷洒

这些是"一旦违反就必然出问题"的硬约束，所以放在生成轨迹之前做 preflight，
而不是塞进自审分数里靠权重折算。
"""
import json
import os
import time

DEFAULT_MODES = ("morning_run", "free_run", "sunshine_run")
MODE_LABELS = {"morning_run": "晨跑", "free_run": "自由跑", "sunshine_run": "阳光跑"}
MODE_ALIASES = {  # 老版本叫法 -> 新标识
    "campus_run": "free_run", "extra_activity": "sunshine_run", "run": "free_run",
    "晨跑": "morning_run", "自由跑": "free_run", "阳光跑": "sunshine_run",
}
DEFAULT_MAX_ATTEMPTS = 5
LOCK_SECONDS = 24 * 3600


class PolicyEngine:
    def __init__(self, path=None, allowed_modes=DEFAULT_MODES,
                 max_password_attempts=DEFAULT_MAX_ATTEMPTS, now=None):
        self.path = path
        self.allowed_modes = tuple(allowed_modes)
        self.max_attempts = max_password_attempts
        self.now = now or time.time()
        self.accounts = {}
        if path and os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            self.accounts = data.get("accounts", {})
            self.allowed_modes = tuple(data.get("allowed_modes", self.allowed_modes))

    # ---------- 账号状态 ----------
    def _acct(self, account):
        return self.accounts.setdefault(account, {
            "bound_device": None, "bound_since": None,
            "failed": 0, "locked_until": 0, "last_login": 0, "devices_seen": []})

    def bind_device(self, account, device):
        a = self._acct(account)
        if a["bound_device"] is None:
            a["bound_device"] = device
            a["bound_since"] = self.now
            a["devices_seen"] = [device]
            return True, "首次绑定"
        if a["bound_device"] == device:
            return True, "设备一致"
        if device not in a["devices_seen"]:
            a["devices_seen"].append(device)
        return False, f"账号已绑定 {a['bound_device'][:8]}…，换设备登录会被判双设备"

    # ---------- 登录 ----------
    def login(self, account, device, success):
        a = self._acct(account)
        if a["locked_until"] > self.now:
            return {"ok": False, "reason": f"账号锁定中，剩余 {(a['locked_until'] - self.now) / 3600:.1f}h",
                    "attempts_left": 0}
        ok_bind, bind_msg = self.bind_device(account, device)
        if success:
            a["failed"] = 0
            a["last_login"] = self.now
            a["locked_until"] = 0
            return {"ok": ok_bind, "reason": bind_msg, "attempts_left": self.max_attempts}
        a["failed"] += 1
        left = max(0, self.max_attempts - a["failed"])
        if a["failed"] >= self.max_attempts:
            a["locked_until"] = self.now + LOCK_SECONDS
            return {"ok": False, "reason": "达到失败上限，账号锁定 24h", "attempts_left": 0,
                    "locked_until": a["locked_until"]}
        return {"ok": False, "reason": f"密码错误（{a['failed']}/{self.max_attempts}）", "attempts_left": left}

    # ---------- 模式 ----------
    def check_mode(self, mode):
        mode = MODE_ALIASES.get(mode, mode)
        if mode in self.allowed_modes:
            return True, "模式在白名单内"
        return False, f"模式 {mode} 未开设，请求非白名单模式会被记为异常"

    # ---------- 出车前置 ----------
    def preflight(self, account, device, mode):
        reasons, ok = [], True
        a = self._acct(account)
        if a["locked_until"] > self.now:
            ok = False
            reasons.append("账号处于锁定窗口内")
        if a["failed"] > 0:
            ok = False
            reasons.append(f"存在 {a['failed']} 次失败登录记录，先人工核对凭证，不要继续尝试")
        bound_ok, bind_msg = self.bind_device(account, device)
        if not bound_ok:
            ok = False
            reasons.append(bind_msg)
        mode_ok, mode_msg = self.check_mode(mode)
        if not mode_ok:
            ok = False
            reasons.append(mode_msg)
        return {"allowed": ok, "reasons": reasons, "bind": bind_msg, "mode": mode_msg}

    def summary(self):
        return {"allowed_modes": list(self.allowed_modes), "max_attempts": self.max_attempts,
                "accounts": {k: {"bound_device": v["bound_device"], "failed": v["failed"],
                                 "locked_until": v["locked_until"]} for k, v in self.accounts.items()}}

    def save(self, path=None):
        p = path or self.path
        if not p:
            return
        os.makedirs(os.path.dirname(os.path.abspath(p)), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"accounts": self.accounts, "allowed_modes": list(self.allowed_modes)},
                      f, ensure_ascii=False, indent=2)
