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


def backup_dir():
    """备份放在用户目录下，这样连 %LOCALAPPDATA% 被清也能捡回来。"""
    d = os.path.join(os.path.expanduser("~"), "CRUN备份")
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        pass
    return d


def backup_now(db_path, log=None):
    import shutil
    if not (os.path.exists(db_path) and os.path.getsize(db_path) > 0):
        return None
    try:
        dst = os.path.join(backup_dir(), "tsn_data-latest.db")
        shutil.copyfile(db_path, dst)
        if log:
            log("已备份数据库到 %s" % dst)
        return dst
    except OSError as e:
        if log:
            log("备份失败：%s" % e)
        return None


def ensure_db(db_path=None, log=print):
    """数据库被删/被清空时自愈：先用随包种子恢复，再不行就建空表。

    之前数据目录被清掉后，sqlite3.connect 会就地建一个 0 字节文件，
    于是第一条 insert 就报 "no such table: tsn_school"。
    """
    db_path = db_path or os.path.join(os.getcwd(), "tsn_data.db")
    ok = os.path.exists(db_path) and os.path.getsize(db_path) > 0
    if ok:
        try:
            import sqlite3
            con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            names = [r[0] for r in con.execute("select name from sqlite_master where type='table'")]
            con.close()
            ok = "tsn_school" in names and "tsn_account" in names
        except Exception:
            ok = False
    if ok:
        return "ok"
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    base = getattr(sys, "_MEIPASS", None) or here
    import glob
    import shutil
    # 先用本地自动备份（里面才有账号），再用随包种子
    backups = sorted(glob.glob(os.path.join(os.path.dirname(db_path), "tsn_data.backup-*.db")),
                     reverse=True)
    ext = os.path.join(backup_dir(), "tsn_data-latest.db")
    seeds = [ext] + backups + [os.path.join(base, "assets", "tsn_data.db")]
    for s in seeds:
        if os.path.exists(s) and os.path.getsize(s) > 0:
            shutil.copyfile(s, db_path)
            log("本地数据库缺失/损坏，已从 %s 恢复" % s)
            return "restored"
    # 连种子都没有：建空表，至少不报 "no such table"
    try:
        import sqlite3
        import models as _m
        con = sqlite3.connect(db_path)
        _m.Base.metadata.create_all(con)
        con.commit()
        con.close()
        log("本地数据库为空，已重建表结构: %s" % db_path)
        return "created"
    except Exception as e:
        log("数据库自愈失败: %s" % e)
        return "failed"


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


def _auth_client():
    return __import__("httpx")


def _account_row(account_id):
    import sqlite3
    con = sqlite3.connect(os.path.join(os.getcwd(), "tsn_data.db"), timeout=10)
    try:
        cur = con.execute("select id, username, password, access_token, refresh_token from tsn_account where id=?",
                          (account_id,))
        row = cur.fetchone()
    finally:
        con.close()
    return row


def session_state(account_id, log=print):
    """登录前检查：用本地 access_token 问服务器"我这个会话还活着吗"。

    返回 dict(has_token, valid, detail)
    """
    ensure_paths()
    import tsn_routes as R
    row = _account_row(account_id)
    if not row or not (row[3] or "").strip():
        log("本地没有 access_token，无法预检会话")
        return {"has_token": False, "valid": False, "detail": "本地无 token"}
    tok = row[3].strip()
    url = R.build_url(R.DEFAULT_BASE_URL, "getLoginUserInfo")
    httpx = _auth_client()
    try:
        r = httpx.get(url, headers={"Authorization": "bearer " + tok}, timeout=15, verify=False)
        if r.status_code == 200:
            log("会话有效（服务器认得这个 token）")
            return {"has_token": True, "valid": True, "detail": "有效"}
        log("会话已失效：HTTP %s" % r.status_code)
        return {"has_token": True, "valid": False, "detail": "HTTP %s" % r.status_code}
    except Exception as e:
        log("会话检查失败：%s" % e)
        return {"has_token": True, "valid": False, "detail": str(e)}


