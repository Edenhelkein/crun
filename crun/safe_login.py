"""登录安全闸：把"封号"的两条主要路径挡在前面。

服务器判定逻辑（从现象反推）：
  1. 手机 App 点"退出登录"只清了本地态，服务端会话还在。
     这时候电脑端立刻登录 = 同一账号短时间内出现第二台设备 → 判违规。
  2. 同一台电脑上先后登录多个账号 → 判"代跑/多号"→ 封。

所以这里做三件事，全部是本地约束，不发额外请求：
  A. 能复用就复用：本地 access_token 没过期就不重新登录（少一次设备握手）
  B. 同一账号登录间隔下限（默认 15 分钟）
  C. 同一台机器切换账号的冷却（默认 24 小时），切号要显式确认
另外提供"手机退出后等待"倒计时（默认 300 秒），把最容易踩的第一次登录风险降下来。
"""
import json
import os
import time

LOGIN_GAP_S = float(os.environ.get("CRUN_LOGIN_GAP_S", "900"))       # 同账号最小登录间隔
SWITCH_COOLDOWN_S = float(os.environ.get("CRUN_SWITCH_COOLDOWN_S", "86400"))  # 换号冷却
PHONE_SETTLE_S = float(os.environ.get("CRUN_PHONE_SETTLE_S", "300"))  # 手机退出后建议等待

STATE = "crun_login_state.json"


def _path(data_dir):
    return os.path.join(data_dir, STATE)


def load(data_dir):
    try:
        with open(_path(data_dir), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"active": None, "accounts": {}}


def save(data_dir, st):
    try:
        with open(_path(data_dir), "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def token_valid(account):
    """本地是否有能用的 access_token（有就别再登录一次）。"""
    tok = getattr(account, "access_token", None) or ""
    exp = getattr(account, "expires_in", None)
    if not tok:
        return False
    try:
        return float(exp or 0) > time.time() + 120
    except (TypeError, ValueError):
        return False


def login_age(account):
    """本地记录的 token 签发时间（没有记录就返回 None）。"""
    return getattr(account, "_crun_login_ts", None)


def precheck(data_dir, account, active=(), now=None):
    """登录前检查。返回 dict(ok=bool, code=str, message=str, wait_s=int)。"""
    now = time.time() if now is None else now
    st = load(data_dir)
    cur = str(getattr(account, "id", ""))
    if token_valid(account):
        return {"ok": True, "code": "reuse", "wait_s": 0,
                "message": "本地登录态还有效，直接复用（不会再向服务器发登录请求，避免二次设备握手）"}

    last = (st.get("accounts", {}).get(cur) or {}).get("last_login", 0)
    if last and now - last < LOGIN_GAP_S:
        wait = int(LOGIN_GAP_S - (now - last))
        return {"ok": False, "code": "cooldown", "wait_s": wait,
                "message": "这个账号 %d 分钟前刚登录过。短时间内反复登录，服务器会看到设备频繁上下线，"
                           "请等 %d 分 %d 秒后再试。" % ((now - last) // 60, wait // 60, wait % 60)}

    act = st.get("active")
    if act and act != cur:
        act_rec = (st.get("accounts", {}).get(act) or {})
        act_last = act_rec.get("last_login", 0)
        if act_last and now - act_last < SWITCH_COOLDOWN_S:
            wait = int(SWITCH_COOLDOWN_S - (now - act_last))
            return {"ok": False, "code": "switch", "wait_s": wait,
                    "message": "这台电脑 %d 小时前登录过另一个账号（%s）。同一助手先后登录多个账号，"
                               "服务端会判为代跑并直接封号。\n\n要切过来，建议等满 24 小时；"
                               "确实要现在切，需要你手动确认。" % (
                                   int((now - act_last) // 3600), act_rec.get("username", "另一个号")),
                    "switch_from": act_rec.get("username")}
    return {"ok": True, "code": "fresh", "wait_s": 0,
            "message": "可以登录。请确认手机端已退出登录，并等倒计时结束再点。"}


def record(data_dir, account, ok=True):
    st = load(data_dir)
    cur = str(getattr(account, "id", ""))
    rec = st.setdefault("accounts", {}).setdefault(cur, {})
    if ok:
        rec["last_login"] = time.time()
        rec["username"] = getattr(account, "username", "")
        st["active"] = cur
    save(data_dir, st)
    return st


def force_active(data_dir, account):
    """用户显式确认换号时调用。"""
    st = load(data_dir)
    st["active"] = str(getattr(account, "id", ""))
    st.setdefault("accounts", {}).setdefault(str(getattr(account, "id", "")), {})["username"] = \
        getattr(account, "username", "")
    save(data_dir, st)


def summary(data_dir, accounts):
    """给界面显示：当前活跃账号、每个号上次登录时间。"""
    st = load(data_dir)
    out = []
    for a in accounts:
        rec = (st.get("accounts", {}).get(str(a.get("id"))) or {})
        ts = rec.get("last_login", 0)
        out.append({
            "id": a.get("id"),
            "username": a.get("username"),
            "active": str(a.get("id")) == str(st.get("active")),
            "last_login": time.strftime("%m-%d %H:%M", time.localtime(ts)) if ts else "从未",
        })
    return out
