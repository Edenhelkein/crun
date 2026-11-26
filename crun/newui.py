"""校园跑助手 · 新界面（三页）：准备 / 跑步 / 查询。

所有动作直接调用原版 SDK（crun.bridge），不再需要打开原版窗口。
"""
import os
import shutil
import sqlite3
import sys
import threading
import time

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
        try:                       # 原版 SDK 用相对路径读 tsn_data.db，工作目录必须是数据目录
            os.makedirs(self.dir, exist_ok=True)
            os.chdir(self.dir)
        except OSError:
            pass
        self.store = Store(self.dir)
        self.db_state = "ok"
        try:
            from . import bridge
            # 每次启动先留一份备份（数据目录 + 用户目录各一份），再把被删空的库自愈回来
            if os.path.exists(self.store.db) and os.path.getsize(self.store.db) > 0:
                shutil.copyfile(self.store.db, os.path.join(self.dir, "tsn_data.backup-latest.db"))
                bridge.backup_now(self.store.db)
            self.db_state = bridge.ensure_db(self.store.db, log=lambda m: None)
        except Exception:
            self.db_state = "ok"
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
        self._prep_checklist()

        # 学校
        c1 = self.card(self.body, width=self.X(300), height=self.X(150))
        c1.place(x=self.X(28), y=self.X(214))
        c1.pack_propagate(False)
        self.lbl(c1, "学校", size=13, bold=True).place(x=self.X(18), y=self.X(14))
        self.school_count = self.lbl(c1, "%d 所" % self.store.schools, size=26, bold=True)
        self.school_count.place(x=self.X(18), y=self.X(40))
        self.btn(c1, "更新学校列表", cmd=self.on_schools, w=150).place(x=self.X(18), y=self.X(96))

        # 账号（单账号模式 + 登录安全闸）
        c2 = self.card(self.body, width=self.X(572), height=self.X(196))
        c2.place(x=self.X(344), y=self.X(214))
        c2.pack_propagate(False)
        self.lbl(c2, "账号", size=13, bold=True).place(x=self.X(18), y=self.X(12))
        self.lbl(c2, "同一助手同时登多个号会被判代跑 —— 建议只用一个", size=10,
                 color=P["warn"]).place(x=self.X(60), y=self.X(16))
        accs = self.store.accounts
        names = [a["username"] for a in accs] or ["—"]
        self.opt_login = ctk.CTkOptionMenu(c2, values=names, width=self.X(200),
                                           fg_color=P["surface2"], button_color=P["accent"],
                                           text_color=P["text"], font=(FONT, 12),
                                           command=lambda _v: self._fill_pwd())
        self.opt_login.place(x=self.X(18), y=self.X(44))
        self.ent_pwd = ctk.CTkEntry(c2, width=self.X(180), placeholder_text="密码", show="*")
        self.ent_pwd.place(x=self.X(230), y=self.X(44))
        self.btn(c2, "登录 / 复用", cmd=self.on_login, primary=True, w=120).place(
            x=self.X(424), y=self.X(44))
        self.lbl_account_state = self.lbl(c2, "", size=10, dim=True, justify="left")
        self.lbl_account_state.place(x=self.X(18), y=self.X(86))
        self.lbl(c2, "同一个号 15 分钟内不重复登录；换号要等 24 小时冷却（可用环境变量调整）",
                 size=9, color=P["dim"]).place(x=self.X(18), y=self.X(112))
        self.btn(c2, "登录体检", cmd=self.on_diagnose, w=90, h=30).place(x=self.X(18), y=self.X(140))
        self.btn(c2, "粘贴 token", cmd=self.on_paste_token, w=100, h=30).place(x=self.X(116), y=self.X(140))
        self._fill_pwd()
        self._refresh_login_state()

        # 路径 + 人脸
        c3 = self.card(self.body, width=self.X(916), height=self.X(120))
        c3.place(x=self.X(28), y=self.X(422))
        c3.pack_propagate(False)
        self.lbl(c3, "路径", size=12, bold=True).place(x=self.X(18), y=self.X(16))
        self.lbl(c3, "%d 条历史路线" % len(self.store.routes), size=11, dim=True).place(x=self.X(18), y=self.X(40))
        self.btn(c3, "爬取路径", cmd=self.on_crawl, w=110).place(x=self.X(18), y=self.X(70))
        self.lbl(c3, "人脸", size=12, bold=True).place(x=self.X(300), y=self.X(16))
        self.lbl(c3, "从官方 App 拉取已上传的人脸", size=11, dim=True).place(x=self.X(300), y=self.X(40))
        self.btn(c3, "更新人脸", cmd=self.on_face, w=110).place(x=self.X(300), y=self.X(70))

        # 日志（就在准备页里，不单开页）
        logc = self.card(self.body, width=self.X(916), height=self.X(140))
        logc.place(x=self.X(28), y=self.X(552))
        logc.pack_propagate(False)
        self.lbl(logc, "运行日志", size=12, bold=True).place(x=self.X(18), y=self.X(10))
        self.log_prep = self.logbox(logc, 14, 36, 888, 96)
        if getattr(self, "db_state", "ok") != "ok":
            self.say(self.log_prep, "⚠ 本地数据库缺失或损坏，已自动恢复到：%s" % self.db_state)
            self.say(self.log_prep, "   如果账号不见了，用学号+密码重新授权一次即可。")
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

        self.status_dot = self.lbl(c, "● 待机", size=13, bold=True, color=P["dim"])
        self.status_dot.place(x=self.X(600), y=self.X(246))
        self.status_time = self.lbl(c, "00:00", size=13, bold=True)
        self.status_time.place(x=self.X(760), y=self.X(246))
        self.status_bar = ctk.CTkProgressBar(c, width=self.X(916 - 40), height=self.X(6),
                                             progress_color=P["accent"], fg_color=P["surface2"],
                                             mode="indeterminate")
        self.status_bar.place(x=self.X(20), y=self.X(286))
        self.status_bar.set(0)

        logc = self.card(self.body, width=self.X(916), height=self.X(300))
        logc.place(x=self.X(28), y=self.X(404))
        logc.pack_propagate(False)
        self.lbl(logc, "运行日志", size=12, bold=True).place(x=self.X(18), y=self.X(10))
        self.log_run = self.logbox(logc, 14, 36, 888, 250)
        if not self.store.routes:
            self.say(self.log_run, "⚠ 本地还没有跑步路线。先去「准备」页点『爬取路径』，"
                                   "爬到至少一条路线，这里才能开跑。")
            self.set_status("无路线", P["warn"])

    # ---------------------------------------------------------------- 查询页
    def _p_query(self):
        self.head("查询", "联网查官方记录：有效次数、里程")
        c = self.card(self.body, width=self.X(916), height=self.X(120))
        c.place(x=self.X(28), y=self.X(88))
        c.pack_propagate(False)
        accs = [a["username"] for a in self.store.accounts] or ["—"]
        self.opt_acc = ctk.CTkOptionMenu(c, values=accs, width=self.X(220), fg_color=P["surface2"],
                                         button_color=P["accent"], text_color=P["text"], font=(FONT, 12))
        self.opt_acc.place(x=self.X(20), y=self.X(18))
        self.btn(c, "查询", cmd=self.on_query, primary=True, w=110).place(x=self.X(260), y=self.X(18))
        self.q_state = self.lbl(c, "点查询开始", size=11, dim=True)
        self.q_state.place(x=self.X(390), y=self.X(26))

        self.tiles = ctk.CTkFrame(self.body, fg_color="transparent", width=self.X(916), height=self.X(120))
        self.tiles.place(x=self.X(28), y=self.X(224))
        self.q_body = self.card(self.body, width=self.X(916), height=self.X(300))
        self.q_body.place(x=self.X(28), y=self.X(360))
        self.q_body.pack_propagate(False)
        self.q_result = self.lbl(self.q_body, "尚未查询", size=12, dim=True, justify="left")
        self.q_result.place(x=self.X(20), y=self.X(18))

    # ---------------------------------------------------------------- 动作
    def _log(self, box):
        return lambda m: self.after(0, self.say, box, str(m))

    def set_status(self, text, color=None):
        try:
            self.status_dot.configure(text="● " + text, text_color=color or P["text"])
        except Exception:
            pass

    def _tick(self):
        if not getattr(self, "running", False):
            return
        el = int(time.monotonic() - self.run_start)
        try:
            self.status_time.configure(text="%02d:%02d" % (el // 60, el % 60))
        except Exception:
            return
        self.after(500, self._tick)

    def _on_progress(self, line):
        self.say(self.log_run, line)
        if getattr(self, "running", False):
            self.set_status("跑步中", P["ok"])

    def _finish(self, ok, err):
        self.running = False
        try:
            self.status_bar.stop()
            self.status_bar.set(1 if ok else 0)
        except Exception:
            pass
        if ok:
            self.set_status("完成", P["ok"])
            self.say(self.log_run, "✅ 本次跑步结束")
        else:
            self.set_status("失败", P["bad"])
            self.say(self.log_run, "❌ " + err)

    def on_schools(self):
        log = self._log(self.log_prep)
        def job():
            from . import bridge
            log("开始更新学校列表（按省份抓取，写入 province_name）…")
            try:
                stat = bridge.update_schools(self.store.db, log)
                total = sum(c for _, c in stat)
                provs = len([n for n, _ in stat if n])
                log("完成：%d 个省份 / %d 所学校" % (provs, total))
                self.after(0, lambda: self.school_count.configure(text="%d 所" % total))
            except Exception as e:
                log("失败：%s" % e)
        self.bg(job)

    # ---------------------------------------------------------------- 账号 / 登录
    def _cur_account(self):
        name = self.opt_login.get() if hasattr(self, "opt_login") else ""
        for a in self.store.accounts:
            if a["username"] == name:
                return a
        return None

    def _fill_pwd(self):
        acc = self._cur_account()
        if not acc or not hasattr(self, "ent_pwd"):
            return
        row = self.store.q("select password from tsn_account where id=?", (acc["id"],))
        try:
            self.ent_pwd.delete(0, "end")
            if row and row[0][0]:
                self.ent_pwd.insert(0, row[0][0])
        except Exception:
            pass

    def _refresh_login_state(self, note=""):
        try:
            from . import safe_login
            rows = safe_login.summary(self.dir, self.store.accounts)
            txt = "　".join("%s %s（%s）" % ("●" if r["active"] else "○", r["username"], r["last_login"])
                            for r in rows)
            self.lbl_account_state.configure(text=(note + "\n" + txt) if note else txt)
        except Exception:
            pass

    def on_login(self):
        log = self._log(self.log_prep)
        acc = self._cur_account()
        if not acc:
            log("库里没有这个账号")
            return
        pwd = self.ent_pwd.get().strip()
        if not pwd:
            log("密码是空的 —— 这个号以前没存密码，填上再登录")
            return
        self._do_login(acc, pwd, log, confirmed=False)

    def _do_login(self, acc, pwd, log, confirmed=False):
        from . import safe_login
        # 密码可能刚改过，先写回库，bridge 用的是库里的值
        try:
            import sqlite3
            con = sqlite3.connect(self.store.db)
            con.execute("update tsn_account set password=? where id=?", (pwd, acc["id"]))
            con.commit()
            con.close()
        except Exception as e:
            log("写密码失败：%s" % e)

        rows = self.store.q("select id, access_token, expires_in, username from tsn_account where id=?",
                            (acc["id"],))
        obj = type("A", (), {})()
        if rows:
            obj.id, obj.access_token, obj.expires_in, obj.username = rows[0]
        else:
            obj.id, obj.access_token, obj.expires_in, obj.username = acc["id"], "", 0, acc["username"]

        check = safe_login.precheck(self.dir, obj)
        if not check["ok"]:
            if check["code"] == "switch" and confirmed:
                safe_login.force_active(self.dir, obj)
                log("已按你的确认强制切换账号（风险自担）")
            else:
                log("⛔ " + check["message"])
                self._refresh_login_state("⛔ " + check["code"])
                if check["code"] == "switch":
                    self._ask_switch(acc, pwd, log, check)
                return
        if check["code"] == "reuse":
            log("✅ 本地登录态还有效 —— 会先强制退出再重新登录，确保只有一台设备在线")
            self._fire_login(acc, pwd, log)
            return
        self._wait_then_login(acc, pwd, log, safe_login.PHONE_SETTLE_S)

    def _ask_switch(self, acc, pwd, log, check):
        from tkinter import messagebox
        ok = messagebox.askyesno(
            "换号有封号风险",
            "%s\n\n确认要现在就切到 %s 吗？\n\n"
            "服务端会把短时间内先后登录两个账号判为代跑。\n"
            "继续 = 你接受这个风险。" % (check["message"], acc["username"]))
        if ok:
            self._do_login(acc, pwd, log, confirmed=True)
        else:
            log("已取消换号")

    def _wait_then_login(self, acc, pwd, log, seconds):
        """手机退出后先等一会儿再发登录请求，降低"第二台设备"判定概率。"""
        from tkinter import messagebox
        wait = int(max(0, seconds))
        if wait <= 0:
            self._fire_login(acc, pwd, log)
            return
        win = ctk.CTkToplevel(self)
        win.title("登录前置检查")
        win.geometry("480x260")
        win.configure(fg_color=P["bg"])
        win.transient(self)
        win.grab_set()
        self.lbl(win, "确认手机端已退出登录", size=16, bold=True).pack(pady=(20, 6))
        self.lbl(win, "手机会话在服务端可能还活着。现在立刻登录，会被当成第二台设备。\n"
                      "倒计时结束再登录最稳。", size=11, dim=True, justify="left").pack(padx=24)
        cd = self.lbl(win, "", size=28, bold=True, color=P["accent"])
        cd.pack(pady=10)

        state = {"left": wait, "done": False}

        def tick():
            if state["done"]:
                return
            if state["left"] <= 0:
                cd.configure(text="可以登录", text_color=P["ok"])
                btn.configure(state="normal", text="现在登录")
                return
            m, s = divmod(state["left"], 60)
            cd.configure(text="%02d:%02d" % (m, s))
            state["left"] -= 1
            win.after(1000, tick)

        def go():
            if state["done"]:
                return
            state["done"] = True
            win.destroy()
            self._fire_login(acc, pwd, log)

        def skip():
            if not messagebox.askyesno("确认跳过等待",
                                       "跳过等待会提高被判定为第二台设备的概率。\n\n确实已经退出手机端、"
                                       "并且离退出超过几分钟了吗？"):
                return
            log("⚠ 你跳过了等待，直接登录")
            go()

        btn = self.btn(win, "等待中…", cmd=go, primary=True, w=150, h=40)
        btn.configure(state="disabled")
        btn.pack(pady=12)
        self.btn(win, "跳过等待（不推荐）", cmd=skip, w=170, h=32).pack()
        tick()

    def _fire_login(self, acc, pwd, log):
        def job():
            import time as _t
            from . import bridge, safe_login
            aid = acc["id"]
            try:
                # 1) 登录前检查：服务器还认不认我们这个会话
                log("① 检查服务器会话…")
                st = bridge.session_state(aid, log=log)
                # 2) 有效就先踢掉，让手机端彻底下线，再重新登录
                if st.get("valid"):
                    log("② 检测到会话仍在，先强制退出（手机端会掉线）…")
                    kicked = bridge.force_logout(aid, log=log)
                    if kicked.get("kicked"):
                        log("   已作废旧会话，等 5 秒让服务端结算…")
                        _t.sleep(5)
                    else:
                        log("   强制退出未被确认，继续尝试登录")
                elif st.get("has_token"):
                    log("② 旧会话已失效（%s），无需踢人" % st.get("detail"))
                else:
                    log("② 本地没有凭据，无法预踢 —— 走保守流程")

                # 3) 重新登录
                log("③ 发起登录…")
                bridge.login(aid, log)
                safe_login.record(self.dir, type("A", (), {"id": aid, "username": acc["username"]}))
                log("✅ 登录完成，当前只有这一台设备在线")
                self.after(0, self._refresh_login_state, "登录完成")
            except Exception as e:
                log("登录失败：%s" % e)
                self.after(0, self._refresh_login_state, "登录失败")
        self.bg(job)

    # ---------------------------------------------------------------- 账号选择
    def active_account(self):
        """当前活跃账号：登录安全闸记的那个；没有就退回第一个。"""
        try:
            from . import safe_login
            st = safe_login.load(self.dir)
            act = st.get("active")
            for a in self.store.accounts:
                if str(a["id"]) == str(act):
                    return a
        except Exception:
            pass
        return self.store.accounts[0] if self.store.accounts else None

    def on_oneclick(self):
        """一键准备：学校 → 续期 → 路线 → 人脸 → 体检，缺什么补什么，已有的跳过。"""
        log = self._log(self.log_prep)
        acc = self.active_account()
        if not acc:
            log("没有账号，先在准备页登录")
            return
        if getattr(self, "prepping", False):
            log("一键准备已经在跑了")
            return
        self.prepping = True

        def job():
            from . import bridge, preflight
            ok_all = True
            try:
                log("========== 一键准备开始 ==========")

                # ① 学校
                n = self.store.schools
                if n < 100:
                    log("① 学校列表只有 %d 所，开始更新…" % n)
                    try:
                        bridge.update_schools(self.store.db, log)
                    except Exception as e:
                        log("   学校更新失败：%s" % e)
                        ok_all = False
                else:
                    log("① 学校列表 %d 所，跳过" % n)

                # ② 登录态（只用 refresh 续期，绝不触发新的设备登录）
                log("② 检查登录态…")
                st = bridge.refresh_session(acc["id"], log=log)
                if not st.get("ok"):
                    log("   续期没成功（%s）。为安全起见不自动重登 ——" % st.get("detail"))
                    log("   请手动点「登录 / 复用」（有冷却与倒计时保护），或用「粘贴 token」")
                    ok_all = False

                # ③ 路线
                if len(self.store.routes) == 0:
                    log("③ 本地没有路线，开始爬取…")
                    try:
                        bridge.crawl_paths(acc["id"], log)
                    except Exception as e:
                        log("   爬取失败：%s" % e)
                        ok_all = False
                else:
                    log("③ 已有 %d 条路线，跳过" % len(self.store.routes))

                # ④ 人脸
                faces = 0
                fdir = os.path.join(self.dir, "face_images")
                if os.path.isdir(fdir):
                    for _r, _d, fs in os.walk(fdir):
                        faces += len([f for f in fs if f.lower().endswith((".jpg", ".png"))])
                if faces == 0:
                    log("④ 本地没有人脸照片，开始拉取…")
                    try:
                        bridge.update_face(acc["id"], log)
                    except Exception as e:
                        log("   人脸更新失败：%s" % e)
                        ok_all = False
                else:
                    log("④ 已有 %d 张人脸，跳过" % faces)

                # ⑤ 体检
                log("⑤ 复查本地状态…")
                for name, good, detail, todo in preflight.local_checks(self.dir):
                    log("   %s %s：%s" % ("✅" if good else "❌", name, detail if good else todo))
                    if not good:
                        ok_all = False
                log("========== 一键准备结束：%s ==========" % ("全部就绪" if ok_all else "有项目没搞定，看上面"))
            finally:
                self.prepping = False
                self.after(0, lambda: self.show("prep"))
        self.bg(job)

    def _prep_checklist(self):
        """防呆清单：每项一眼看出缺什么、该点哪儿。"""
        try:
            from . import preflight
            rows = preflight.local_checks(self.dir)
        except Exception:
            return
        bar = self.card(self.body, width=self.X(916), height=self.X(124))
        bar.place(x=self.X(28), y=self.X(78))
        bar.pack_propagate(False)
        self.lbl(bar, "开跑前检查（缺什么点右边那句话去做）", size=11, bold=True).place(
            x=self.X(16), y=self.X(8))
        col = 0
        for i, (name, ok, detail, todo) in enumerate(rows):
            r, c = divmod(i, 2)
            x = 16 + c * 450
            y = 30 + r * 26
            self.lbl(bar, ("✅ " if ok else "❌ ") + name, size=10, bold=True,
                     color=P["ok"] if ok else P["bad"]).place(x=self.X(x), y=self.X(y))
            tail = todo if (not ok and todo != "正常") else detail
            self.lbl(bar, tail, size=9, dim=True).place(x=self.X(x + 74), y=self.X(y + 1))
        self.btn(bar, "一键准备", cmd=self.on_oneclick, primary=True, w=120, h=34).place(
            x=self.X(770), y=self.X(40))

    def on_diagnose(self):
        log = self._log(self.log_prep)
        acc = self.active_account()
        if not acc:
            log("没有账号")
            return
        def job():
            from . import bridge
            log("—— 登录链路体检（账号 %s）——" % acc["username"])
            try:
                bridge.diagnose(acc["id"], log=log)
            except Exception as e:
                log("体检失败：%s" % e)
        self.bg(job)

    def on_paste_token(self):
        from tkinter import simpledialog
        acc = self.active_account()
        if not acc:
            return
        tok = simpledialog.askstring("粘贴 token",
                                     "把浏览器里拿到的 access_token 粘进来：\n"
                                     "（F12 → Application → Local Storage → token / access_token）",
                                     parent=self)
        if not tok:
            return
        log = self._log(self.log_prep)
        def job():
            from . import bridge
            try:
                st = bridge.set_token(acc["id"], tok, log=log)
                log("校验结果：%s" % ("有效" if st.get("valid") else st.get("detail")))
            except Exception as e:
                log("导入失败：%s" % e)
        self.bg(job)

    def on_crawl(self):
        log = self._log(self.log_prep)
        acc = self.active_account()
        if not acc:
            log("没有账号")
            return
        def job():
            from . import bridge
            log("开始爬取路径（账号 %s）…" % acc["username"])
            try:
                bridge.crawl_paths(acc["id"], log)
                log("爬取完成")
            except Exception as e:
                log("爬取失败：%s" % e)
        self.bg(job)

    def on_face(self):
        log = self._log(self.log_prep)
        acc = self.active_account()
        if not acc:
            log("没有账号")
            return
        def job():
            from . import bridge
            log("开始更新人脸（账号 %s）…" % acc["username"])
            try:
                bridge.update_face(acc["id"], log)
            except Exception as e:
                log("更新失败：%s" % e)
        self.bg(job)

    def on_run(self):
        log = self._log(self.log_run)
        if getattr(self, "running", False):
            log("已经在跑了，等它结束")
            return
        if not self.store.routes:
            self.set_status("无路线", P["warn"])
            log("⚠ 本地没有跑步路线，先去「准备」页点『爬取路径』")
            return
        name = self.seg.get()
        key = next(k for k, cn, _ in MODES if cn == name)
        try:
            km = float(self.ent_km.get().strip() or 2.0)
            minutes = float(self.ent_min.get().strip() or 0) or None
            cadence = float(self.ent_cad.get().strip() or 0) or None
        except ValueError:
            self.set_status("参数错误", P["bad"])
            log("参数填得不对（距离/时间/步频要写数字）")
            return

        self.running = True
        self.run_start = time.monotonic()
        self.set_status("启动中…", P["warn"])
        try:
            self.status_time.configure(text="00:00")
            self.status_bar.start()
        except Exception:
            pass
        self._tick()
        log("准备开跑：%.2f km / %s" % (km, name))

        def job():
            from . import bridge
            try:
                bridge.run(self.active_account()["id"], km, key, minutes, cadence,
                           log=lambda m: log(m),
                           on_progress=lambda m: self.after(0, self._on_progress, m))
                self.after(0, self._finish, True, "")
            except Exception as e:
                try:
                    from . import preflight
                    why = preflight.explain_error(e)
                    msg = "跑步失败：%s\n原因：%s\n怎么办：%s" % (e, why["what"], why["todo"])
                except Exception:
                    msg = "跑步失败：%s" % e
                self.after(0, self._finish, False, msg)
        self.bg(job)

    def on_query(self):
        user = self.opt_acc.get()
        acc = next((a for a in self.store.accounts if a["username"] == user), None)
        if not acc:
            self.q_state.configure(text="没找到这个账号", text_color=P["bad"])
            return
        self.q_state.configure(text="查询中…", text_color=P["warn"])
        for w in self.tiles.winfo_children():
            w.destroy()

        def job():
            from . import bridge
            try:
                st = bridge.query_stats(acc["id"], log=lambda m: None)
                self.after(0, self._show_stats, acc, st)
            except Exception as e:
                msg = str(e)
                self.after(0, self._query_failed, msg)
        self.bg(job)

    def _query_failed(self, msg):
        self.q_state.configure(text="失败", text_color=P["bad"])
        hint = ""
        if "Wrong password" in msg or "重新登录" in msg:
            hint = ("\n\n这个账号的密码在本地库里对不上了。去「准备」页用学号+密码"
                    "重新授权一次，再回来查询。")
        self.q_result.configure(text="查询失败：" + msg + hint, text_color=P["bad"])

    def _show_stats(self, acc, st):
        self.q_state.configure(text="查询完成", text_color=P["ok"])
        tiles = [("晨跑", st.get("morning_run_count")),
                 ("阳光跑", st.get("sun_run_count")),
                 ("自由跑", st.get("freedom_run_count"))]
        for i, (name, val) in enumerate(tiles):
            c = self.card(self.tiles, width=self.X(296), height=self.X(120))
            c.place(x=self.X(i * 312), y=0)
            c.pack_propagate(False)
            self.lbl(c, name, size=11, dim=True).place(x=self.X(18), y=self.X(14))
            self.lbl(c, str(val if val is not None else "—"), size=26, bold=True).place(
                x=self.X(18), y=self.X(40))
            self.lbl(c, "有效次数", size=10, dim=True).place(x=self.X(18), y=self.X(86))

        lines = [("账号", acc["username"]),
                 ("总有效次数", st.get("total_valid_count")),
                 ("总里程", "%.2f km" % float(st.get("total_distance_km") or 0)),
                 ("总跑步次数", st.get("total_run_count"))]
        if st.get("valid_records_count") is not None:
            lines.append(("有记录条数", "%s / %s" % (st.get("valid_records_count"),
                                                st.get("total_records_count"))))
        text = "\n\n".join("%s：%s" % (k, v) for k, v in lines if v is not None)
        self.q_result.configure(text=text, text_color=P["text"])


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
