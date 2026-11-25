"""启动原版"校园跑助手"图形界面，并在外面套一层增强。

思路：原版 exe 里的模块（gui_app / tsnRunServer / tsnClient…）已经被导出成 .pyc，
这里把它们接回来跑，然后在运行时打补丁 —— 而不是重写一套功能。

增强点（可在 GUI 里看到效果）：
  1. 路线平滑：原版生成的轨迹直接交给学校，这里做一次小角度平滑，去掉 90° 硬折角
  2. 运行日志里追加自审结论（角度/步频/速度是否会在平台侧露馅）
  3. 数据目录与旧版隔离：默认用 %LOCALAPPDATA%\\CRUN\\legacy，可 --data-dir 指定
"""
import json
import os
import shutil
import sys

APP_NAME = "校园跑助手"


def _legacy_roots():
    """优先用打包进来的 legacy 目录，其次用本机原版安装目录。"""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cands = [os.path.join(here, "legacy"), os.path.join(here, "legacy_site")]
    if getattr(sys, "_MEIPASS", None):
        cands = [os.path.join(sys._MEIPASS, "legacy"), os.path.join(sys._MEIPASS, "legacy_site")] + cands
    ext = [r"E:\校园跑助手\_internal"]
    return [c for c in cands if os.path.isdir(c)], [e for e in ext if os.path.isdir(e)]


def prepare_path():
    bundled, ext = _legacy_roots()
    for p in reversed(bundled):
        if p not in sys.path:
            sys.path.insert(0, p)
    return bundled, ext


def _count_accounts(db):
    try:
        import sqlite3
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        n = con.execute("select count(*) from tsn_account").fetchone()[0]
        con.close()
        return n
    except Exception:
        return -1


def _legacy_databases(bundled, ext):
    """找旧安装里的 tsn_data.db（账号/路线都在里面）。"""
    found = []
    for d in ext:
        for src in (os.path.join(d, "tsn_data.db"), os.path.join(os.path.dirname(d), "tsn_data.db")):
            if os.path.exists(src):
                found.append(src)
    for d in bundled:
        src = os.path.join(d, "tsn_data.db")
        if os.path.exists(src):
            found.append(src)
    try:
        from .migrate import _keyword_dirs
        for d in _keyword_dirs(max_depth=2, budget_s=4.0):
            src = os.path.join(d, "tsn_data.db")
            if os.path.exists(src):
                found.append(src)
    except Exception:
        pass
    return found


def ensure_data_dir(data_dir, legacy_dirs):
    """原版把 tsn_data.db / device_profiles.json 当相对路径用，先把它们准备好。"""
    os.makedirs(data_dir, exist_ok=True)
    db = os.path.join(data_dir, "tsn_data.db")
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    base = getattr(sys, "_MEIPASS", None) or here
    stamp = __import__("time").strftime("%Y%m%d-%H%M%S")

    # 1) 用旧安装的库优先（里面才有账号和路线）；只有找不到时才放干净的学校库
    old_dbs = [p for p in _legacy_databases(legacy_dirs[:2] if legacy_dirs else [], legacy_dirs)
               if _count_accounts(p) > 0]
    if not old_dbs or not os.path.exists(db) or _count_accounts(db) == 0:
        for src in old_dbs:
            if os.path.abspath(src) == os.path.abspath(db):
                break
            try:
                if os.path.exists(db):
                    shutil.copyfile(db, db.replace(".db", ".backup-%s.db" % stamp))
                shutil.copyfile(src, db)
                _boot_log("已从旧安装导入数据库: %s" % src, data_dir)
                break
            except OSError:
                continue

    if not os.path.exists(db):
        for cand in (os.path.join(base, "assets", "tsn_data.db"), os.path.join(here, "assets", "tsn_data.db")):
            if os.path.exists(cand):
                shutil.copyfile(cand, db)
                break

    # 设备指纹文件：原版读 device_profiles.json，缺了会报 Errno 2
    prof = os.path.join(data_dir, "device_profiles.json")
    if not os.path.exists(prof):
        for cand in (os.path.join(base, "device_profiles.json"),
                     os.path.join(base, "assets", "device_profiles.json"),
                     os.path.join(base, "legacy", "device_profiles.json"),
                     os.path.join(here, "assets", "device_profiles.json")):
            try:
                if os.path.exists(cand):
                    shutil.copyfile(cand, prof)
                    break
            except OSError:
                pass
    if not os.path.exists(prof):
        try:                       # 实在找不到就写一份默认的，别让程序带着 ENOENT 跑
            with open(prof, "w", encoding="utf-8") as f:
                json.dump({"host::DEFAULT": {
                    "brand": "Redmi", "model": "2409BRN2CC", "osver": "14",
                    "a_list": "arm64-v8a,armeabi-v7a",
                    "android_id": "96482f740870aaab", "device_name": "2409BRN2CC"}},
                    f, ensure_ascii=False, indent=2)
        except OSError:
            pass

    # 这些目录原版会往里写东西，先建好，省得运行到一半 Errno 2
    for sub in ("logs", "faces", "face", "images", "out"):
        try:
            os.makedirs(os.path.join(data_dir, sub), exist_ok=True)
        except OSError:
            pass
    return db


