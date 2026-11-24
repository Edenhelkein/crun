"""自测：会话链路 + 路线多样化 + 平台约束 + 更新模块。"""
import json
import os
import random
import shutil
import sys
import zipfile

from crun.antidetect import audit, evasion_plan, CHECKS
from crun.blacklist import RiskLedger, fingerprint
from crun.engine import run_session
from crun.policy import PolicyEngine
from crun.routegen import cells_of, generate_diverse, overlap, RouteLibrary
from crun.sensors import build_steps
from crun.traj import simulate_run
from crun.updater import apply as update_apply, check as update_check

ROOT = os.path.dirname(os.path.abspath(__file__))
TMP = os.path.join(ROOT, ".selftest-tmp")
OK, BAD = [], []


def check(name, cond, info=""):
    (OK if cond else BAD).append(name)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))


def t_session():
    rng = random.Random(20261125)
    s = simulate_run(rng, (30.2741, 120.1551), 2400.0, 355.0, start_epoch=1765000000.0)
    st = build_steps(s["points"], rng, ref_distance=s["distance_m"])
    rep = audit(s, st)
    check("会话自审 RUN", rep["verdict"] == "RUN", f"score={rep['score']}")
    check("步数-里程比 1.00±0.05", abs(st["step_gps_ratio"] - 1.0) < 0.05, st["step_gps_ratio"])
    check("最大 5s 均速 <7.5", max(p["speed5"] for p in s["points"]) < 7.5)
    check("检测矩阵 16 项", len(CHECKS) == 16, len(CHECKS))

    # 散步模式：步频应落在 walk 区间
    s2 = simulate_run(random.Random(5), (30.2741, 120.1551), 1500.0, 540.0,
                      start_epoch=1765000000.0, mode="walk")
    st2 = build_steps(s2["points"], ref_distance=s2["distance_m"])
    rep2 = audit(s2, st2)
    check("散步模式步频 100-145", 100 <= st2["avg_cadence_spm"] <= 145, st2["avg_cadence_spm"])
    check("散步模式自审通过", rep2["verdict"] == "RUN", rep2["failed"])


def t_routes():
    rng = random.Random(11)
    lib = RouteLibrary(os.path.join(TMP, "routes_t.json"))
    fps, starts, overlaps = set(), set(), []
    for i in range(6):
        pts, meta = generate_diverse(rng, (30.2741, 120.1551), 2200.0, lib, tries=12)
        fps.add(meta["fp"])
        starts.add(pts[0])
        ov, _ = lib.max_overlap(pts=pts)
        overlaps.append(round(ov, 2))
        lib.add(pts, ts=1765000000.0 + i * 86400)
    check("6 条路线指纹互不相同", len(fps) == 6, len(fps))
    check("与历史最大重叠 <0.9", max(overlaps) < 0.9, max(overlaps))
    turns = []
    for k in range(10):
        _, meta = generate_diverse(random.Random(100 + k), (30.2741, 120.1551), 2200.0, tries=10)
        turns.append(meta["max_turn_deg"])
    check("单次转角 <=30°", max(turns) <= 30.0, f"max={max(turns):.1f}")
    a = generate_diverse(random.Random(3), (30.40, 120.30), 1800.0)[0]
    check("跨起点不重叠", overlap(cells_of(a), cells_of(generate_diverse(
        random.Random(4), (30.30, 120.10), 1800.0)[0])) == 0.0)


def t_policy():
    pol = PolicyEngine(os.path.join(TMP, "policy.json"))
    ok, _ = pol.bind_device("STU_1", "DEV_A")
    check("首台设备绑定成功", ok)
    ok2, msg2 = pol.bind_device("STU_1", "DEV_B")
    check("第二台设备被拒", not ok2, msg2)
    check("非白名单模式被拒", not pol.check_mode("night_ride")[0])
    for _ in range(4):
        pol.login("STU_2", "DEV_C", success=False)
    r5 = pol.login("STU_2", "DEV_C", success=False)
    check("第 5 次失败触发锁定", "锁定" in r5["reason"], r5["reason"])
    r6 = pol.login("STU_2", "DEV_C", success=True)
    check("锁定期间登录被拒", not r6["ok"], r6["reason"])
    pre = pol.preflight("STU_1", "DEV_B", "night_ride")
    check("preflight 汇总两条违规", len(pre["reasons"]) == 2 and not pre["allowed"], pre["reasons"])


