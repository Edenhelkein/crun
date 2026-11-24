"""引擎：平台约束 preflight -> 风控账本 -> 路线多样化 -> 轨迹/传感器合成 -> 自审 -> 落盘。"""
import json
import os
import random

from .antidetect import audit, evasion_plan
from .blacklist import RiskLedger
from .planner import Planner
from .policy import PolicyEngine
from .routegen import RouteLibrary, generate_diverse
from .sensors import build_steps
from .traj import simulate_run


def _ctx(cfg):
    return {"device": cfg.get("device_fp"), "account": cfg.get("account_id"), "ip": cfg.get("egress_ip")}


def _mode_of(pace):
    return "walk" if pace > 470 else "run"


def run_session(cfg, out_dir="out", register=True):
    os.makedirs(out_dir, exist_ok=True)
    work = cfg.get("work_dir", out_dir)
    ledger = RiskLedger(os.path.join(work, "ledger.json"))
    pol = PolicyEngine(os.path.join(work, "policy.json"))
    lib = RouteLibrary(os.path.join(work, "routes.json"))
    planner = Planner(os.path.join(work, "state.json"), min_gap_days=cfg.get("min_gap_days", 10))
    ctx = _ctx(cfg)

    pre = pol.preflight(cfg.get("account_id") or "ANON",
                        cfg.get("device_fp") or "NODEV", cfg.get("mode", "campus_run"))
    if not pre["allowed"]:
        pol.save()
        return {"verdict": "ABORT", "reasons": pre["reasons"],
                "action": "硬约束越界：不生成轨迹。换设备/非白名单模式/重试密码都会被直接判定，只能人工处理",
                "policy": pre}

    verdict, reasons = ledger.decide(ctx, cfg.get("route_hash"))
    if verdict == "ABORT":
        return {"verdict": "ABORT", "reasons": reasons,
                "action": "未生成轨迹：先换设备指纹/账号/出口 IP，冷却期内不要补跑",
                "policy": pre}

    seed = cfg.get("seed")
    if seed is None:
        seed = random.randrange(1 << 30)
    rng = random.Random(seed)

    if cfg.get("origin") and cfg.get("start_ts"):
        plan = {"origin": cfg["origin"], "start_ts": cfg["start_ts"],
                "distance_m": cfg.get("distance_m", 2500.0),
                "pace_s_per_km": cfg.get("pace_s_per_km", 360.0), "geohash6": ""}
    else:
        plan = planner.plan(rng, cfg.get("origin"), cfg.get("distance_m", 2500.0), cfg.get("start_ts"))
    if cfg.get("pace_s_per_km"):
        plan["pace_s_per_km"] = cfg["pace_s_per_km"]

    route_pts, meta = generate_diverse(
        rng, tuple(plan["origin"]), plan["distance_m"], lib,
        tries=cfg.get("tries", 20), max_overlap=cfg.get("max_overlap", 0.55))

    pace = plan["pace_s_per_km"]
    session = simulate_run(rng, tuple(plan["origin"]), plan["distance_m"], pace,
                           start_epoch=plan["start_ts"],
                           noise_sigma=cfg.get("noise_sigma", 3.0),
                           canyon_p=cfg.get("canyon_p", 0.12),
                           route=route_pts, mode=_mode_of(pace))
    steps = build_steps(session["points"], rng, ref_distance=session["distance_m"])
    rep = audit(session, steps, ledger, ctx, planner.runs, cfg.get("min_gap_days", 10),
                route_meta=meta, policy=pre)
    actions = evasion_plan(rep)

    if rep["verdict"] != "ABORT" and rep["verdict"] == "THROTTLE":
        # 降级重算：换起点 + 慢 5% + 推迟 30 分钟
        plan2 = dict(plan)
        plan2["start_ts"] = plan["start_ts"] + 1800
        plan2["pace_s_per_km"] = pace * 1.05
        plan2["origin"] = [plan["origin"][0] + 0.004, plan["origin"][1] + 0.004]
        route_pts, meta = generate_diverse(rng, tuple(plan2["origin"]), plan["distance_m"], lib,
                                           tries=cfg.get("tries", 20),
                                           max_overlap=max(0.35, cfg.get("max_overlap", 0.55) - 0.1))
        session = simulate_run(rng, tuple(plan2["origin"]), plan["distance_m"], plan2["pace_s_per_km"],
                               start_epoch=plan2["start_ts"],
                               noise_sigma=cfg.get("noise_sigma", 3.0), canyon_p=0.08,
                               route=route_pts, mode=_mode_of(plan2["pace_s_per_km"]))
        steps = build_steps(session["points"], rng, ref_distance=session["distance_m"])
        rep = audit(session, steps, ledger, ctx, planner.runs, cfg.get("min_gap_days", 10),
                    route_meta=meta, policy=pre)
        actions = evasion_plan(rep)
        plan = plan2

    report = {"verdict": rep["verdict"], "reasons": [], "policy": pre,
              "route": meta, "session": session, "steps": steps, "audit": rep,
              "actions": actions, "plan": plan, "seed": seed}
    if rep["verdict"] == "ABORT":
        report["action"] = "自审未过：按 actions 调参后重跑，不要直接提交"
        return report

    if register:
        planner.register({"geohash6": session["geohash6"], "route_hash": session["route_hash"],
                          "start_ts": session["points"][0]["t"], "distance_m": session["distance_m"]})
        lib.add([(p["lat"], p["lon"]) for p in session["points"]], session["points"][0]["t"],
                session["distance_m"])
        lib.save()
        pol.save()

    with open(os.path.join(out_dir, "session.json"), "w", encoding="utf-8") as f:
        json.dump({"session": session, "steps": steps, "audit": rep, "actions": actions,
                   "plan": plan, "route": meta}, f, ensure_ascii=False, indent=2)
    return report
