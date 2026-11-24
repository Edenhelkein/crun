"""打包入口：PyInstaller 冻结后由 crun.exe 调用。"""
import sys
import multiprocessing


def _utf8_console():
    """中文输出在 GBK 控制台会变乱码，冻结后强制 UTF-8（失败就退回原样）。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


if __name__ == "__main__":
    multiprocessing.freeze_support()
    _utf8_console()
    from crun.cli import main
    sys.exit(main())