def t_engine():
    work = os.path.join(TMP, "eng")
    os.makedirs(work, exist_ok=True)
    rep = run_session({"device_fp": "DEV_ENG", "account_id": "ACC_ENG", "egress_ip": "203.0.113.77",
                       "seed": 21, "distance_m": 2200.0, "pace_s_per_km": 370.0,
                       "work_dir": work, "origin": [30.2741, 120.1551], "start_ts": 1765100000.0},
                      out_dir=os.path.join(work, "out"))
    check("engine 出车 RUN", rep["verdict"] == "RUN", rep["verdict"])
    check("engine 落盘 session.json", os.path.exists(os.path.join(work, "out", "session.json")))
    check("engine 记录路线库", os.path.exists(os.path.join(work, "routes.json")))
    rep2 = run_session({"device_fp": "DEV_ENG", "account_id": "ACC_ENG", "mode": "night_ride",
                        "seed": 22, "work_dir": work}, out_dir=os.path.join(work, "out2"))
    check("非白名单模式被引擎拦截", rep2["verdict"] == "ABORT" and "policy" in rep2, rep2["reasons"])


def t_updater():
    src = os.path.join(TMP, "pkg")
    os.makedirs(os.path.join(src, "crun"), exist_ok=True)
    with open(os.path.join(src, "crun", "__init__.py"), "w", encoding="utf-8") as f:
        f.write('__version__ = "9.9.9"\n')
    zp = os.path.join(TMP, "crun-9.9.9.zip")
    with zipfile.ZipFile(zp, "w") as z:
        z.write(os.path.join(src, "crun", "__init__.py"), "crun/__init__.py")
    import hashlib
    sha = hashlib.sha256(open(zp, "rb").read()).hexdigest()
    man = {"version": "9.9.9", "url": zp, "sha256": sha, "notes": ["test"]}
    mp = os.path.join(TMP, "manifest.json")
    with open(mp, "w", encoding="utf-8") as f:
        json.dump(man, f)

    info = update_check(mp)
    check("清单检查发现新版本", info["ok"] and info["update_available"], info.get("latest"))

    inst = os.path.join(TMP, "install")
    os.makedirs(os.path.join(inst, "crun"), exist_ok=True)
    with open(os.path.join(inst, "crun", "__init__.py"), "w", encoding="utf-8") as f:
        f.write('__version__ = "1.2.0"\n')

    dry = update_apply(info, inst, dry_run=True)
    check("dry-run 不落盘", dry["ok"] and dry["stage"] == "dry-run")

    bad = dict(info); bad["sha256"] = "0" * 64
    r_bad = update_apply(bad, inst)
    check("sha256 不符被拒", not r_bad["ok"] and r_bad["stage"] == "verify", r_bad.get("stage"))

    r_ok = update_apply(info, inst)
    check("更新替换成功", r_ok["ok"], r_ok.get("stage"))
    with open(os.path.join(inst, "crun", "__init__.py"), encoding="utf-8") as f:
        check("版本号已切换", '9.9.9' in f.read())

    man2 = dict(man); man2["version"] = "9.9.8"
    info2 = update_check({"version": "9.9.8", "url": zp, "sha256": sha})
    check("降级被拒", update_apply(info2, inst)["stage"] == "validate")


def main():
    shutil.rmtree(TMP, ignore_errors=True)
    os.makedirs(TMP, exist_ok=True)
    try:
        t_session()
        t_routes()
        t_policy()
        t_engine()
        t_updater()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
    print(f"\n{len(OK)} passed, {len(BAD)} failed")
    return 0 if not BAD else 1


if __name__ == "__main__":
    sys.exit(main())
