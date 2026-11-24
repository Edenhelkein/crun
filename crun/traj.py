"""轨迹合成：闭环路线 + 配速模型 + 自相关 GPS 误差。

产出与真实跑步一致的序列特征：
  - 热身前慢、途中微漂、疲劳掉速、红绿灯停顿
  - GPS 误差不是白噪声（AR(1)），否则「相邻点过于平滑」本身就是特征
  - accuracy / satellite 随城市峡谷窗口波动
"""
import bisect
import hashlib
import math
import random

from .geo import haversine, geohash_encode, offset


def organic_loop(rng, origin, perimeter_m, n_ctrl=16):
    """半径调制的闭环：避免正圆/规则多边形（规则形状是路线指纹）。"""
    amp = perimeter_m / (2 * math.pi)
    a1, a2, a3 = rng.uniform(0.08, 0.24), rng.uniform(0.04, 0.16), rng.uniform(0.02, 0.10)
    p1, p2, p3 = rng.uniform(0, 6.28), rng.uniform(0, 6.28), rng.uniform(0, 6.28)
    rot = rng.uniform(0, 2 * math.pi)
    ctrl = []
    for i in range(n_ctrl):
        th = 2 * math.pi * i / n_ctrl + rot
        r = amp * (1 + a1 * math.sin(3 * th + p1) + a2 * math.sin(5 * th + p2) + a3 * math.sin(2 * th + p3))
        r = max(r, amp * 0.35)
        ctrl.append(offset(origin[0], origin[1], r * math.sin(th), r * math.cos(th)))
    return ctrl


def densify(ctrl, step_m=4.0):
    """把控制点连成 ~step_m 间隔的折线（闭环）。返回 (pts, cum)。"""
    n = len(ctrl)
    pts = []
    for i in range(n):
        a, b = ctrl[i], ctrl[(i + 1) % n]
        d = haversine(a, b)
        k = max(1, int(d / step_m))
        for j in range(k):
            f = j / k
            pts.append((a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f))
    pts.append(ctrl[0])
    cum = [0.0]
    for i in range(1, len(pts)):
        cum.append(cum[-1] + haversine(pts[i - 1], pts[i]))
    return pts, cum


def _at(pts, cum, s):
    """按里程 s 取折线上的点（闭环取模）。"""
    total = cum[-1]
    s = s % total
    i = bisect.bisect_right(cum, s) - 1
    i = max(0, min(i, len(pts) - 2))
    seg = cum[i + 1] - cum[i]
    f = 0.0 if seg <= 1e-9 else (s - cum[i]) / seg
    a, b = pts[i], pts[i + 1]
    return a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f


def speed_profile(rng, target_m, pace_s_per_km, dt=1.0):
    """生成 (t, s, v) 序列。v 单位 m/s，含热身/疲劳/红绿灯/AR(1) 微扰。"""
    base = 1000.0 / float(pace_s_per_km)
    n_stops = 0
    if rng.random() < 0.85:
        n_stops = rng.randint(1, 3)
    stop_marks = sorted(rng.uniform(0.12, 0.93) for _ in range(n_stops))
    stop_left = 0.0
    micro = 0.0
    t = 0.0
    d = 0.0
    out = []
    while d < target_m:
        frac = d / target_m
        warm = 0.55 + 0.45 * min(1.0, t / 90.0)
        fatigue = 1.0 - 0.05 * frac
        micro = 0.86 * micro + rng.gauss(0.0, 0.20)
        v = base * warm * fatigue * (1.0 + micro * 0.10)
        if stop_left > 0:
            v = 0.0
            stop_left -= dt
        elif stop_marks and frac >= stop_marks[0]:
            stop_marks.pop(0)
            stop_left = rng.uniform(15.0, 50.0)
            v = 0.0
            stop_left -= dt
        v = max(0.0, min(v, 7.2))
        out.append((round(t, 1), round(d, 2), round(v, 3)))
        d += v * dt
        t += dt
    return out, base