def apply_patches(log=print):
    """给原版打补丁：路线平滑 + 自审日志。失败不影响主流程。"""
    try:
        import tsnRunServer as S
    except Exception as e:
        log("[增强] 载入 tsnRunServer 失败，跳过补丁：%s" % e)
        return

    orig = getattr(S, "genTiShiNengRunPathRepeat", None)
    if orig is None:
        return

    def patched(pointList, needDistance, startTimeStamp, planUseTime, isPublic=True, options=None):
        pts, ids, dist = orig(pointList, needDistance, startTimeStamp, planUseTime, isPublic, options)
        try:
            from .routegen import _smooth, route_max_turn
            xy = [(p["latitude"], p["longitude"]) if isinstance(p, dict) else p for p in pts]
            turn = route_max_turn([(p[0], p[1]) for p in xy], 10.0)
            if turn > 35.0:
                smooth = _smooth([(p[0], p[1]) for p in xy], 1)
                for i, p in enumerate(pts):
                    if isinstance(p, dict) and i < len(smooth):
                        p["latitude"], p["longitude"] = smooth[i][0], smooth[i][1]
                log("[增强] 轨迹最大转角 %.1f° > 35°，已平滑" % turn)
            else:
                log("[增强] 轨迹最大转角 %.1f°，无需平滑" % turn)
        except Exception as e:
            log("[增强] 平滑失败（不影响上传）：%s" % e)
        return pts, ids, dist

    S.genTiShiNengRunPathRepeat = patched
    for mod in list(sys.modules.values()):
        if getattr(mod, "genTiShiNengRunPathRepeat", None) is orig:
            setattr(mod, "genTiShiNengRunPathRepeat", patched)
    log("[增强] 已启用路线平滑与转角自检")

    # 上传前自审：把要提交的轨迹先算一遍，别把明显异常的数据送上去
    try:
        _patch_upload_guard(S, log)
    except Exception as e:
        log("[增强] 上传自审挂载失败（不影响原功能）：%s" % e)


def _points_of(path):
    """尽量把原版的 path 结构解析成 [(lat, lon, t?)]。"""
    pts = []
    if isinstance(path, dict):
        path = path.get("points") or path.get("pointList") or path.get("path") or []
    for p in path or []:
        try:
            if isinstance(p, dict):
                lat = p.get("latitude", p.get("lat"))
                lon = p.get("longitude", p.get("lng", p.get("lon")))
                t = p.get("timestamp", p.get("time"))
            else:
                lat, lon = p[0], p[1]
                t = p[2] if len(p) > 2 else None
            if lat is None or lon is None:
                continue
            pts.append((float(lat), float(lon), float(t) if t is not None else None))
        except Exception:
            continue
    return pts