def force_logout(account_id, log=print):
    """强制退出该账号在服务器上的会话（手机端也会被踢下线）。

    这是"登录前检查 + 先踢人再登录"的核心：把可能还活着的手机会话作废，
    避免服务端把接下来的登录看成第二台设备。
    """
    ensure_paths()
    import tsn_routes as R
    row = _account_row(account_id)
    if not row:
        raise RuntimeError("账号不存在")
    tok = (row[3] or "").strip()
    if not tok:
        log("没有 access_token，无法强制退出（首次登录没有凭据可踢）")
        return {"kicked": False, "detail": "无 token"}
    url = R.build_url(R.DEFAULT_BASE_URL, "logout")
    httpx = _auth_client()
    for method in ("post", "get"):
        try:
            fn = getattr(httpx, method)
            r = fn(url, headers={"Authorization": "bearer " + tok}, timeout=15, verify=False)
            log("强制退出 %s：HTTP %s" % (method.upper(), r.status_code))
            if r.status_code in (200, 204):
                # 本地 token 也一并作废，避免拿旧 token 继续打接口
                try:
                    import sqlite3
                    con = sqlite3.connect(os.path.join(os.getcwd(), "tsn_data.db"), timeout=10)
                    con.execute("update tsn_account set access_token='', refresh_token='', expires_in=0 where id=?",
                                (account_id,))
                    con.commit()
                    con.close()
                except Exception:
                    pass
                return {"kicked": True, "detail": "HTTP %s" % r.status_code}
        except Exception as e:
            log("强制退出失败（%s）：%s" % (method, e))
    return {"kicked": False, "detail": "服务器未确认"}


def login(account_id, log=print):
    """走原版的私有客户端：本地 token 还有效就直接复用，不重复登录。

    这一点很关键 —— 每次重新 appLogin 都是一次新的设备握手，
    短时间内反复登录是封号的头号诱因。
    """
    ensure_paths()
    import database
    from tsnClient import getPrivateVersionClient, getTsnAccountByid

    async def work():
        async for db in database.get_db():
            acc = await getTsnAccountByid(account_id, db)
            if acc is None:
                raise RuntimeError("账号不存在")
            log("获取客户端：%s" % getattr(acc, "username", account_id))
            cli = await getPrivateVersionClient(acc)
            return acc, cli

    acc, cli = _run(work())
    log("登录态就绪（token 有效则不会重新登录）")
    return acc, cli


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


def query_stats(account_id, log=print):
    """查有效次数/里程。用的是原版同一个 validCountServer。"""
    ensure_paths()
    import validCountServer as V
    res = _run(V.crawl_valid_count_for_account(account_id))
    out = {k: getattr(res, k, None) for k in V.ValidRunCount.__dataclass_fields__}
    log("查询完成：有效 %s 次 / %.2f km" % (out.get("total_valid_count"), out.get("total_distance_km") or 0))
    return out


def crawl_paths(account_id, log=print):
    """爬取路径：原版用的是 spiderServer.startSpider，不是 TsnRunServer.queryPath。"""
    ensure_paths()
    import logging
    import spiderServer as SP
    log("正在从学校的跑步服务端爬取路线…")
    old = logging.root.manager.disable
    logging.disable(logging.INFO)          # 原版会把整条轨迹打进日志，别刷屏
    try:
        _run(SP.startSpider(account_id))
    finally:
        logging.disable(old)
    log("爬取完成")
    return True


def update_face(account_id, log=print):
    """更新人脸：先把 accountModel / tsnClient 塞进 TsnRunServer，否则 getFaceImage 会空指针。"""
    ensure_paths()
    import database
    import models
    # 动态导入：静态 import 会让 PyInstaller 去分析 sqlalchemy，而它是以 .pyc 形式随包发的
    _sa = __import__("sqlalchemy", fromlist=["select"])
    _orm = __import__("sqlalchemy.orm", fromlist=["selectinload"])
    select, selectinload = _sa.select, _orm.selectinload
    from tsnRunServer import TsnRunServer, TsnRunType
    from tsnClient import getTsnClientById

    async def work():
        async for db in database.get_db():
            acc = (await db.execute(
                select(models.TsnAccount_Model)
                .options(selectinload(models.TsnAccount_Model.school))
                .where(models.TsnAccount_Model.id == account_id))).scalars().first()
            if acc is None:
                raise RuntimeError("账号不存在")
            srv = TsnRunServer(account_id, 2.0, TsnRunType.freedom)
            srv.accountModel = acc
            srv.tsnClient = await getTsnClientById(account_id, db)
            srv.isPublic = False
            log("客户端就绪，开始拉取人脸…")
            return await srv.getFaceImage()

    res = _run(work())
    log("人脸：%s" % str(res)[:160])
    return res


RUN_TYPES = {"morning_run": "morningRun", "free_run": "freedom", "sunshine_run": "sumRun"}


def run(account_id, km, run_type, minutes=None, cadence=None, log=print, on_progress=None):
    """跑一次。run_type 可以传 'morning_run'/'free_run'/'sunshine_run' 或 TsnRunType 常量。"""
    ensure_paths()
    import logging
    try:
        from tsnRunServer import TsnRunServer, TsnRunType
    except ImportError as e:
        raise RuntimeError("缺少运行内核 tsnRunServer（%s）。请用安装包装一遍，"
                           "或确认程序目录下有 _internal\\legacy\\tsnRunServer.pyc" % e)
    if isinstance(run_type, str):
        run_type = getattr(TsnRunType, RUN_TYPES.get(run_type, "freedom"))

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
