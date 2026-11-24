"""反作弊矩阵：把平台侧校验项逐条落地成可判定 + 可对抗的条目。

audit() 对一次 session 打分（0-100），evasion_plan() 把失败项映射成动作。
"""
import math
import statistics

CHECKS = [
    {"id": "speed_outlier", "w": 12, "name": "瞬时速度超人类",
     "obs": "5s 窗口均速 > 7.5 m/s", "counter": "配速模型封顶 7.2 m/s + 5s 窗口平滑"},
    {"id": "teleport", "w": 12, "name": "定位跳变",
     "obs": "单秒位移 > 60 m", "counter": "AR(1) 误差 + 漂移上限约束"},
    {"id": "accuracy_bad", "w": 6, "name": "精度长期劣化",
     "obs": "accuracy > 30 m 的采样占比 > 15%", "counter": "城市峡谷窗口占比 <= 15%"},
    {"id": "step_ratio", "w": 16, "name": "步数-里程不匹配",
     "obs": "|步数*步幅 / GPS里程 - 1| > 0.18", "counter": "步幅由速度反推，比率锁在 1.00±0.05"},
    {"id": "cadence", "w": 8, "name": "步频不合理",
     "obs": "跑: 140-200 spm / 走: 100-145 spm", "counter": "步幅分段经验式，步频=v*60/stride"},
    {"id": "pace_window", "w": 8, "name": "配速越界",
     "obs": "配速不在 4:00-10:00 /km", "counter": "plan 阶段约束 pacing"},
    {"id": "too_smooth", "w": 7, "name": "过于连续（无停顿）",
     "obs": "速度<0.4 m/s 的时间占比 < 0.1%", "counter": "1-3 次 15-50 s 停顿"},
    {"id": "noise_flat", "w": 6, "name": "定位噪声过小",
     "obs": "经纬度二阶差分方差 < 1e-14", "counter": "AR(1) 噪声 sigma>=3 m"},
    {"id": "sat_low", "w": 5, "name": "卫星数偏低",
     "obs": "平均 satellites < 9", "counter": "常规窗口 11-21"},
    {"id": "alt_flat", "w": 4, "name": "海拔近似常数",
     "obs": "海拔标准差 < 0.3 m", "counter": "地形起伏 + 0.6 m 噪声"},
    {"id": "route_reuse", "w": 18, "name": "轨迹指纹复用",
     "obs": "同 geohash6 路线在 10 天内重复", "counter": "路线库轮换 + 起点抖动"},
    {"id": "route_overlap", "w": 14, "name": "与历史路线覆盖率过高",
     "obs": "与历史路线的 geohash7 相邻格覆盖率 > 0.55", "counter": "多候选按相邻格重叠度仲裁"},
    {"id": "turn_angle", "w": 6, "name": "转角过大（直角/折返）",
     "obs": "路线最大转角 > 35°", "counter": "wander 单次转向上限 30°"},
    {"id": "policy", "w": 40, "name": "平台硬约束越界",
     "obs": "双设备/非白名单模式/密码重试", "counter": "policy.preflight 前置拦截"},
    {"id": "clock_regular", "w": 10, "name": "开跑时刻过于规律",
     "obs": "与历史开跑同 15 分钟桶", "counter": "开跑时间抖动 >= 25 分钟"},
    {"id": "ledger", "w": 30, "name": "本地黑名单命中",
     "obs": "device/account/ip 处于 flagged/banned", "counter": "decide() 直接 ABORT/THROTTLE"},
]
TOTAL_W = sum(c["w"] for c in CHECKS)


def _fail(i, w, name, detail, counter):
    return {"id": i, "w": w, "name": name, "fail": True, "detail": detail, "counter": counter}


