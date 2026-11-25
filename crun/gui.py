"""桌面界面（customtkinter）：沿用原版"校园跑助手"的三步式布局。

晨跑 / 自由跑 / 阳光跑 三种类型；参数用大白话（距离、配速），不再有"出车"这种黑话。
底层仍走 crun.engine：路线随机化 + 平台硬约束 + 16 项自审。
"""
import json
import os
import queue
import threading
import time
import traceback

import customtkinter as ctk

from . import __version__
from .blacklist import fingerprint
from .engine import run_session

MODES = [("morning_run", "晨跑", "早上 6:00-9:00，配速偏慢"),
         ("free_run", "自由跑", "任意时间，配速自定"),
         ("sunshine_run", "阳光跑", "白天课外，按学校配额")]

MODE_PACE = {"morning_run": 420, "free_run": 360, "sunshine_run": 390}


def _writable(d):
    try:
        os.makedirs(d, exist_ok=True)
        probe = os.path.join(d, ".write_test")
        with open(probe, "w", encoding="utf-8") as f:
            f.write("1")
        os.remove(probe)
        return True
    except Exception:
        return False


def resolve_work_dir(preferred=None):
    """找一个真的能写的目录，别因为权限直接崩。"""
    cands = []
    if preferred:
        cands.append(preferred)
    if os.environ.get("CRUN_WORK"):
        cands.append(os.environ["CRUN_WORK"])
    cands += [
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "CRUN"),
        os.path.join(os.path.expanduser("~"), "CRUN"),
        os.path.join(os.path.expanduser("~"), "Documents", "CRUN"),
        os.getcwd(),
        os.path.join(os.environ.get("TEMP", os.getcwd()), "CRUN"),
    ]
    for d in cands:
        if d and _writable(d):
            return d
    return os.getcwd()


