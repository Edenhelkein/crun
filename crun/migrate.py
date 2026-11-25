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

# 旧版工具叫法五花八门，按名字里出现的关键词找目录
KEYWORDS = ("校园跑", "步道", "乐跑", "跑步", "助手", "健康跑", "跑跑", "crun",
            "pao", "run", "sport", "fitness", "jog")
SKIP = {"windows", "$recycle.bin", "system volume information", "programdata",
        "node_modules", ".git", "appdata\\local\\packages", "__pycache__"}


def _env(name, default=""):
    return os.environ.get(name, default)


def _keyword_dirs(max_depth=2, budget_s=6.0):
    """按关键词在用户目录和磁盘顶层找旧版目录（带时间预算，别让安装卡住）。"""
    import time
    t0 = time.time()
    roots = [os.path.join(_env("USERPROFILE"), "Desktop"),
             os.path.join(_env("USERPROFILE"), "Downloads"),
             os.path.join(_env("USERPROFILE"), "Documents"),
             _env("USERPROFILE"),
             _env("LOCALAPPDATA"),
             _env("APPDATA")]
    for d in ("C:\\", "D:\\", "E:\\", "F:\\"):
        if os.path.isdir(d):
            roots.append(d)
    found = []
    seen = set()
    for root in roots:
        if not root or not os.path.isdir(root):
            continue
        for cur, dirs, _files in os.walk(root):
            if time.time() - t0 > budget_s:
                return found
            depth = cur[len(root):].count(os.sep)
            if depth >= max_depth:
                dirs[:] = []
            dirs[:] = [d for d in dirs if d.lower() not in SKIP and not d.startswith(".")]
            low = os.path.basename(cur).lower()
            if cur != root and any(k in low for k in KEYWORDS):
                real = os.path.normcase(os.path.abspath(cur))
                if real not in seen:
                    seen.add(real)
                    found.append(cur)
    return found


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
    try:
        cands += _keyword_dirs()
    except Exception:
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
        # 旧版可能不是这几个文件名：把可能的数据库/配置也列出来，好让用户认得
        try:
            for fn in os.listdir(d):
                low = fn.lower()
                if low in found or low in ("out",):
                    continue
                if low.endswith((".db", ".sqlite", ".sqlite3", ".csv")) or low in ("config.json", "settings.json", "user.json"):
                    found["?" + fn] = os.path.getsize(os.path.join(d, fn))
        except OSError:
            pass
        db = _tsn_candidates(d)
        if db:
            found["legacy:s校园跑助手"] = os.path.getsize(db)
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


def _tsn_candidates(d):
    """旧版"校园跑助手"把数据放在 tsn_data.db（sqlite）。"""
    try:
        for fn in os.listdir(d):
            if fn.lower().endswith((".db", ".sqlite", ".sqlite3")):
                p = os.path.join(d, fn)
                try:
                    import sqlite3
                    con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
                    tabs = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
                    con.close()
                    if {"tsn_run_path", "tsn_account"} & tabs:
                        return p
                except Exception:
                    continue
    except OSError:
        pass
    return None


def _parse_ts(v):
    """旧库的 created_at 有 int(ms) 也有 'YYYY-MM-DD HH:MM:SS' 文本，都要吃。"""
    if isinstance(v, (int, float)):
        return float(v) / 1000.0 if v > 1e11 else float(v)
    try:
        import datetime
        return datetime.datetime.strptime(str(v)[:19], "%Y-%m-%d %H:%M:%S").timestamp()
    except Exception:
        return 0.0


def import_tsn_db(db_path, target_dir):
    """把旧版 sqlite 里的路线与账号标识导入新格式。

    - 路线：run_line_path 是 [lon, lat] 点列 -> 换算成新格式（含 geohash7 相邻格指纹）
    - 账号：只导 student_id / school_id 作为标识；**不导入密码和 token**（那是明文凭证，不该复制）
    """
    import sqlite3

    from .geo import geohash_encode, haversine
    from .routegen import cells_of, edges_of, route_fingerprint

    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    cur = con.cursor()
    stats = {"db": db_path, "routes_added": 0, "accounts_added": 0, "schools": 0}

    rt_path = os.path.join(target_dir, "routes.json")
    routes = (_load_json(rt_path) or {}).get("routes", [])
    seen = {r.get("fp") for r in routes}
    try:
        for rid, scode, srange, line, created in cur.execute(
                "select run_path_id, school_code, sport_range, run_line_path, created_at from tsn_run_path"):
            try:
                raw = json.loads(line)
                pts = [(float(p[1]), float(p[0])) for p in raw if len(p) >= 2]
                if len(pts) < 10:
                    continue
                fp = route_fingerprint(pts)
                if fp in seen:
                    continue
                dist = sum(haversine(pts[i], pts[i + 1]) for i in range(len(pts) - 1))
                routes.append({"cells": cells_of(pts), "edges": edges_of(pts),
                               "ts": _parse_ts(created), "fp": fp,
                               "start_cell": geohash_encode(pts[0][0], pts[0][1], 6),
                               "distance_m": round(dist, 1), "source": "tsn",
                               "school_code": scode, "sport_range": srange})
                seen.add(fp)
                stats["routes_added"] += 1
            except Exception:
                continue
    except sqlite3.Error:
        pass
    if stats["routes_added"]:
        routes.sort(key=lambda r: r.get("ts", 0))
        with open(rt_path, "w", encoding="utf-8") as f:
            json.dump({"routes": routes[-300:]}, f, ensure_ascii=False, indent=2)

    pol_path = os.path.join(target_dir, "policy.json")
    pol = _load_json(pol_path) or {}
    accts = pol.setdefault("accounts", {})
    try:
        for sid, uid, school_id, uname in cur.execute(
                "select student_id, user_id, school_id, username from tsn_account"):
            key = str(uname or sid)
            if key in accts:
                continue
            accts[key] = {"bound_device": None, "bound_since": None, "failed": 0,
                          "locked_until": 0, "last_login": 0, "devices_seen": [],
                          "note": "imported from 校园跑助手", "school_id": school_id}
            stats["accounts_added"] += 1
    except sqlite3.Error:
        pass
    if stats["accounts_added"]:
        with open(pol_path, "w", encoding="utf-8") as f:
            json.dump(pol, f, ensure_ascii=False, indent=2)
    try:
        stats["schools"] = cur.execute("select count(*) from tsn_school").fetchone()[0]
    except sqlite3.Error:
        pass
    con.close()
    return stats


def merge(target_dir, sources):
    """把 sources 里的数据合并进 target_dir，返回统计。"""
    os.makedirs(target_dir, exist_ok=True)
    stats = {}
    conflicts = []

    # 旧版"校园跑助手"的 sqlite 先导（路线 + 账号标识）
    tsn = []
    for s in sources:
        db = _tsn_candidates(s)
        if db:
            try:
                tsn.append(import_tsn_db(db, target_dir))
            except Exception as e:
                tsn.append({"db": db, "error": str(e)})
    if tsn:
        stats["legacy_db"] = tsn

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
