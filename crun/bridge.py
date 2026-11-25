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


def run(account_id, km, run_type, minutes=None, cadence=None, log=print):
    ensure_paths()
    from tsnRunServer import TsnRunServer
    srv = TsnRunServer(account_id, float(km), run_type, minutes, cadence)
    log("开始跑步：%.2f km" % float(km))
    res = _run(srv.startRun())
    log("跑步结束：%s" % str(res)[:120])
    return res
