"""开跑前的防呆检查：把所有会让人卡住的前提条件一次性摊开。

每一项都返回 (名称, 状态, 一句话说明, 怎么办)。界面直接照着画，
用户不用猜"为什么点了没反应"。
"""
import os
import sqlite3


def _q(db, sql, args=()):
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        rows = con.execute(sql, args).fetchall()
        con.close()
        return rows
    except sqlite3.Error:
        return []


def local_checks(data_dir):
    """纯本地检查，不发网络请求。"""
    db = os.path.join(data_dir, "tsn_data.db")
    out = []

    schools = _q(db, "select count(*) from tsn_school")
    n_school = schools[0][0] if schools else 0
    out.append(("学校列表", n_school > 0, "%d 所" % n_school,
                "点「更新学校列表」" if n_school == 0 else "正常"))

    accs = _q(db, "select count(*) from tsn_account")
    n_acc = accs[0][0] if accs else 0
    out.append(("账号", n_acc > 0, "%d 个" % n_acc,
                "先在准备页输入学号密码登录" if n_acc == 0 else "正常"))

    tok = _q(db, "select access_token, refresh_token, username from tsn_account limit 1")
    has_tok = bool(tok and (tok[0][0] or tok[0][1]))
    out.append(("登录凭据", has_tok, "有 token" if has_tok else "没有 token",
                "点「登录 / 复用」，或从浏览器粘贴 token"))

    routes = _q(db, "select count(*) from tsn_run_path")
    n_route = routes[0][0] if routes else 0
    out.append(("跑步路线", n_route > 0, "%d 条" % n_route,
                "点「爬取路径」" if n_route == 0 else "正常"))

    faces = _q(db, "select count(*) from tsn_account")
    face_dir = os.path.join(data_dir, "face_images")
    n_face = 0
    if os.path.isdir(face_dir):
        for _root, _d, files in os.walk(face_dir):
            n_face += len([f for f in files if f.lower().endswith((".jpg", ".png"))])
    out.append(("人脸照片", n_face > 0, "%d 张" % n_face,
                "点「更新人脸」" if n_face == 0 else "正常（跑步中途验证要用）"))

    dev = os.path.join(data_dir, "device_profiles.json")
    ok_dev = os.path.exists(dev)
    out.append(("设备指纹", ok_dev, "已生成" if ok_dev else "缺失",
                "正常" if ok_dev else "重启程序会自动生成"))

    return out


def explain_error(text):
    """把服务器/网络的原始报错翻译成"发生了什么 + 你该做什么"。"""
    t = str(text or "")
    low = t.lower()
    table = [
        ("999", "账号被系统判定违规，已进入禁跑黑名单（不是网络问题）",
         "在手机 App 里看「我的-违规记录」，到期才能跑；期间爬路径/人脸仍可用"),
        ("黑名单", "账号被系统判定违规，已进入禁跑黑名单",
         "等解封日期；不要重复尝试跑步，重复请求会加重风控"),
        ("403", "服务器拒绝访问：登录态失效或没有权限",
         "点「登录 / 复用」续期，或从浏览器粘贴新 token"),
        ("401", "登录态无效（token 过期或被踢）",
         "重新登录；如果登录接口报 404，用「粘贴 token」"),
        ("404", "接口地址不存在 —— 学校后端升级了，登录接口已搬迁",
         "这版无法密码登录，请用「粘贴 token」；并向作者反馈接口 404"),
        ("405", "请求地址拼错（学校域名带参数导致路径错乱）",
         "点「登录体检」看具体哪一环；不要反复重试"),
        ("wrong password", "密码不对",
         "在准备页重新输入密码；连续错多次会触发风控，别试太多次"),
        ("没有可用的跑步路线", "本地一条路线都没有",
         "准备页点「爬取路径」"),
        ("未开通", "学校没开放这个跑步类型",
         "换一个类型（常见可用：阳光跑）"),
        ("timeout", "网络超时", "换网络/稍后再试；不要连点"),
        ("refused", "连不上服务器", "检查网络或学校是否限制访问"),
    ]
    for key, what, todo in table:
        if key in low or key in t:
            return {"what": what, "todo": todo}
    return {"what": "未知错误", "todo": "把这段日志发给作者（准备页底部日志区可复制）"}


def banned_from(text):
    """从报错里抽解封日期，用于界面红条。"""
    import re
    t = str(text or "")
    m = re.search(r"(20\d{2}-\d{2}-\d{2})", t)
    return m.group(1) if m else ""
