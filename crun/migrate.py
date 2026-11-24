"""旧版数据发现与合并。

背景：早前版本是"解压即用"，数据就躺在 exe 旁边的 json 里；有人拷走整个目录后，
新装机器的安装包里读不到那些历史（账本、路线库、账号绑定、开跑时间分布）。
这里把已知位置全扫一遍，按"并集、取严"的规则合并，不覆盖已有数据。

合并语义：
  ledger   同实体取更高分、更高状态、更近的 last_hit
  policy   账号绑定冲突时保留最后登录的那台设备，其余记入 devices_seen 并报冲突
  routes   按指纹去重，按时间排序保留最近 300 条
  state    按 (route_hash, start_ts) 去重，保留最近 200 条
"""
import json
import os
import sys

DATA_FILES = ("ledger.json", "policy.json", "routes.json", "state.json")
STATUS_RANK = {"clean": 0, "watch": 1, "flagged": 2, "banned": 3}


def _env(name, default=""):
    return os.environ.get(name, default)


def _reg_install_locations():
    """从卸载表里找历史安装目录（HKCU + HKLM）。"""
    out = []
    try:
        import winreg
    except Exception:
        return out
    roots = [
        (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]
    for hive, base in roots:
        try:
            with winreg.OpenKey(hive, base) as k:
                for i in range(winreg.QueryInfoKey(k)[0]):
                    try:
                        name = winreg.EnumKey(k, i)
                        if "crun" not in name.lower():
                            continue
                        with winreg.OpenKey(k, name) as sk:
                            try:
                                loc = winreg.QueryValueEx(sk, "InstallLocation")[0]
                            except OSError:
                                continue
                            if loc:
                                out.append(loc)
                    except OSError:
                        continue
        except OSError:
            continue
    return out


def candidate_dirs(extra=None):
    """按可信度排序的候选目录。"""
    exe_dir = os.path.dirname(os.path.abspath(sys.executable)) if getattr(sys, "frozen", False) \
        else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cands = [
        exe_dir,
        os.path.join(_env("LOCALAPPDATA"), "Programs", "CRUN"),
        os.path.join(_env("LOCALAPPDATA"), "CRUN"),
        os.path.join(_env("APPDATA"), "crun"),
        os.path.join(_env("USERPROFILE"), ".crun"),
        os.getcwd(),
    ]
    cands += _reg_install_locations()
    for base in (os.path.join(_env("USERPROFILE"), "Desktop"),
                 os.path.join(_env("USERPROFILE"), "Downloads"),
                 os.path.join(_env("USERPROFILE"), "Documents")):
        if not os.path.isdir(base):
            continue
        try:
            for name in os.listdir(base):
                p = os.path.join(base, name)
                if os.path.isdir(p) and "crun" in name.lower():
                    cands.append(p)
        except OSError:
            pass
    if extra:
        cands = list(extra) + cands
    seen, out = set(), []
    for c in cands:
        if not c:
            continue
        try:
            real = os.path.normcase(os.path.abspath(c))
        except OSError:
            continue
        if real in seen or not os.path.isdir(real):
            continue
        seen.add(real)
        out.append(os.path.abspath(c))
    return out


def _load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def scan(dirs=None):
    """扫描并返回每个目录里发现了什么，不写任何东西。"""
    report = []
    for d in dirs or candidate_dirs():
        found = {}
        for fn in DATA_FILES + ("session.json",):
            p = os.path.join(d, fn)
            if os.path.isfile(p):
                found[fn] = os.path.getsize(p)
        sub = os.path.join(d, "out", "session.json")
        if os.path.isfile(sub):
            found["out/session.json"] = os.path.getsize(sub)
        if found:
            report.append({"dir": d, "files": found})
    return report


# ---------------------------------------------------------------- 合并

def _merge_ledger(target, src):
    entries = {}
    for e in (target or {}).get("entries", []):
        entries[(e["kind"], e["value"])] = e
    added = 0
    for e in (src or {}).get("entries", []):
        k = (e["kind"], e["value"])
        cur = entries.get(k)
        if cur is None:
            entries[k] = e
            added += 1
            continue
        cur["score"] = max(cur.get("score", 0), e.get("score", 0))
        if STATUS_RANK.get(e.get("status"), 0) > STATUS_RANK.get(cur.get("status"), 0):
            cur["status"] = e["status"]
        cur["last_hit"] = max(cur.get("last_hit", 0), e.get("last_hit", 0))
        cur["hits"] = max(cur.get("hits", 0), e.get("hits", 0))
    return {"entries": list(entries.values())}, added


def _merge_policy(target, src):
    tgt = dict(target or {})
    accts = tgt.setdefault("accounts", {})
    conflicts, added = [], 0
    for name, a in (src or {}).get("accounts", {}).items():
        cur = accts.get(name)
        if cur is None:
            accts[name] = a
            added += 1
            continue
        if a.get("bound_device") and cur.get("bound_device") and a["bound_device"] != cur["bound_device"]:
            keep = a if a.get("last_login", 0) > cur.get("last_login", 0) else cur
            other = cur if keep is a else a
            seen = set(keep.get("devices_seen") or [])
            seen.add(other.get("bound_device"))
            keep["devices_seen"] = sorted(x for x in seen if x)
            conflicts.append({"account": name, "kept": keep.get("bound_device"),
                              "other": other.get("bound_device")})
            accts[name] = keep
        cur["failed"] = max(cur.get("failed", 0), a.get("failed", 0))
        cur["locked_until"] = max(cur.get("locked_until", 0), a.get("locked_until", 0))
    if src and src.get("allowed_modes") and not tgt.get("allowed_modes"):
        tgt["allowed_modes"] = src["allowed_modes"]
    return tgt, added, conflicts


def _merge_routes(target, src):
    routes = list((target or {}).get("routes", []))
    seen = {r.get("fp") for r in routes}
    added = 0
    for r in (src or {}).get("routes", []):
        if r.get("fp") in seen:
            continue
        routes.append(r)
        seen.add(r.get("fp"))
        added += 1
    routes.sort(key=lambda r: r.get("ts", 0))
    return {"routes": routes[-300:]}, added


def _merge_state(target, src):
    runs = list((target or {}).get("runs", []))
    seen = {(r.get("route_hash"), r.get("start_ts")) for r in runs}
    added = 0
    for r in (src or {}).get("runs", []):
        k = (r.get("route_hash"), r.get("start_ts"))
        if k in seen:
            continue
        runs.append(r)
        seen.add(k)
        added += 1
    runs.sort(key=lambda r: r.get("start_ts", 0))
    return {"runs": runs[-200:]}, added


def merge(target_dir, sources):
    """把 sources 里的数据合并进 target_dir，返回统计。"""
    os.makedirs(target_dir, exist_ok=True)
    stats = {}
    conflicts = []

    led_path = os.path.join(target_dir, "ledger.json")
    led, n = _merge_ledger(_load_json(led_path), None)
    for s in sources:
        src = _load_json(os.path.join(s, "ledger.json"))
        if src:
            led, added = _merge_ledger(led, src)
            n += added
    if led["entries"] or os.path.exists(led_path):
        with open(led_path, "w", encoding="utf-8") as f:
            json.dump(led, f, ensure_ascii=False, indent=2)
        stats["ledger_entries"] = len(led["entries"])
        stats["ledger_added"] = n

    pol_path = os.path.join(target_dir, "policy.json")
    pol = _load_json(pol_path) or {}
    for s in sources:
        src = _load_json(os.path.join(s, "policy.json"))
        if src:
            pol, added, conf = _merge_policy(pol, src)
            stats["policy_accounts"] = len(pol.get("accounts", {}))
            stats["policy_added"] = stats.get("policy_added", 0) + added
            conflicts.extend(conf)
    if pol:
        with open(pol_path, "w", encoding="utf-8") as f:
            json.dump(pol, f, ensure_ascii=False, indent=2)

    rt_path = os.path.join(target_dir, "routes.json")
    rt = _load_json(rt_path) or {}
    for s in sources:
        src = _load_json(os.path.join(s, "routes.json"))
        if src:
            rt, added = _merge_routes(rt, src)
            stats["routes_total"] = len(rt["routes"])
            stats["routes_added"] = stats.get("routes_added", 0) + added
    if rt.get("routes"):
        with open(rt_path, "w", encoding="utf-8") as f:
            json.dump(rt, f, ensure_ascii=False, indent=2)

    st_path = os.path.join(target_dir, "state.json")
    st = _load_json(st_path) or {}
    for s in sources:
        src = _load_json(os.path.join(s, "state.json"))
        if src:
            st, added = _merge_state(st, src)
            stats["runs_total"] = len(st["runs"])
            stats["runs_added"] = stats.get("runs_added", 0) + added
    if st.get("runs"):
        with open(st_path, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False, indent=2)

    if conflicts:
        stats["device_conflicts"] = conflicts
    stats["source_dirs"] = sources
    return stats
