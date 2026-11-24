"""传感器/计步合成：与 GPS 速度物理自洽。

平台反作弊最常见的一条硬校验：
    步数 * 步幅 ≈ GPS 里程   (偏差 >15~20% 直接判异常)
第二条：步频必须随配速变化，恒定步频 = 设备合成数据。
"""
import math


def _stride(v_mps):
    """步幅经验式：步行与跑步两段，7-8 km/h 之间平滑过渡。"""
    if v_mps < 0.2:
        return 0.0
    kmh = v_mps * 3.6
    walk = 0.66 + 0.085 * (kmh - 4.5)          # 3-7 km/h
    run = 0.95 + 0.052 * (kmh - 8.0)           # 8-16 km/h
    if kmh <= 7.0:
        s = walk
    elif kmh >= 8.0:
        s = run
    else:
        s = walk + (run - walk) * (kmh - 7.0)
    return max(0.55, min(1.55, s))


def build_steps(points, rng=None, ref_distance=None):
    """从 1Hz 速度序列生成步数/步频/加速度概要。

    ref_distance: 融合后里程。平台就是这么比的（步数*步幅 vs 自己平滑出来的里程），
    所以分母必须是平滑值，直接对带噪点位求和会凭空多出 30%+。
    """
    import random
    rng = rng or random.Random(7)
    steps = 0.0
    step_dist = 0.0
    step_log = []
    stride_sum = 0.0
    stride_n = 0
    for i, p in enumerate(points):
        v = float(p.get("_v_true", p.get("speed", 0.0)))
        st = _stride(v)
        if st <= 0:
            step_log.append({"t": p["t"], "steps": 0.0, "cadence": 0.0})
            continue
        cad = v * 60.0 / st                     # steps per minute
        inc = cad / 60.0                        # steps in this 1s window
        steps += inc
        step_dist += inc * st                   # 逐秒步幅积分，避免用均值步幅产生系统性偏差
        stride_sum += st
        stride_n += 1
        step_log.append({"t": p["t"], "steps": round(inc, 3), "cadence": round(cad, 1)})

    cadences = [s["cadence"] for s in step_log if s["cadence"] > 0]
    avg_stride = stride_sum / stride_n if stride_n else 0.0
    gps_dist = float(ref_distance) if ref_distance else 0.0
    if not gps_dist:
        for i in range(1, len(points)):
            a, b = points[i - 1], points[i]
            dlat = (b["lat"] - a["lat"]) * 111320.0
            dlon = (b["lon"] - a["lon"]) * 111320.0 * math.cos(math.radians(a["lat"]))
            gps_dist += math.hypot(dlat, dlon)

    # 50Hz 竖直加速度概要（前 6 秒），供 hook 回放
    accel = []
    t = 0.0
    idx = 0
    for _ in range(300):
        while idx + 1 < len(points) and points[idx + 1]["t"] <= points[0]["t"] + t:
            idx += 1
        cad = step_log[idx]["cadence"] if idx < len(step_log) else 0.0
        if cad > 0:
            f = cad / 60.0
            a = 9.81 + 2.4 * math.sin(2 * math.pi * f * t) + rng.gauss(0, 0.12)
        else:
            a = 9.81 + rng.gauss(0, 0.03)
        accel.append(round(a, 3))
        t += 0.02

    return {
        "total_steps": int(round(steps)),
        "avg_cadence_spm": round(sum(cadences) / len(cadences), 1) if cadences else 0.0,
        "cadence_min": round(min(cadences), 1) if cadences else 0.0,
        "cadence_max": round(max(cadences), 1) if cadences else 0.0,
        "avg_stride_m": round(avg_stride, 3),
        "step_distance_m": round(step_dist, 1),
        "gps_distance_m": round(gps_dist, 1),
        "step_gps_ratio": round(step_dist / gps_dist, 3) if gps_dist > 0 else 0.0,
        "accel_head_50hz": accel,
        "step_log_first10": step_log[:10],
    }