def simulate_run(rng, origin, target_m=2500.0, pace_s_per_km=360.0,
                 start_epoch=0.0, noise_sigma=3.0, canyon_p=0.12, canyon_mul=1.6,
                 route=None, mode="run"):
    if route:
        pts, cum = densify([tuple(p) for p in route], 3.0)
        target_m = cum[-1]
        ctrl = []
    else:
        ctrl = organic_loop(rng, origin, target_m)
        pts, cum = densify(ctrl, 4.0)
    prof, base_v = speed_profile(rng, target_m, pace_s_per_km)

    # 城市峡谷窗口：误差放大，但要带 5s 包络斜坡，否则会出现物理不可能的跳点
    windows, cur = [], 0
    while cur < len(prof):
        if rng.random() < canyon_p:
            ln = rng.randint(8, 25)
            windows.append((cur, cur + ln))
            cur += ln + rng.randint(40, 120)
        else:
            cur += 5

    def canyon_gain(i):
        g = 0.0
        for a, b in windows:
            if a <= i < b:
                g = max(g, 1.0)
            elif a - 5 <= i < a:
                g = max(g, (i - (a - 5)) / 5.0)
            elif b <= i < b + 5:
                g = max(g, (b + 5 - i) / 5.0)
        return g

    ex = ey = 0.0
    records = []
    for i, (t, d, v) in enumerate(prof):
        lat, lon = _at(pts, cum, d)
        g = canyon_gain(i)
        sigma = noise_sigma * (1.0 + (canyon_mul - 1.0) * g)
        k = 0.85
        ex = k * ex + rng.gauss(0.0, sigma * math.sqrt(1 - k * k))
        ey = k * ey + rng.gauss(0.0, sigma * math.sqrt(1 - k * k))
        lat_n, lon_n = offset(lat, lon, ex, ey)
        records.append({
            "t": round(start_epoch + t, 1),
            "lat": round(lat_n, 7),
            "lon": round(lon_n, 7),
            "alt": round(18.0 + 2.1 * math.sin(d / 240.0) + rng.gauss(0, 0.6), 2),
            "accuracy": round(rng.uniform(22.0, 38.0) if g > 0.4 else rng.uniform(4.5, 12.0), 1),
            "satellites": rng.randint(6, 9) if g > 0.4 else rng.randint(11, 21),
            "_v_true": v,
        })

    # 观测速度：app 拿到融合位置后按 3s 窗口反算 + 3 点中值（等价 Kalman 平滑）
    raw = []
    for i, r in enumerate(records):
        if i < 3:
            raw.append(0.0)
            continue
        p, q = records[i - 3], r
        raw.append(haversine((p["lat"], p["lon"]), (q["lat"], q["lon"])) / max(1e-6, (q["t"] - p["t"])))
    for i, r in enumerate(records):
        lo, hi = max(0, i - 1), min(len(raw) - 1, i + 1)
        win = sorted(raw[lo:hi + 1])
        r["speed"] = round(win[len(win) // 2], 3)

    # 5s 窗口平均速度：平台判"速度异常/瞬移"用的就是这类指标，比单点速度稳健得多
    for i, r in enumerate(records):
        if i < 5:
            r["speed5"] = 0.0
            continue
        p, q = records[i - 5], r
        r["speed5"] = round(haversine((p["lat"], p["lon"]), (q["lat"], q["lon"])) / max(1e-6, q["t"] - p["t"]), 3)


    gh = geohash_encode(origin[0], origin[1], 6)
    sig = "|".join(geohash_encode(r["lat"], r["lon"], 6) for r in records[::15])
    return {
        "route_ctrl": [[round(a, 7), round(b, 7)] for a, b in ctrl],
        "mode": mode,
        "origin": [round(origin[0], 7), round(origin[1], 7)],
        "geohash6": gh,
        "route_hash": hashlib.sha1(sig.encode()).hexdigest()[:16],
        "distance_m": round(prof[-1][1], 1),
        "duration_s": round(prof[-1][0], 1),
        "pace_s_per_km": round(prof[-1][0] / max(1e-6, prof[-1][1] / 1000.0), 1),
        "points": records,
    }
