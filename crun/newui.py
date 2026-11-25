"""校园跑助手 · 新界面（三页）：准备 / 跑步 / 查询。

所有动作直接调用原版 SDK（crun.bridge），不再需要打开原版窗口。
"""
import os
import sqlite3
import sys
import threading

import customtkinter as ctk

FONT = "Microsoft YaHei UI"
BOLD = "bold"

P = {
    "bg": "#0F1115", "surface": "#191C22", "surface2": "#22262E", "line": "#2A2F38",
    "text": "#F2F4F7", "dim": "#8A93A0", "accent": "#7C9CFF", "accent_text": "#0A0F1F",
    "ok": "#4ADE80", "warn": "#FBBF24", "bad": "#F87171",
}

MODES = [("morning_run", "晨跑", "06:00 - 09:00"),
         ("free_run", "自由跑", "任意时间"),
         ("sunshine_run", "阳光跑", "白天课外")]


def data_dir():
    return os.environ.get("CRUN_WORK") or os.path.join(
        os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "CRUN", "legacy")


class Store:
    def __init__(self, d):
        self.dir = d
        self.db = os.path.join(d, "tsn_data.db")

    def q(self, sql, args=()):
        try:
            con = sqlite3.connect(f"file:{self.db}?mode=ro", uri=True)
            rows = con.execute(sql, args).fetchall()
            con.close()
            return rows
        except sqlite3.Error:
            return []

    @property
    def accounts(self):
        return [{"id": r[0], "username": r[1], "school_id": r[2], "user_id": r[3]}
                for r in self.q("select id, username, school_id, user_id from tsn_account")]

    @property
    def routes(self):
        return [(r[0], float(r[1] or 0)) for r in
                self.q("select run_path_id, sport_range from tsn_run_path order by sport_range")]

    @property
    def schools(self):
        r = self.q("select count(*) from tsn_school")
        return r[0][0] if r else 0