def audit(session, steps, ledger=None, ctx=None, history=None, min_gap_days=10,
          route_meta=None, policy=None):
    pts = session["points"]
    hist = history or []
    res = []
    speeds = [p.get("speed5", p["speed"]) for p in pts]
    vmax = max(speeds) if speeds else 0.0
    res.append({"id": "speed_outlier", "w": 12, "name": "瞬时速度超人类", "fail": vmax > 7.5,
                "detail": f"max_5s={vmax:.2f} m/s", "counter": "配速模型封顶 7.2 m/s"})

    jump = 0.0
    for i in range(1, len(pts)):
        a, b = pts[i - 1], pts[i]
        dt = max(1e-6, b["t"] - a["t"])
        d = math.hypot((b["lat"] - a["lat"]) * 111320.0,
                       (b["lon"] - a["lon"]) * 111320.0 * math.cos(math.radians(a["lat"])))
        jump = max(jump, d / dt if dt < 1.2 else d)
    res.append({"id": "teleport", "w": 12, "name": "定位跳变", "fail": jump > 60.0,
                "detail": f"max_step={jump:.1f} m", "counter": "AR(1) + 上限约束"})

    bad = sum(1 for p in pts if p["accuracy"] > 30.0) / max(1, len(pts))
    res.append({"id": "accuracy_bad", "w": 6, "name": "精度长期劣化", "fail": bad > 0.15,
                "detail": f"ratio={bad:.3f}", "counter": "峡谷窗口 <=15%"})

    ratio = steps["step_gps_ratio"]
    res.append({"id": "step_ratio", "w": 16, "name": "步数-里程不匹配", "fail": abs(ratio - 1.0) > 0.18,
                "detail": f"ratio={ratio:.3f}", "counter": "步幅由速度反推"})

    cad = steps["avg_cadence_spm"]
    pace = session["pace_s_per_km"]
    walk_mode = pace > 470  # 8 分/km 以上按步行节奏判
    cad_ok = (100 <= cad <= 145) if walk_mode else (140 <= cad <= 200)
    res.append({"id": "cadence", "w": 8, "name": "步频不合理", "fail": not cad_ok,
                "detail": f"cadence={cad} ({'walk' if walk_mode else 'run'})",
                "counter": "cadence=v*60/stride"})

    res.append({"id": "pace_window", "w": 8, "name": "配速越界", "fail": not (240 <= pace <= 600),
                "detail": f"pace={pace:.1f}s/km", "counter": "plan 阶段约束"})

    stop = sum(1 for s in speeds if s < 0.4) / max(1, len(speeds))
    res.append({"id": "too_smooth", "w": 7, "name": "过于连续（无停顿）", "fail": stop < 0.001,
                "detail": f"stop_ratio={stop:.4f}", "counter": "1-3 次 12-55s 停顿"})

    d2 = []
    for i in range(2, len(pts)):
        d2.append(abs(pts[i]["lat"] - 2 * pts[i - 1]["lat"] + pts[i - 2]["lat"]))
    var = statistics.pvariance(d2) if len(d2) > 2 else 0.0
    res.append({"id": "noise_flat", "w": 6, "name": "定位噪声过小", "fail": var < 1e-14,
                "detail": f"var={var:.3e}", "counter": "sigma>=3m"})

    sat = statistics.mean(p["satellites"] for p in pts)
    res.append({"id": "sat_low", "w": 5, "name": "卫星数偏低", "fail": sat < 9,
                "detail": f"mean_sat={sat:.1f}", "counter": "11-21"})

    alt_sd = statistics.pstdev(p["alt"] for p in pts)
    res.append({"id": "alt_flat", "w": 4, "name": "海拔近似常数", "fail": alt_sd < 0.3,
                "detail": f"alt_sd={alt_sd:.2f}", "counter": "地形+噪声"})

    reused = [h for h in hist if h.get("geohash6") == session["geohash6"]
              and abs(h.get("start_ts", 0) - session["points"][0]["t"]) < min_gap_days * 86400]
    res.append({"id": "route_reuse", "w": 18, "name": "轨迹指纹复用", "fail": bool(reused),
                "detail": f"{len(reused)} 次同格路线", "counter": "路线库轮换"})

    ov = (route_meta or {}).get("overlap", 0.0)
    res.append({"id": "route_overlap", "w": 14, "name": "与历史路线覆盖率过高", "fail": ov > 0.55,
                "detail": f"overlap={ov:.3f}", "counter": "多候选择优"})

    turn = (route_meta or {}).get("max_turn_deg")
    res.append({"id": "turn_angle", "w": 6, "name": "转角过大（直角/折返）",
                "fail": bool(turn is not None and turn > 35.0),
                "detail": (f"max_turn={turn}°" if turn is not None else "n/a"),
                "counter": "wander 单次转向 <=30°"})

    start = session["points"][0]["t"]
    bucket = int((start % 86400) // 900)
    same = [h for h in hist if int((h.get("start_ts", 0) % 86400) // 900) == bucket]
    res.append({"id": "clock_regular", "w": 10, "name": "开跑时刻过于规律", "fail": len(same) >= 2,
                "detail": f"{len(same)} 次同 15min 桶", "counter": "抖动 >=25min"})

    lf = []
    if ledger is not None and ctx:
        for k in ("device", "account", "ip"):
            if ctx.get(k) and ledger.status(k, ctx[k]) in ("flagged", "banned"):
                lf.append(f"{k}={ledger.status(k, ctx[k])}")
    res.append({"id": "ledger", "w": 30, "name": "本地黑名单命中", "fail": bool(lf),
                "detail": ",".join(lf) or "clear", "counter": "ABORT/THROTTLE"})

    pf = [] if (policy is None or policy.get("allowed", True)) else list(policy.get("reasons", []))
    res.append({"id": "policy", "w": 40, "name": "平台硬约束越界", "fail": bool(pf),
                "detail": "; ".join(pf) or "ok", "counter": "policy.preflight 前置拦截"})

    score = 100.0 * sum(r["w"] for r in res if r["fail"]) / TOTAL_W
    fails = [r for r in res if r["fail"]]
    if any(r["id"] == "policy" for r in fails):
        verdict = "ABORT"          # 硬约束越界没有协商空间
    elif any(r["id"] == "ledger" for r in fails) and score >= 30:
        verdict = "ABORT"
    elif score < 22:
        verdict = "RUN"
    elif score < 45:
        verdict = "THROTTLE"
    else:
        verdict = "ABORT"
    # 轨迹复用/时段规律是关联分析里权重最高的一类，单项命中就不该按 RUN 走
    if verdict == "RUN" and ({"route_reuse", "clock_regular"} & {r["id"] for r in fails}):
        verdict = "THROTTLE"
    return {"checks": res, "score": round(score, 1), "verdict": verdict,
            "failed": [r["id"] for r in fails]}


def evasion_plan(report):
    actions = []
    for r in report["checks"]:
        if not r["fail"]:
            continue
        if r["id"] == "route_reuse":
            actions.append("换 geohash6 相邻 2km 外的新起点；route_lib 轮换脚本加 --exclude-recent 10")
        elif r["id"] == "route_overlap":
            actions.append("提高候选数 --tries 40、降低 max_overlap 到 0.45；或换片区起点")
        elif r["id"] == "turn_angle":
            actions.append("降低 max_turn_deg（默认 30°）或加大 seg_m 下限，避免折返式路线")
        elif r["id"] == "policy":
            actions.append("硬约束越界：不要换设备、不要请求非白名单模式、不要重试密码——只能换账号或走人工")
        elif r["id"] == "clock_regular":
            actions.append("开跑时间抖动 ±25-70 min；避免与历史同时段（同类 App 的规律性权重很高）")
        elif r["id"] == "ledger":
            actions.append("命中黑名单：ABORT。更换设备指纹/账号/出口 IP 后再协商，禁止补跑")
        elif r["id"] in ("step_ratio", "cadence"):
            actions.append("重算步幅表：stride=0.72+0.062*(kmh-4)，比率回到 1.00±0.05")
        elif r["id"] == "too_smooth":
            actions.append("注入 1-3 次 12-55s 停顿（等红灯语义），stop_ratio 目标 1-6%")
        elif r["id"] == "speed_outlier":
            actions.append("速度上限降到 7.2 m/s，并对 >6.6 m/s 的点做 3 点中值")
        elif r["id"] == "accuracy_bad":
            actions.append("峡谷窗口概率 canyon_p 降到 0.08；accuracy 上限 30 m")
        elif r["id"] == "teleport":
            actions.append("关闭 canyon 放大期间的跳变，误差 sigma 上限 12 m")
        elif r["id"] == "noise_flat":
            actions.append("AR(1) 系数 k=0.85、sigma>=3 m 必须开启")
        elif r["id"] == "sat_low":
            actions.append("satellites 采样区间抬到 11-21")
        elif r["id"] == "alt_flat":
            actions.append("海拔叠加 2 m 正弦 + 0.6 m 高斯噪声")
        elif r["id"] == "pace_window":
            actions.append("配速钳到 4:30-8:00/km 区间")
    if not actions:
        actions.append("无失败项；保持当前参数，继续做轨迹轮换")
    return actions
