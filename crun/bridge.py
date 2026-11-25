"""新界面到原版 SDK 的桥：把 gui_app 里那套调用换成可复用的函数。

原版 GUI 是"点按钮 → 提交协程"，这里把同样的调用抽成同步函数，
新界面用线程调用，不需要原版窗口。
"""
import asyncio
import os
import sys
import uuid

LEGACY_DIRS = ("legacy", "legacy_site")


def ensure_paths():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    base = getattr(sys, "_MEIPASS", None) or here
    for d in LEGACY_DIRS:
        p = os.path.join(base, d)
        if os.path.isdir(p) and p not in sys.path:
            sys.path.insert(0, p)
    for d in LEGACY_DIRS:
        p = os.path.join(here, d)
        if os.path.isdir(p) and p not in sys.path:
            sys.path.insert(0, p)


def _run(coro):
    """同步跑协程（新界面在工作线程里调用）。"""
    try:
        return asyncio.run(coro)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        except Exception:
            raise
        finally:
            loop.close()


def _private(account=None):
    from TiShiNengSdkPrivate import TiShiNengPrivate
    if account is None:
        return TiShiNengPrivate("", 0, "", 0, str(uuid.uuid4()), "Xiaomi", "25053RT47C", "", "")
    return TiShiNengPrivate(
        str(account.user_id or ""), int(account.school_id or 0), str(account.username or ""),
        int(account.expires_in or 0), str(account.mobile_device_id or uuid.uuid4()),
        "Xiaomi", "25053RT47C", str(account.access_token or ""))


def provinces(log=print):
    """拉省份列表（原版用同一个私有客户端）。"""
    ensure_paths()
    cli = _private()
    resp = _run(cli.findAllProvince())
    data = (resp or {}).get("data") if isinstance(resp, dict) else None
    if not data:
        raise RuntimeError("服务器没有返回省份数据")
    out = [(p.get("id"), p.get("province_name") or p.get("name")) for p in data]
    log("拿到 %d 个省份" % len(out))
    return out


def schools_of_province(province_id, log=print):
    ensure_paths()
    cli = _private()
    resp = _run(cli.listSchoolByProvinceId(province_id))
    rows = (resp or {}).get("data") or []
    log("省份 %s 有 %d 所学校" % (province_id, len(rows)))
    return rows


def login(account, log=print):
    """用库里已有的账号做一次登录刷新 token。"""
    ensure_paths()
    cli = _private(account)
    resp = _run(cli.appLogin(account.username, account.password))
    log("登录返回：%s" % str(resp)[:120])
    return resp


