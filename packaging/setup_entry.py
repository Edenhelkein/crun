"""CRUN 安装器（带 GUI，可静默）。

  crun-setup.exe                     图形安装
  crun-setup.exe --silent --dir <p>  静默安装
  crun-setup.exe --uninstall --dir <p>  卸载

安装内容：解压程序包 -> 迁移旧版数据 -> 开始菜单/桌面快捷方式 -> 卸载表登记。
不需要管理员权限：默认装到 %LOCALAPPDATA%\\Programs\\CRUN。
"""
import ctypes
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

APP_NAME = "CRUN"
try:
    from crun import __version__ as APP_VER
except Exception:
    APP_VER = "1.2.2"
PUBLISHER = "CRUN Studio"
REG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\CRUN"


def res(name):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


def payload_zip():
    for cand in ("payload/crun-%s-win64.zip" % APP_VER,):
        p = res(cand)
        if os.path.exists(p):
            return p
    base = res("payload")
    if os.path.isdir(base):
        for fn in os.listdir(base):
            if fn.endswith(".zip"):
                return os.path.join(base, fn)
    raise FileNotFoundError("安装器内没有程序包 payload")


def default_dir():
    return os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "Programs", APP_NAME)


def _ps(cmd):
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd],
                   capture_output=True, text=True)


def make_shortcut(lnk, target, workdir, args=""):
    _ps("$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%s');"
        "$s.TargetPath='%s';$s.Arguments='%s';$s.WorkingDirectory='%s';$s.IconLocation='%s';$s.Save()"
        % (lnk, target, args, workdir, target))


def _pids_under(dst):
    """列出正在从目标目录运行的进程（装新版前要先关掉，否则文件被占用）。"""
    try:
        ps = ("Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.Path -like '%s\\*' } "
              "| ForEach-Object { $_.Id }" % dst.replace("'", "''"))
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                             capture_output=True, text=True, timeout=20)
        return [int(x) for x in out.stdout.split() if x.strip().isdigit()]
    except Exception:
        return []


def _extract(zip_path, dst, log):
    """解压程序包；如果 zip 里套了一层同名文件夹（为了拖动方便），把它剥掉。"""
    for attempt in range(3):
        try:
            with zipfile.ZipFile(zip_path) as z:
                names = [n for n in z.namelist() if n and not n.endswith("/")]
                tops = {n.split("/")[0] for n in names}
                prefix = ""
                if len(tops) == 1:
                    top = next(iter(tops))
                    if all(n.startswith(top + "/") for n in names):
                        prefix = top + "/"
                for n in names:
                    rel = n[len(prefix):] if prefix and n.startswith(prefix) else n
                    if not rel:
                        continue
                    target = os.path.join(dst, rel.replace("/", os.sep))
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    with z.open(n) as src, open(target, "wb") as out:
                        shutil.copyfileobj(src, out)
            return True
        except PermissionError:
            pids = _pids_under(dst)
            if pids:
                log("检测到 CRUN 正在运行（PID %s），正在关闭…" % ",".join(map(str, pids)))
                for pid in pids:
                    subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, text=True)
            else:
                log("文件被占用（杀毒软件可能正在扫描），%.0f 秒后重试…" % 1.5)
            time.sleep(1.5)
    return False