class App(ctk.CTk):
    def __init__(self, d=None):
        super().__init__()
        self.dir = d or data_dir()
        self.store = Store(self.dir)
        self.page = "prep"
        ctk.set_appearance_mode("dark")
        self.title("校园跑助手")
        self.geometry("1200x760")
        self.minsize(1040, 680)
        self.configure(fg_color=P["bg"])
        try:
            from customtkinter.windows.widgets.scaling.scaling_tracker import ScalingTracker
            self._s = float(ScalingTracker.get_window_scaling(self) or 1.0)
        except Exception:
            self._s = 1.0

        self._nav()
        self.body = ctk.CTkFrame(self, fg_color="transparent", width=self.X(980), height=self.X(696))
        self.body.place(x=self.X(220), y=self.X(64))
        self.show("prep")

    # ---------------------------------------------------------------- 基础
    def X(self, v):
        return int(round(v / self._s))

    def card(self, parent, **kw):
        kw.setdefault("fg_color", P["surface"])
        kw.setdefault("corner_radius", 14)
        kw.setdefault("border_width", 1)
        kw.setdefault("border_color", P["line"])
        return ctk.CTkFrame(parent, **kw)

    def lbl(self, parent, text, size=12, dim=False, bold=False, color=None, **kw):
        return ctk.CTkLabel(parent, text=text, font=(FONT, size, BOLD if bold else "normal"),
                            text_color=color or (P["dim"] if dim else P["text"]), **kw)

    def btn(self, parent, text, cmd=None, primary=False, w=130, h=38):
        kw = dict(width=self.X(w), height=self.X(h), corner_radius=10, text=text,
                  font=(FONT, 12, BOLD if primary else "normal"), command=cmd)
        if primary:
            kw.update(fg_color=P["accent"], hover_color="#93AFFF", text_color=P["accent_text"])
        else:
            kw.update(fg_color=P["surface2"], hover_color=P["line"], border_width=1,
                      border_color=P["line"], text_color=P["text"])
        return ctk.CTkButton(parent, **kw)

    def _nav(self):
        nav = ctk.CTkFrame(self, corner_radius=0, fg_color=P["surface"], width=self.X(220), height=self.X(760))
        nav.place(x=0, y=0)
        nav.pack_propagate(False)
        ctk.CTkLabel(nav, text="校园跑", font=(FONT, 18, BOLD), text_color=P["text"]).place(x=self.X(24), y=self.X(26))
        ctk.CTkLabel(nav, text="v2.3", font=(FONT, 10), text_color=P["dim"]).place(x=self.X(24), y=self.X(56))
        self.nav = {}
        for i, (k, name) in enumerate([("prep", "准备"), ("run", "跑步"), ("query", "查询")]):
            b = ctk.CTkButton(nav, text="   " + name, anchor="w", width=self.X(180), height=self.X(40),
                              corner_radius=9, font=(FONT, 12), fg_color="transparent",
                              hover_color=P["surface2"], text_color=P["text"],
                              command=lambda key=k: self.show(key))
            b.place(x=self.X(20), y=self.X(110 + i * 46))
            self.nav[k] = b
        ctk.CTkLabel(nav, text="数据目录", font=(FONT, 10), text_color=P["dim"]).place(x=self.X(24), y=self.X(690))
        ctk.CTkLabel(nav, text=self.dir, font=(FONT, 9), text_color="#5B6472", wraplength=self.X(180),
                     justify="left").place(x=self.X(24), y=self.X(708))

    def show(self, key):
        self.page = key
        for k, b in self.nav.items():
            b.configure(fg_color=P["surface2"] if k == key else "transparent",
                        text_color=P["accent"] if k == key else P["text"])
        for w in self.body.winfo_children():
            w.destroy()
        getattr(self, "_p_" + key)()

    def head(self, title, sub=""):
        self.lbl(self.body, title, size=22, bold=True).place(x=self.X(28), y=self.X(14))
        if sub:
            self.lbl(self.body, sub, size=11, dim=True).place(x=self.X(30), y=self.X(50))

    # ---------------------------------------------------------------- 日志区
    def logbox(self, parent, x, y, w, h):
        box = ctk.CTkTextbox(parent, width=self.X(w), height=self.X(h), font=("Consolas", 11),
                             fg_color="#0D0F13", text_color=P["dim"])
        box.place(x=self.X(x), y=self.X(y))
        return box

    def say(self, box, msg):
        try:
            box.insert("end", msg + "\n")
            box.see("end")
        except Exception:
            pass

    def bg(self, fn, *a):
        threading.Thread(target=fn, args=a, daemon=True).start()

    # ---------------------------------------------------------------- 准备页
    def _p_prep(self):
        self.head("准备", "学校、账号、路径、人脸 —— 跑之前先把这些弄好")

        # 学校
        c1 = self.card(self.body, width=self.X(300), height=self.X(150))
        c1.place(x=self.X(28), y=self.X(88))
        c1.pack_propagate(False)
        self.lbl(c1, "学校", size=13, bold=True).place(x=self.X(18), y=self.X(14))
        self.lbl(c1, "%d 所" % self.store.schools, size=26, bold=True).place(x=self.X(18), y=self.X(40))
        self.btn(c1, "更新学校列表", cmd=self.on_schools, w=150).place(x=self.X(18), y=self.X(96))

        # 账号
        c2 = self.card(self.body, width=self.X(600), height=self.X(150))
        c2.place(x=self.X(344), y=self.X(88))
        c2.pack_propagate(False)
        self.lbl(c2, "账号", size=13, bold=True).place(x=self.X(18), y=self.X(14))
        accs = self.store.accounts
        for i, a in enumerate(accs[:2]):
            self.lbl(c2, "%s · 学校 %s" % (a["username"], a["school_id"]), size=11).place(
                x=self.X(18 + i * 280), y=self.X(44))
            self.lbl(c2, "已授权" if a["user_id"] else "未授权", size=10, dim=True).place(
                x=self.X(18 + i * 280), y=self.X(66))
        self.ent_user = ctk.CTkEntry(c2, width=self.X(150), placeholder_text="学号")
        self.ent_user.place(x=self.X(18), y=self.X(96))
        self.ent_pwd = ctk.CTkEntry(c2, width=self.X(150), placeholder_text="密码", show="*")
        self.ent_pwd.place(x=self.X(180), y=self.X(96))
        self.btn(c2, "授权登录", cmd=self.on_login, primary=True, w=110).place(x=self.X(344), y=self.X(96))

        # 路径 + 人脸
        c3 = self.card(self.body, width=self.X(916), height=self.X(120))
        c3.place(x=self.X(28), y=self.X(252))
        c3.pack_propagate(False)
        self.lbl(c3, "路径", size=12, bold=True).place(x=self.X(18), y=self.X(16))
        self.lbl(c3, "%d 条历史路线" % len(self.store.routes), size=11, dim=True).place(x=self.X(18), y=self.X(40))
        self.btn(c3, "爬取路径", cmd=self.on_crawl, w=110).place(x=self.X(18), y=self.X(70))
        self.lbl(c3, "人脸", size=12, bold=True).place(x=self.X(300), y=self.X(16))
        self.lbl(c3, "从官方 App 拉取已上传的人脸", size=11, dim=True).place(x=self.X(300), y=self.X(40))
        self.btn(c3, "更新人脸", cmd=self.on_face, w=110).place(x=self.X(300), y=self.X(70))

        # 日志（就在准备页里，不单开页）
        logc = self.card(self.body, width=self.X(916), height=self.X(250))
        logc.place(x=self.X(28), y=self.X(386))
        logc.pack_propagate(False)
        self.lbl(logc, "运行日志", size=12, bold=True).place(x=self.X(18), y=self.X(10))
        self.log_prep = self.logbox(logc, 14, 36, 888, 200)
        self.say(self.log_prep, "就绪。数据目录：%s" % self.dir)

    # ---------------------------------------------------------------- 跑步页
    def _p_run(self):
        self.head("跑步", "选类型、距离、时间和步频，然后开始")

        c = self.card(self.body, width=self.X(916), height=self.X(300))
        c.place(x=self.X(28), y=self.X(88))
        c.pack_propagate(False)

        self.lbl(c, "类型", size=12, bold=True).place(x=self.X(20), y=self.X(16))
        self.mode_var = ctk.StringVar(value="晨跑")
        self.seg = ctk.CTkSegmentedButton(c, values=[m[1] for m in MODES], width=self.X(360),
                                          height=self.X(34), font=(FONT, 12),
                                          selected_color=P["accent"], selected_hover_color=P["accent"],
                                          fg_color=P["surface2"], text_color=P["text"])
        self.seg.set("晨跑")
        self.seg.place(x=self.X(90), y=self.X(12))

        self.lbl(c, "距离(km)", size=12, bold=True).place(x=self.X(20), y=self.X(66))
        self.ent_km = ctk.CTkEntry(c, width=self.X(100))
        self.ent_km.insert(0, "2.0")
        self.ent_km.place(x=self.X(110), y=self.X(62))

        self.lbl(c, "计划时间(分钟)", size=12, bold=True).place(x=self.X(20), y=self.X(110))
        self.ent_min = ctk.CTkEntry(c, width=self.X(100))
        self.ent_min.insert(0, "0")
        self.ent_min.place(x=self.X(140), y=self.X(106))

        self.lbl(c, "步频(spm)", size=12, bold=True).place(x=self.X(20), y=self.X(154))
        self.ent_cad = ctk.CTkEntry(c, width=self.X(100))
        self.ent_cad.insert(0, "0")
        self.ent_cad.place(x=self.X(110), y=self.X(150))

        self.lbl(c, "路线", size=12, bold=True).place(x=self.X(20), y=self.X(198))
        routes = self.store.routes
        self.route_map = {"自动（最久未用）": None}
        for rid, dist in routes[:40]:
            self.route_map["%.2f km · %s" % (dist, rid[-6:])] = rid
        self.opt_route = ctk.CTkOptionMenu(c, values=list(self.route_map), width=self.X(300),
                                           fg_color=P["surface2"], button_color=P["accent"],
                                           text_color=P["text"], font=(FONT, 11))
        self.opt_route.place(x=self.X(90), y=self.X(194))

        self.btn(c, "开始跑步", cmd=self.on_run, primary=True, w=160, h=44).place(x=self.X(20), y=self.X(240))
        self.lbl(c, "0 表示交给程序按距离自动算", size=10, dim=True).place(x=self.X(200), y=self.X(252))

        logc = self.card(self.body, width=self.X(916), height=self.X(300))
        logc.place(x=self.X(28), y=self.X(404))
        logc.pack_propagate(False)
        self.lbl(logc, "运行日志", size=12, bold=True).place(x=self.X(18), y=self.X(10))
        self.log_run = self.logbox(logc, 14, 36, 888, 250)

    # ---------------------------------------------------------------- 查询页
    def _p_query(self):
        self.head("查询", "看有效次数和里程")
        c = self.card(self.body, width=self.X(916), height=self.X(200))
        c.place(x=self.X(28), y=self.X(88))
        c.pack_propagate(False)
        accs = [a["username"] for a in self.store.accounts] or ["—"]
        self.opt_acc = ctk.CTkOptionMenu(c, values=accs, width=self.X(220), fg_color=P["surface2"],
                                         button_color=P["accent"], text_color=P["text"], font=(FONT, 12))
        self.opt_acc.place(x=self.X(20), y=self.X(18))
        self.btn(c, "查询", cmd=self.on_query, primary=True, w=110).place(x=self.X(260), y=self.X(18))
        self.q_result = self.lbl(c, "尚未查询", size=12, dim=True, justify="left")
        self.q_result.place(x=self.X(20), y=self.X(70))

    # ---------------------------------------------------------------- 动作
    def _log(self, box):
        return lambda m: self.after(0, self.say, box, str(m))

    def on_schools(self):
        log = self._log(self.log_prep)
        def job():
            from . import bridge
            log("开始更新学校列表…")
            try:
                ps = bridge.provinces(log)
                total = 0
                for pid, name in ps[:3]:
                    rows = bridge.schools_of_province(pid, log)
                    total += len(rows)
                log("完成（示例取前 3 个省份，共 %d 所学校）" % total)
            except Exception as e:
                log("失败：%s" % e)
        self.bg(job)

    def on_login(self):
        log = self._log(self.log_prep)
        user = self.ent_user.get().strip()
        pwd = self.ent_pwd.get().strip()
        if not user or not pwd:
            log("学号和密码都要填")
            return
        def job():
            from . import bridge
            log("正在授权 %s …" % user)
            try:
                import types
                acc = types.SimpleNamespace(user_id="", school_id=0, username=user,
                                            password=pwd, expires_in=0,
                                            mobile_device_id=None, access_token="")
                bridge.login(acc, log)
                log("授权完成")
            except Exception as e:
                log("授权失败：%s" % e)
        self.bg(job)

    def on_crawl(self):
        log = self._log(self.log_prep)
        def job():
            from . import bridge
            log("开始爬取路径…")
            try:
                bridge.crawl_paths(self.store.accounts[0]["id"], log)
            except Exception as e:
                log("爬取失败：%s" % e)
        self.bg(job)

    def on_face(self):
        log = self._log(self.log_prep)
        def job():
            from . import bridge
            log("开始更新人脸…")
            try:
                bridge.update_face(self.store.accounts[0]["id"], log)
            except Exception as e:
                log("更新失败：%s" % e)
        self.bg(job)

    def on_run(self):
        log = self._log(self.log_run)
        name = self.seg.get()
        key = next(k for k, cn, _ in MODES if cn == name)
        try:
            km = float(self.ent_km.get().strip() or 2.0)
            minutes = float(self.ent_min.get().strip() or 0) or None
            cadence = float(self.ent_cad.get().strip() or 0) or None
        except ValueError:
            log("参数填得不对")
            return
        def job():
            from . import bridge
            from tsnRunServer import TsnRunType
            t = {"morning_run": TsnRunType.morningRun, "free_run": TsnRunType.freedom,
                 "sunshine_run": TsnRunType.sumRun}[key]
            log("准备开跑：%.2f km / %s" % (km, name))
            try:
                bridge.run(self.store.accounts[0]["id"], km, t, minutes, cadence, log)
            except Exception as e:
                log("跑步失败：%s" % e)
        self.bg(job)

    def on_query(self):
        acc = self.opt_acc.get()
        rows = self.store.q("select count(*), coalesce(sum(sport_range),0) from tsn_run_path")
        n, dist = rows[0] if rows else (0, 0)
        self.q_result.configure(
            text="账号 %s\n路线 %d 条 · 合计 %.2f km\n（联网查询有效次数待接入）" % (acc, n, float(dist or 0)),
            text_color=P["text"])


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=None)
    ap.add_argument("--page", default="prep", choices=["prep", "run", "query"])
    a = ap.parse_args(argv)
    app = App(a.data_dir)
    if a.page != "prep":
        app.after(250, lambda: app.show(a.page))
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
