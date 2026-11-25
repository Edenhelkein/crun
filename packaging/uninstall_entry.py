"""CRUN 卸载程序（独立 exe）。

  crun-uninstall.exe            图形确认
  crun-uninstall.exe --yes      静默卸载（保留用户数据）
  crun-uninstall.exe --yes --purge-data   连数据目录一起删（账号/路线会没）
"""
import os
import shutil
import subprocess
import sys
import time

APP = "CRUN"
REG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\CRUN"


def _pids_under(path):
    try:
        ps = ("Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.Path -like '%s\\*' } "
              "| ForEach-Object { $_.Id }" % path.replace("'", "''"))
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                             capture_output=True, text=True, timeout=20)
        return [int(x) for x in out.stdout.split() if x.strip().isdigit()]
    except Exception:
        return []


def _default_dir():
    return os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "Programs", APP)


def uninstall(dst=None, purge_data=False, log=print):
    dst = dst or _default_dir()
    data = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), APP)

    for p in _pids_under(dst) + _pids_under(data):
        try:
            subprocess.run(["taskkill", "/PID", str(p), "/F"], capture_output=True, timeout=10)
            log("已结束进程 %d" % p)
        except Exception:
            pass
    time.sleep(0.6)

    for lnk in (os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu",
                             "Programs", APP + ".lnk"),
                os.path.join(os.environ.get("USERPROFILE", ""), "Desktop", APP + ".lnk")):
        try:
            os.remove(lnk)
            log("已删除快捷方式 %s" % lnk)
        except OSError:
            pass

    try:
        import winreg
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, REG_KEY)
        log("已删除卸载表项")
    except OSError:
        pass

    if purge_data:
        shutil.rmtree(data, ignore_errors=True)
        log("已删除数据目录 %s" % data)
    else:
        log("用户数据保留在 %s" % data)

    # 自己在安装目录里，先退出去再删
    script = ('start "" /min cmd /c "ping -n 2 127.0.0.1 >nul & rmdir /s /q \\"%s\\""' % dst)
    subprocess.Popen(script, shell=True, creationflags=0x00000008,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    log("安装目录将在 2 秒后删除：%s" % dst)
    return {"dir": dst, "purged_data": purge_data}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    yes = "--yes" in argv or "-y" in argv
    purge = "--purge-data" in argv
    dst = None
    if "--dir" in argv:
        i = argv.index("--dir")
        if i + 1 < len(argv):
            dst = argv[i + 1]

    if not yes:
        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            msg = ("确定要卸载「校园跑助手」吗？\n\n"
                   "· 会删除程序目录、桌面/开始菜单快捷方式和卸载表项\n"
                   "· 账号、路线等用户数据默认保留在 %LOCALAPPDATA%\\CRUN")
            if not messagebox.askyesno("卸载 %s" % APP, msg):
                return 0
            purge = messagebox.askyesno("删除用户数据？",
                                        "要不要连账号、路线数据一起删掉？\n选「否」则保留，下次装回来还能用。")
            root.destroy()
        except Exception:
            pass

    res = uninstall(dst, purge)
    if not yes:
        try:
            import tkinter as tk
            from tkinter import messagebox
            r = tk.Tk(); r.withdraw()
            messagebox.showinfo("卸载完成", "程序已卸载。\n用户数据：%s" %
                                ("已删除" if res["purged_data"] else "已保留"))
            r.destroy()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