class App(ctk.CTk):
    def __init__(self, work_dir=None):
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("green")

        self.work = resolve_work_dir(work_dir)

        self.title("校园跑助手 %s" % __version__)
        self.geometry("1040x700")
        self.minsize(980, 640)

        self.mode = "morning_run"
        self.q = queue.Queue()
        self._build()
        self.after(100, self._drain)

    # ---------------------------------------------------------------- 布局
    def _build(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        side = ctk.CTkFrame(self, width=210, corner_radius=0)
        side.grid(row=0, column=0, sticky="nsw")
        side.grid_propagate(False)
        ctk.CTkLabel(side, text="校园跑助手", font=("Microsoft YaHei UI", 20, "bold")).pack(padx=18, pady=(24, 2), anchor="w")
        ctk.CTkLabel(side, text="v%s · 反侦测版" % __version__, text_color="#7d8b9c",
                     font=("Microsoft YaHei UI", 11)).pack(padx=18, anchor="w")
        for i, (txt, sub) in enumerate([("① 选跑步类型", "晨跑 / 自由跑 / 阳光跑"),
                                        ("② 填跑步参数", "距离、配速"),
                                        ("③ 生成路线", "随机且不重复"),
                                        ("④ 开始跑步", "生成数据并自审")]):
            f = ctk.CTkFrame(side, fg_color="transparent")
            f.pack(fill="x", padx=14, pady=(16 if i == 0 else 6, 0))
            ctk.CTkLabel(f, text=txt, font=("Microsoft YaHei UI", 13, "bold"), anchor="w").pack(anchor="w")
            ctk.CTkLabel(f, text=sub, font=("Microsoft YaHei UI", 10), text_color="#7d8b9c", anchor="w").pack(anchor="w")

        ctk.CTkLabel(side, text="数据目录", font=("Microsoft YaHei UI", 10), text_color="#7d8b9c").pack(
            side="bottom", padx=18, pady=(0, 4), anchor="w")
        ctk.CTkLabel(side, text=self.work, font=("Microsoft YaHei UI", 9), text_color="#5b6a7a",
                     wraplength=180, justify="left").pack(side="bottom", padx=18, anchor="w")

        main = ctk.CTkFrame(self, fg_color="transparent")
        main.grid(row=0, column=1, sticky="nsew", padx=(0, 0), pady=0)
        main.grid_columnconfigure(0, weight=3)
        main.grid_columnconfigure(1, weight=2)
        main.grid_rowconfigure(2, weight=1)

        # ---- ① 跑步类型 ----
        top = ctk.CTkFrame(main, corner_radius=12)
        top.grid(row=0, column=0, columnspan=2, sticky="ew", padx=16, pady=(16, 8))
        ctk.CTkLabel(top, text="① 选择跑步类型", font=("Microsoft YaHei UI", 14, "bold")).pack(anchor="w", padx=16, pady=(14, 6))
        self.mode_var = ctk.StringVar(value="morning_run")
        row = ctk.CTkFrame(top, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(0, 14))
        self.mode_btns = {}
        for key, label, hint in MODES:
            b = ctk.CTkButton(row, text="%s\n%s" % (label, hint), width=210, height=56,
                              font=("Microsoft YaHei UI", 12), corner_radius=10,
                              command=lambda k=key: self._pick_mode(k))
            b.pack(side="left", padx=(0, 10))
            self.mode_btns[key] = b

        # ---- ② 参数 ----
        form = ctk.CTkFrame(main, corner_radius=12)
        form.grid(row=1, column=0, sticky="nsew", padx=(16, 8), pady=8)
        ctk.CTkLabel(form, text="② 跑步参数", font=("Microsoft YaHei UI", 14, "bold")).pack(anchor="w", padx=16, pady=(14, 8))

        g = ctk.CTkFrame(form, fg_color="transparent")
        g.pack(fill="x", padx=16)
        ctk.CTkLabel(g, text="距离（公里）", width=100, anchor="w").grid(row=0, column=0, pady=6, sticky="w")
        self.dist = ctk.CTkEntry(g, width=120)
        self.dist.insert(0, "2.0")
        self.dist.grid(row=0, column=1, sticky="w")
        ctk.CTkLabel(g, text="配速（分钟/公里）", width=140, anchor="w").grid(row=1, column=0, pady=6, sticky="w")
        self.pace = ctk.CTkEntry(g, width=120)
        self.pace.insert(0, "7:00")
        self.pace.grid(row=1, column=1, sticky="w")
        ctk.CTkLabel(g, text="账号（学号）", width=100, anchor="w").grid(row=2, column=0, pady=6, sticky="w")
        self.account = ctk.CTkEntry(g, width=220)
        self.account.insert(0, os.environ.get("CRUN_ACCOUNT", "260901100106"))
        self.account.grid(row=2, column=1, sticky="w")
        ctk.CTkLabel(g, text="设备指纹", width=100, anchor="w").grid(row=3, column=0, pady=6, sticky="w")
        self.device = ctk.CTkEntry(g, width=220)
        self.device.insert(0, fingerprint("Redmi 2409BRN2CC", "AP3A", "96482f740870aaab"))
        self.device.grid(row=3, column=1, sticky="w")

        btns = ctk.CTkFrame(form, fg_color="transparent")
        btns.pack(fill="x", padx=16, pady=(10, 14))
        self.btn_route = ctk.CTkButton(btns, text="③ 生成路线", height=40, command=self.on_route)
        self.btn_route.pack(side="left", padx=(0, 10))
        self.btn_run = ctk.CTkButton(btns, text="④ 开始跑步", height=40, fg_color="#2fbf7a",
                                     hover_color="#43e595", command=self.on_run)
        self.btn_run.pack(side="left")

        # ---- 右侧自审 ----
        right = ctk.CTkFrame(main, corner_radius=12)
        right.grid(row=1, column=1, sticky="nsew", padx=(8, 16), pady=8)
        ctk.CTkLabel(right, text="反侦测自审", font=("Microsoft YaHei UI", 14, "bold")).pack(anchor="w", padx=16, pady=(14, 2))
        self.score = ctk.CTkLabel(right, text="—", font=("Microsoft YaHei UI", 34, "bold"), text_color="#3ee08f")
        self.score.pack(anchor="w", padx=16)
        self.verdict = ctk.CTkLabel(right, text="等待生成", font=("Microsoft YaHei UI", 12), text_color="#7d8b9c")
        self.verdict.pack(anchor="w", padx=16, pady=(0, 8))
        self.checks = ctk.CTkScrollableFrame(right, height=210, fg_color="#0d131a")
        self.checks.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        # ---- 日志 ----
        logf = ctk.CTkFrame(main, corner_radius=12)
        logf.grid(row=2, column=0, columnspan=2, sticky="nsew", padx=16, pady=(8, 16))
        ctk.CTkLabel(logf, text="运行日志", font=("Microsoft YaHei UI", 12, "bold")).pack(anchor="w", padx=16, pady=(10, 4))
        self.logbox = ctk.CTkTextbox(logf, height=150, font=("Consolas", 11))
        self.logbox.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self._pick_mode("morning_run")
        self._say("数据目录：%s" % self.work)
        self._say("提示：跑步前请在手机上完全退出体适能 App（同账号同时在线会被判违规）。")

    # ---------------------------------------------------------------- 交互
    def _pick_mode(self, key):
        self.mode = key
        for k, b in self.mode_btns.items():
            b.configure(fg_color="#2fbf7a" if k == key else "#243040")
        label = dict((k, l) for k, l, _ in MODES)[key]
        self._say("已选跑步类型：%s" % label)
        self.pace.delete(0, "end")
        self.pace.insert(0, self._fmt_pace(MODE_PACE[key]))

    @staticmethod
    def _fmt_pace(sec):
        return "%d:%02d" % (sec // 60, sec % 60)

    def _pace_seconds(self):
        try:
            txt = self.pace.get().strip()
            if ":" in txt:
                m, s = txt.split(":")
                return int(m) * 60 + int(s)
            return int(float(txt) * 60)
        except Exception:
            return MODE_PACE[self.mode]

    def _say(self, msg):
        self.logbox.insert("end", time.strftime("[%H:%M:%S] ") + msg + "\n")
        self.logbox.see("end")

    def _cfg(self, generate_only=False):
        km = float(self.dist.get().strip() or 2.0)
        return {
            "distance_m": max(300.0, km * 1000.0),
            "pace_s_per_km": self._pace_seconds(),
            "account_id": self.account.get().strip() or "ANON",
            "device_fp": self.device.get().strip() or "NODEV",
            "mode": self.mode,
            "work_dir": self.work,
            "tries": 24,
        }

    def _busy(self, on):
        state = "disabled" if on else "normal"
        self.btn_run.configure(state=state)
        self.btn_route.configure(state=state)

    def on_route(self):
        self._busy(True)
        threading.Thread(target=self._work, args=(True,), daemon=True).start()

    def on_run(self):
        self._busy(True)
        threading.Thread(target=self._work, args=(False,), daemon=True).start()

    def _work(self, route_only):
        try:
            cfg = self._cfg()
            self.q.put(("log", "生成路线中（候选 %d 条）…" % cfg["tries"]))
            rep = run_session(cfg, out_dir=os.path.join(self.work, "out"))
            self.q.put(("report", rep))
        except Exception as e:
            self.q.put(("log", "失败：%s" % e))
            self.q.put(("log", traceback.format_exc().splitlines()[-1]))
        finally:
            self.q.put(("busy", False))

    def _drain(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "log":
                    self._say(payload)
                elif kind == "busy":
                    self._busy(payload)
                elif kind == "report":
                    self._render(payload)
        except queue.Empty:
            pass
        self.after(120, self._drain)

    def _render(self, rep):
        verdict = rep.get("verdict", "?")
        color = {"RUN": "#3ee08f", "THROTTLE": "#f0b354", "ABORT": "#ff5f6d"}.get(verdict, "#8b9bb0")
        self.verdict.configure(text=verdict, text_color=color)
        au = rep.get("audit")
        if au:
            self.score.configure(text="%.0f" % au["score"], text_color=color)
            for w in self.checks.winfo_children():
                w.destroy()
            for c in au["checks"]:
                row = ctk.CTkFrame(self.checks, fg_color="transparent")
                row.pack(fill="x", pady=1)
                ctk.CTkLabel(row, text=("✗ " if c["fail"] else "✓ ") + c["name"],
                             text_color="#ff5f6d" if c["fail"] else "#5b6a7a",
                             anchor="w", font=("Microsoft YaHei UI", 11)).pack(side="left")
                ctk.CTkLabel(row, text=c["detail"], text_color="#3d4a58",
                             font=("Consolas", 10)).pack(side="right")
        if rep.get("route"):
            m = rep["route"]
            self._say("路线指纹 %s · 重叠 %.2f · 转角 %.1f° · 候选 %d" % (
                m["fp"], m["overlap"], m.get("max_turn_deg", 0), m["candidates"]))
        if rep.get("session"):
            s = rep["session"]
            self._say("已生成 %.0f 米 / %d 秒 / 配速 %s" % (s["distance_m"], s["duration_s"],
                                                       self._fmt_pace(int(s["pace_s_per_km"]))))
        for a in rep.get("actions", [])[:3]:
            self._say("建议：" + a)
        if rep.get("action"):
            self._say(rep["action"])
        self._say("自审结论：%s" % verdict)


def main(work_dir=None):
    App(work_dir).mainloop()


if __name__ == "__main__":
    main()