def _patch_upload_guard(S, log):
    cls = getattr(S, "TsnRunServer", None)
    if cls is None or not hasattr(cls, "uploadRunPath"):
        return
    orig_upload = cls.uploadRunPath

    def uploadRunPath(self, path, stepNumbers, sumDistance, *a, **kw):
        try:
            pts = _points_of(path)
            if len(pts) > 10:
                from .routegen import route_max_turn
                from .geo import haversine
                turn = route_max_turn([(p[0], p[1]) for p in pts], 10.0)
                dist = sum(haversine(pts[i], pts[i + 1]) for i in range(len(pts) - 1))
                dur = None
                ts = [p[2] for p in pts if p[2]]
                if len(ts) > 2:
                    dur = max(ts) - min(ts)
                speed = (dist / dur) if dur and dur > 0 else None
                step_ratio = (float(stepNumbers) * 0.75 / dist) if dist > 0 and stepNumbers else None
                log("[自审] 上传前：%d 点 / %.0f 米 / 最大转角 %.1f°%s%s" % (
                    len(pts), dist, turn,
                    " / 均速 %.2f m/s" % speed if speed else "",
                    " / 步数比 %.2f" % step_ratio if step_ratio else ""))
                bad = []
                if turn > 60:
                    bad.append("转角 %.0f°" % turn)
                if speed and speed > 8.0:
                    bad.append("均速 %.2f m/s" % speed)
                if step_ratio and not (0.6 <= step_ratio <= 1.6):
                    bad.append("步数比 %.2f" % step_ratio)
                if bad:
                    msg = "轨迹自审异常：" + "，".join(bad)
                    log("[自审] " + msg)
                    if os.environ.get("CRUN_STRICT") == "1":
                        raise RuntimeError(msg + "（CRUN_STRICT=1，已拦截上传）")
        except RuntimeError:
            raise
        except Exception as e:
            log("[自审] 检查失败（放行）：%s" % e)
        return orig_upload(self, path, stepNumbers, sumDistance, *a, **kw)

    cls.uploadRunPath = uploadRunPath
    log("[增强] 已挂载上传前自审（默认只记录，CRUN_STRICT=1 时拦截）")


def _writable(d):
    try:
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, ".w")
        open(p, "w").close()
        os.remove(p)
        return True
    except Exception:
        return False


def _default_data_dir():
    cands = [
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "CRUN", "legacy"),
        os.path.join(os.path.expanduser("~"), "CRUN", "legacy"),
        os.path.join(os.path.expanduser("~"), "Documents", "CRUN", "legacy"),
        os.path.join(os.getcwd(), "CRUN-legacy"),
        os.path.join(os.environ.get("TEMP", os.getcwd()), "CRUN-legacy"),
    ]
    for c in cands:
        if c and _writable(c):
            return c
    return os.getcwd()


def _boot_log(msg, data_dir=None):
    try:
        base = data_dir or os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "CRUN")
        os.makedirs(base, exist_ok=True)
        with open(os.path.join(base, "crun-launch.log"), "a", encoding="utf-8") as f:
            f.write("%s %s\n" % (__import__("time").strftime("%H:%M:%S"), msg))
    except Exception:
        pass


def _polish_ui():
    """套一层更好看的主题：深色 + 绿色强调色 + 高 DPI 清晰字体。"""
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass
    try:
        import customtkinter as ctk
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("green")
    except Exception:
        pass


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    data_dir = None
    i = 0
    while i < len(argv):
        if argv[i] == "--data-dir" and i + 1 < len(argv):
            data_dir = argv[i + 1]
            i += 2
        else:
            i += 1

    _boot_log("start", data_dir)
    _polish_ui()
    bundled, ext = prepare_path()
    _boot_log("legacy paths: %s" % (bundled or ext))
    data_dir = data_dir or _default_data_dir()
    _boot_log("data dir: %s" % data_dir)
    db = ensure_data_dir(data_dir, bundled + ext)
    os.chdir(data_dir)          # 原版要求工作目录里有 tsn_data.db
    _boot_log("db: %s exists=%s" % (db, os.path.exists(db)))
    print("数据目录：%s" % data_dir)
    print("数据库  ：%s (%s)" % (db, "存在" if os.path.exists(db) else "缺失"))

    apply_patches(_boot_log)

    try:
        import gui_app
        _boot_log("gui_app imported")
        app = gui_app.App()
        _boot_log("App constructed, entering mainloop")
        app.mainloop()
        _boot_log("mainloop returned")
    except Exception:
        import traceback
        _boot_log("LAUNCH FAILED:\n" + traceback.format_exc())
        try:
            import tkinter.messagebox as mb
            mb.showerror("启动失败", traceback.format_exc()[-1200:])
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
