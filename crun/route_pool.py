"""路径池：让原版不要老是抽到最近跑过的那条路线。

原版 queryPath 的选路逻辑是：按距离筛选 → random.choice 随机抽一条。
我们在旁边记一本"每条路线上次用是什么时候"，把选中的目标从"纯随机"
换成"优先用最久没用的那条，偶尔在前三名里随机"，避免连续两天同一条线。
"""
import os
import random
import sqlite3
import time

DB = "tsn_data.db"


def _conn():
    return sqlite3.connect(os.path.join(os.getcwd(), DB), timeout=5)


def ensure():
    try:
        with _conn() as c:
            c.execute("create table if not exists crun_pool_usage("
                      "run_path_id text primary key, last_used real, uses integer default 0)")
    except sqlite3.Error:
        pass


def _id(obj):
    for a in ("run_path_id", "id"):
        v = getattr(obj, a, None)
        if v is not None:
            return str(v)
    return None


def _usage():
    out = {}
    try:
        with _conn() as c:
            for rid, lu, us in c.execute("select run_path_id, last_used, uses from crun_pool_usage"):
                out[str(rid)] = (lu or 0.0, us or 0)
    except sqlite3.Error:
        pass
    return out


def _mark(rid):
    if not rid:
        return
    try:
        with _conn() as c:
            c.execute("insert into crun_pool_usage(run_path_id,last_used,uses) values(?,?,1) "
                      "on conflict(run_path_id) do update set last_used=excluded.last_used, uses=uses+1",
                      (rid, time.time()))
    except sqlite3.Error:
        pass


def choose(candidates):
    """在候选路线里挑一条最久没用的；失败就返回 None 交给原版随机。"""
    if not candidates:
        return None
    ensure()
    usage = _usage()
    scored = sorted(candidates, key=lambda o: usage.get(_id(o), (0.0, 0))[0])
    top = scored[:3] if len(scored) > 1 and random.random() < 0.25 else scored[:1]
    pick = random.choice(top)
    _mark(_id(pick))
    return pick


def stats():
    ensure()
    try:
        with _conn() as c:
            rows = c.execute("select run_path_id, uses, last_used from crun_pool_usage "
                             "order by last_used desc").fetchall()
    except sqlite3.Error:
        return []
    return [{"route": r[0], "uses": r[1], "last_used": time.strftime("%m-%d %H:%M", time.localtime(r[2] or 0))}
            for r in rows]
