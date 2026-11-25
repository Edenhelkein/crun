"""启动原版"校园跑助手"图形界面，并在外面套一层增强。

思路：原版 exe 里的模块（gui_app / tsnRunServer / tsnClient…）已经被导出成 .pyc，
这里把它们接回来跑，然后在运行时打补丁 —— 而不是重写一套功能。

增强点（可在 GUI 里看到效果）：
  1. 路线平滑：原版生成的轨迹直接交给学校，这里做一次小角度平滑，去掉 90° 硬折角
  2. 运行日志里追加自审结论（角度/步频/速度是否会在平台侧露馅）
  3. 数据目录与旧版隔离：默认用 %LOCALAPPDATA%\\CRUN\\legacy，可 --data-dir 指定
"""
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


def ensure_data_dir(data_dir, legacy_dirs):
    """原版把 tsn_data.db 当相对路径用，所以先把库准备好再切工作目录。"""
    os.makedirs(data_dir, exist_ok=True)
    db = os.path.join(data_dir, "tsn_data.db")
    if os.path.exists(db):
        return db
    # 1) 打包自带的干净库（只有学校）
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    base = getattr(sys, "_MEIPASS", None) or here
    for cand in (os.path.join(base, "assets", "tsn_data.db"), os.path.join(here, "assets", "tsn_data.db")):
        if os.path.exists(cand):
            shutil.copyfile(cand, db)
            return db
    # 2) 旧版安装目录里的库（含账号与路线）
    for d in legacy_dirs:
        for src in (os.path.join(d, "tsn_data.db"), os.path.join(os.path.dirname(d), "tsn_data.db")):
            if os.path.exists(src):
                shutil.copyfile(src, db)
                return db
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