def update_schools(db_path, log=print, only_provinces=None):
    """修好的学校更新：按省份把学校写进 tsn_school，并带上 province_name。

    原版的问题：更新时没把 province_name 写进去（NULL），而且 school_code 是
    NOT NULL 但接口返回 null，导致非广东的学校根本插不进库。
    """
    ensure_paths()
    import sqlite3
    import uuid as _uuid
    from TiShiNengSdkPrivate import TiShiNengPrivate

    async def work():
        cli = TiShiNengPrivate("", 0, "", 0, str(_uuid.uuid4()), "Xiaomi", "25053RT47C", "")
        provs = (await cli.findAllProvince()).get("data") or []
        if only_provinces:
            provs = [p for p in provs if p.get("province_name") in only_provinces]
        log("省份 %d 个，开始抓学校…" % len(provs))
        got = {}
        for p in provs:
            pid, pname = p.get("province_id"), p.get("province_name")
            if any(k in (pname or "") for k in ("测试", "演示")):
                continue
            try:
                resp = await cli.listSchoolByProvinceId(pid)
                rows = (resp or {}).get("data") or []
            except Exception as e:
                log("  %s 失败：%s" % (pname, e))
                continue
            got[pname] = rows
            log("  %s (id=%s) → %d 所" % (pname, pid, len(rows)))
        return got

    data = _run(work())
    con = sqlite3.connect(db_path, timeout=30)
    added = updated = 0
    try:
        cur = con.cursor()
        for pname, rows in data.items():
            for s in rows:
                sid = s.get("school_id")
                if sid is None:
                    continue
                name = (s.get("school_name") or "").strip()
                if not name:
                    continue
                low = name.lower()
                if "demo" in low or "test" in low:
                    continue
                code = s.get("schoolCode") or ""
                old = cur.execute("select school_code from tsn_school where school_id=?", (sid,)).fetchone()
                if not code:
                    code = (old[0] if old and old[0] and not str(old[0]).startswith("s") else "") or ("s%d" % sid)
                vals = (sid, name, s.get("school_url") or "", s.get("lan_url") or "",
                        str(s.get("openId") or ""), 1 if s.get("isOpenKeep") else 0,
                        1 if s.get("isOpenLive") else 0, 1 if s.get("isOpenEncry") else 0,
                        int(s.get("sysType") or 2), code, pname)
                cur.execute(
                    "insert into tsn_school(school_id, school_name, school_url, lan_url, open_id,"
                    " is_open_keep, is_open_live, is_open_encry, sys_type, school_code, province_name)"
                    " values(?,?,?,?,?,?,?,?,?,?,?)"
                    " on conflict(school_id) do update set"
                    " school_name=excluded.school_name, school_url=excluded.school_url,"
                    " lan_url=excluded.lan_url, open_id=excluded.open_id,"
                    " is_open_keep=excluded.is_open_keep, is_open_live=excluded.is_open_live,"
                    " is_open_encry=excluded.is_open_encry, sys_type=excluded.sys_type,"
                    " school_code=case when excluded.school_code='' then tsn_school.school_code"
                    " else excluded.school_code end,"
                    " province_name=excluded.province_name", vals)
                if old:
                    updated += 1
                else:
                    added += 1
        con.commit()
        # 回填历史 NULL（万一有残留）
        cur.execute("update tsn_school set province_name='广东省' where province_name is null and school_id in"
                    " (select school_id from tsn_school where province_name is null)")
        con.commit()
        stat = cur.execute("select province_name, count(*) from tsn_school group by province_name"
                           " order by 2 desc").fetchall()
    finally:
        con.close()
    log("写入完成：新增 %d，更新 %d" % (added, updated))
    log("现在有 %d 个省份：%s" % (len(stat), ", ".join("%s%d" % (n or "NULL", c) for n, c in stat[:8])))
    return stat


def crawl_paths(account_id, log=print):
    ensure_paths()
    from tsnRunServer import TsnRunServer, TsnRunType
    srv = TsnRunServer(account_id, 2.0, TsnRunType.freedom)
    res = _run(srv.queryPath())
    log("爬取路径完成：%s" % str(res)[:120])
    return res


def update_face(account_id, log=print):
    ensure_paths()
    from tsnRunServer import TsnRunServer, TsnRunType
    srv = TsnRunServer(account_id, 2.0, TsnRunType.freedom)
    res = _run(srv.getFaceImage())
    log("人脸：%s" % str(res)[:120])
    return res


def run(account_id, km, run_type, minutes=None, cadence=None, log=print, on_progress=None):
    """跑一次。on_progress(文本) 会实时收到原版 logger 的每一行（配速/等待/剩余）。"""
    ensure_paths()
    import logging
    from tsnRunServer import TsnRunServer

    class _Sink(logging.Handler):
        def emit(self, rec):
            try:
                on_progress(self.format(rec))
            except Exception:
                pass

    handler = _Sink()
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("%(asctime)s  %(message)s", "%H:%M:%S"))
    root = logging.getLogger()
    old_level = root.level
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    try:
        srv = TsnRunServer(account_id, float(km), run_type, minutes, cadence)
        log("开始跑步：%.2f km" % float(km))
        res = _run(srv.startRun())
        log("跑步结束：%s" % str(res)[:200])
        return res
    finally:
        try:
            root.removeHandler(handler)
            root.setLevel(old_level)
        except Exception:
            pass