def install(dst, import_legacy=True, desktop=True, launch=True, log=print):
    os.makedirs(dst, exist_ok=True)
    log("解压程序包…")
    if not _extract(payload_zip(), dst, log):
        raise RuntimeError("目标目录里的文件被占用，无法覆盖：\n%s\n\n"
                           "请先在任务管理器里结束所有 CRUN 进程，或用杀毒软件把该目录加入信任后重试。" % dst)

    with open(os.path.join(dst, "version.txt"), "w", encoding="utf-8") as f:
        f.write(APP_VER + "\n")

    # 清掉旧安装器误建的嵌套目录（crun-2.0.x-win64），免得新旧文件混在一起
    try:
        for name in os.listdir(dst):
            p = os.path.join(dst, name)
            if os.path.isdir(p) and name.startswith("crun-") and os.path.exists(os.path.join(p, "crun.exe")):
                shutil.rmtree(p, ignore_errors=True)
                log("已清理残留目录 %s" % name)
    except OSError:
        pass

    migrated = None
    if import_legacy:
        log("扫描旧版数据…")
        try:
            from crun.migrate import candidate_dirs, merge, scan
            dirs = [d for d in candidate_dirs() if os.path.normcase(os.path.abspath(d)) !=
                    os.path.normcase(os.path.abspath(dst))]
            found = scan(dirs)
            if found:
                migrated = merge(dst, [r["dir"] for r in found])
                migrated["scanned"] = [r["dir"] for r in found]
                log("已合并 %d 处旧数据" % len(found))
            else:
                log("没有发现旧版数据（已扫描 %d 个位置：桌面/下载/文档/用户目录/注册表）" % len(dirs))
                log("如果旧版放在别处，装完后运行：crun migrate --dir <你的旧版目录> --apply")
        except Exception as e:
            log("旧数据迁移跳过：%s" % e)

    exe = os.path.join(dst, "crun.exe")
    start_menu = os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs")
    try:
        if os.path.isdir(start_menu):
            make_shortcut(os.path.join(start_menu, APP_NAME + ".lnk"), exe, dst, "")
    except Exception as e:
        log("开始菜单快捷方式失败：%s" % e)
    if desktop:
        try:
            desk = os.path.join(os.environ.get("USERPROFILE", ""), "Desktop")
            if os.path.isdir(desk):
                make_shortcut(os.path.join(desk, APP_NAME + ".lnk"), exe, dst, "")
        except Exception as e:
            log("桌面快捷方式失败：%s" % e)

    # 卸载器：包内已带 crun-uninstall.exe，就不用再复制安装器自己
    try:
        uni = os.path.join(dst, "uninstall.exe")
        if not os.path.exists(uni):
            shutil.copyfile(sys.executable, uni)
    except Exception:
        pass

    try:
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, REG_KEY) as k:
            winreg.SetValueEx(k, "DisplayName", 0, winreg.REG_SZ, APP_NAME)
            winreg.SetValueEx(k, "DisplayVersion", 0, winreg.REG_SZ, APP_VER)
            winreg.SetValueEx(k, "Publisher", 0, winreg.REG_SZ, PUBLISHER)
            winreg.SetValueEx(k, "InstallLocation", 0, winreg.REG_SZ, dst)
            winreg.SetValueEx(k, "DisplayIcon", 0, winreg.REG_SZ, exe)
            winreg.SetValueEx(k, "UninstallString", 0, winreg.REG_SZ,
                              '"%s" --uninstall --dir "%s"' % (os.path.join(dst, "uninstall.exe"), dst))
            winreg.SetValueEx(k, "NoModify", 0, winreg.REG_DWORD, 1)
            winreg.SetValueEx(k, "NoRepair", 0, winreg.REG_DWORD, 1)
    except Exception as e:
        log("写卸载表失败：%s" % e)

    if launch:
        try:
            subprocess.Popen([exe], cwd=dst, creationflags=0x00000008,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass
    return {"dir": dst, "migrated": migrated}


def uninstall(dst, log=print):
    import winreg
    for p in (os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu",
                           "Programs", APP_NAME + ".lnk"),
              os.path.join(os.environ.get("USERPROFILE", ""), "Desktop", APP_NAME + ".lnk")):
        try:
            os.remove(p)
        except OSError:
            pass
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, REG_KEY)
    except OSError:
        pass
    # 自己在安装目录里，先让 cmd 等 1 秒再删目录
    subprocess.Popen('cmd /c ping -n 2 127.0.0.1 >nul & rmdir /s /q "%s"' % dst,
                     shell=True, creationflags=0x00000008,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {"uninstalled": dst}


# ---------------------------------------------------------------- GUI

def gui():
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox

    root = tk.Tk()
    root.title("%s 安装程序 %s" % (APP_NAME, APP_VER))
    root.geometry("600x560")
    root.minsize(600, 520)
    try:
        root.iconbitmap(default=res("icon.ico"))
    except Exception:
        pass

    style = ttk.Style()
    try:
        style.theme_use("clam")
    except Exception:
        pass
    bg, fg, accent = "#0e141c", "#e8eef6", "#3ee08f"
    root.configure(bg=bg)
    style.configure(".", background=bg, foreground=fg, fieldbackground="#0a1017")
    style.configure("TFrame", background=bg)
    style.configure("TLabel", background=bg, foreground=fg)
    style.configure("Hint.TLabel", foreground="#8595a8")
    style.configure("Title.TLabel", font=("Segoe UI", 22, "bold"))
    style.configure("Step.TLabel", foreground="#8595a8", font=("Segoe UI", 9))
    style.configure("TCheckbutton", background=bg, foreground=fg)
    style.configure("TEntry", fieldbackground="#0a1017", foreground=fg, insertcolor=fg)
    style.configure("TButton", padding=8)
    style.configure("Go.TButton", background=accent, foreground="#04140c", font=("Segoe UI", 11, "bold"))
    style.map("Go.TButton", background=[("active", "#54e8a2")])

    # ---- 底部按钮栏先 pack(side=bottom)，保证任何窗口尺寸下都可见 ----
    bar = ttk.Frame(root)
    bar.pack(side="bottom", fill="x", padx=24, pady=(0, 18))

    # ---- 顶部 ----
    head = ttk.Frame(root)
    head.pack(side="top", fill="x", padx=24, pady=(22, 4))
    ttk.Label(head, text=APP_NAME, style="Title.TLabel").pack(anchor="w")
    ttk.Label(head, text="校园跑会话控制台 · 版本 %s" % APP_VER, style="Hint.TLabel").pack(anchor="w")

    # ---- 安装位置 ----
    frm = ttk.Frame(root)
    frm.pack(side="top", fill="x", padx=24, pady=(14, 0))
    ttk.Label(frm, text="安装位置").pack(anchor="w")
    row = ttk.Frame(frm)
    row.pack(fill="x", pady=(4, 0))
    path_var = tk.StringVar(value=default_dir())
    ttk.Entry(row, textvariable=path_var).pack(side="left", fill="x", expand=True)

    def browse():
        p = filedialog.askdirectory(initialdir=path_var.get())
        if p:
            path_var.set(p)
    ttk.Button(row, text="浏览…", command=browse).pack(side="left", padx=(8, 0))

    # ---- 选项 ----
    opt = ttk.Frame(root)
    opt.pack(side="top", fill="x", padx=24, pady=(14, 0))
    ttk.Label(opt, text="安装选项", style="Step.TLabel").pack(anchor="w", pady=(0, 4))
    legacy = tk.BooleanVar(value=True)
    desk = tk.BooleanVar(value=True)
    run = tk.BooleanVar(value=True)
    ttk.Checkbutton(opt, text="导入旧版数据（账本 / 路线库 / 账号绑定）", variable=legacy).pack(anchor="w")
    ttk.Checkbutton(opt, text="创建桌面快捷方式", variable=desk).pack(anchor="w")
    ttk.Checkbutton(opt, text="安装完成后启动", variable=run).pack(anchor="w")

    # ---- 日志（可伸缩）----
    log_box = tk.Text(root, height=6, bg="#0a1017", fg="#8595a8", bd=0,
                      font=("Consolas", 9), wrap="word")
    log_box.pack(side="top", fill="both", expand=True, padx=24, pady=(12, 8))
    log_box.insert("end", "点右下角「开始安装」即可，全程无需管理员权限。\n")
    log_box.configure(state="disabled")

    def log(msg):
        log_box.configure(state="normal")
        log_box.insert("end", msg + "\n")
        log_box.see("end")
        log_box.configure(state="disabled")
        root.update_idletasks()

    def go():
        btn.state(["disabled"])
        btn.configure(text="安装中…")
        try:
            r = install(path_var.get(), legacy.get(), desk.get(), run.get(), log)
            log("安装完成：" + r["dir"])
            if r.get("migrated"):
                log("已合并旧数据：" + ", ".join(r["migrated"].get("scanned", [])))
            if run.get():
                log("正在启动…")
            messagebox.showinfo("安装完成", "已安装到\n%s\n\n桌面已创建快捷方式。" % r["dir"])
            root.after(300, root.destroy)
        except Exception as e:
            log("失败：" + str(e))
            messagebox.showerror("安装失败", str(e))
            btn.configure(text="重试")
            btn.state(["!disabled"])

    ttk.Label(bar, text="安装到当前用户目录，不修改系统环境变量",
              style="Step.TLabel").pack(side="left")
    btn = ttk.Button(bar, text="开始安装", style="Go.TButton", command=go, width=18)
    btn.pack(side="right")

    root.mainloop()


def _log_line(msg):
    """无控制台构建里 sys.stdout 可能是 None，静默模式统一写日志文件。"""
    try:
        if sys.stdout:
            sys.stdout.write(str(msg) + "\n")
            sys.stdout.flush()
    except Exception:
        pass
    try:
        with open(os.path.join(tempfile.gettempdir(), "crun-setup.log"), "a", encoding="utf-8") as f:
            f.write(str(msg) + "\n")
    except Exception:
        pass


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        for s in (sys.stdout, sys.stderr):
            if s is not None:
                s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    args = {}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--silent":
            args["silent"] = True; i += 1
        elif a == "--dir":
            args["dir"] = argv[i + 1] if i + 1 < len(argv) else None; i += 2
        elif a == "--uninstall":
            args["uninstall"] = True; i += 1
        elif a == "--no-legacy":
            args["legacy"] = False; i += 1
        elif a == "--no-desktop":
            args["desktop"] = False; i += 1
        else:
            i += 1
    dst = args.get("dir") or default_dir()
    try:
        if args.get("uninstall"):
            _log_line(json.dumps(uninstall(dst), ensure_ascii=False))
            return 0
        if args.get("silent"):
            r = install(dst, args.get("legacy", True), args.get("desktop", True), False, _log_line)
            _log_line(json.dumps(r, ensure_ascii=False))
            return 0
        gui()
        return 0
    except Exception as e:
        import traceback
        _log_line("FATAL: %s\n%s" % (e, traceback.format_exc()))
        if not args.get("silent"):
            try:
                import tkinter.messagebox as mb
                mb.showerror("安装失败", str(e))
            except Exception:
                pass
        return 1


if __name__ == "__main__":
    sys.exit(main())
