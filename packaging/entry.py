"""打包入口：PyInstaller 冻结后由 crun.exe 调用。"""
import os
import sys
import traceback

APP = "crun"


def _log_path():
    """找一个真能写的位置，否则崩溃信息就丢了。"""
    import tempfile
    cands = [
        os.environ.get("CRUN_LOG"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "CRUN", "crun-error.log"),
        os.path.join(os.path.expanduser("~"), "CRUN", "crun-error.log"),
        os.path.join(tempfile.gettempdir(), "crun-error.log"),
        os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "crun-error.log"),
    ]
    for c in cands:
        if not c:
            continue
        try:
            os.makedirs(os.path.dirname(c), exist_ok=True)
            with open(c, "a", encoding="utf-8"):
                pass
            return c
        except Exception:
            continue
    return os.path.join(tempfile.gettempdir(), "crun-error.log")


def _fix_streams():
    """窗口模式（console=False）下 sys.stdout/stderr 是 None，print 会直接崩。"""
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))
        try:
            getattr(sys, name).reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _install_crash_log():
    def hook(exc_type, exc, tb):
        try:
            os.makedirs(os.path.dirname(_log_path()), exist_ok=True)
            with open(_log_path(), "a", encoding="utf-8") as f:
                f.write("\n=== %s ===\n" % __import__("time").strftime("%Y-%m-%d %H:%M:%S"))
                traceback.print_exception(exc_type, exc, tb, file=f)
        except Exception:
            pass
        try:
            import tkinter.messagebox as mb
            mb.showerror("出错了", "%s\n\n详细信息已写到：\n%s" % (exc, _log_path()))
        except Exception:
            pass
    sys.excepthook = hook


def _hide_console():
    """把控制台窗口藏起来：GUI 应用不该带一个黑窗口，叉掉它还会把程序一起关掉。

    设置 CRUN_KEEP_CONSOLE=1 可以保留（调试用）。
    """
    if os.environ.get("CRUN_KEEP_CONSOLE"):
        return
    try:
        import ctypes
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)   # SW_HIDE
    except Exception:
        pass


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    _fix_streams()
    _install_crash_log()
    _hide_console()
    from crun.cli import main
    sys.exit(main())
