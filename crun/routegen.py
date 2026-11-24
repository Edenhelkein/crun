"""路径随机化：小角度随机漫步 + 路线多样性仲裁。

要点：真人的跑步路线是「缓慢拐弯」而不是直角转弯。直角（±90°）是网格路的特征，
真实跑者在校园里更多是 10-30° 的小幅转向 + 长直道。

所以这里每个路口的转角被硬限制在 MAX_TURN_DEG=30° 以内（Beta(1.5,3.2) 分布，
大部分落在 5-15°），朝起点纠偏也用同样的角度上限逐步转，而不是一步甩过去。
生成后做两遍 3 点平滑，把接缝处的尖角抹掉。

多样性仲裁：候选路线算 geohash7 相邻格序列，与历史库比覆盖率，取最低的一条。
"""
import hashlib
import json
import math
import os
import random

from .geo import bearing, geohash_encode, haversine, offset

MAX_TURN_DEG = 30.0


# ---------------------------------------------------------------- 基础游走

def _wobble(rng, a, b, step_m=3.0, amp=1.1):
    """把一条直段拆成带轻微摆动的点列（GPS 之前的路面形状）。"""
    d = haversine(a, b)
    n = max(1, int(d / step_m))
    out = []
    for i in range(n):
        f = i / n
        lat = a[0] + (b[0] - a[0]) * f
        lon = a[1] + (b[1] - a[1]) * f
        w = amp * math.sin(math.pi * f) * rng.uniform(-1, 1)
        out.append(offset(lat, lon, w * 0.6, w))
    return out


def _smooth(pts, passes=2):
    """3 点加权平滑，抹掉段间接缝。"""
    for _ in range(passes):
        if len(pts) < 3:
            break
        out = [pts[0]]
        for i in range(1, len(pts) - 1):
            a, b, c = pts[i - 1], pts[i], pts[i + 1]
            out.append(((a[0] + 2 * b[0] + c[0]) / 4.0, (a[1] + 2 * b[1] + c[1]) / 4.0))
        out.append(pts[-1])
        pts = out
    return pts


def _wrap(a):
    return (a + math.pi) % (2 * math.pi) - math.pi


def wander(rng, start, target_m, seg_m=(45, 120), radius_m=None, max_turn_deg=MAX_TURN_DEG):
    """小角度随机漫步：单次转向 ≤ max_turn_deg，收尾时按同样角度上限朝起点纠偏。"""
    radius = radius_m or max(280.0, target_m / 4.2)
    limit = math.radians(max_turn_deg)
    theta = rng.uniform(0, 2 * math.pi)
    p = start
    pts = [start]
    walked = 0.0
    guard = 0
    while walked + haversine(p, start) < target_m and guard < 8000:
        guard += 1
        d_start = haversine(p, start)
        if d_start > radius * 0.92:
            brg = math.atan2(start[0] - p[0],
                             (start[1] - p[1]) * math.cos(math.radians(p[0])))
            theta += max(-limit, min(limit, _wrap(brg - theta)))
        elif rng.random() < 0.82:
            mag = limit * rng.betavariate(1.5, 3.2)      # 主要 5-15°，上限 30°
            theta += rng.choice([-1.0, 1.0]) * mag
        L = rng.uniform(*seg_m)
        nxt = offset(p[0], p[1], L * math.sin(theta), L * math.cos(theta))
        pts.extend(_wobble(rng, p, nxt))
        walked += haversine(p, nxt)
        p = nxt
        pts.append(p)

    # 回家：仍然每次最多转 30°
    guard = 0
    while haversine(p, start) > 18 and guard < 1200:
        guard += 1
        brg = math.atan2(start[0] - p[0],
                         (start[1] - p[1]) * math.cos(math.radians(p[0])))
        theta += max(-limit, min(limit, _wrap(brg - theta)))
        L = min(haversine(p, start), rng.uniform(40, 100))
        nxt = offset(p[0], p[1], L * math.sin(theta), L * math.cos(theta))
        pts.extend(_wobble(rng, p, nxt))
        p = nxt
        pts.append(p)
    if haversine(p, start) <= 60:
        pts.append(start)
    return _smooth(pts, 2)


def resample(pts, step_m=10.0):
    out = [pts[0]]
    acc = 0.0
    for i in range(1, len(pts)):
        acc += haversine(pts[i - 1], pts[i])
        if acc >= step_m:
            out.append(pts[i])
            acc = 0.0
    if out[-1] != pts[-1]:
        out.append(pts[-1])
    return out


def route_max_turn(pts, step_m=10.0):
    """按等距重采样后统计相邻航向变化的最大值（度）。"""
    rs = resample(pts, step_m)
    if len(rs) < 3:
        return 0.0
    hs = [bearing(rs[i], rs[i + 1]) for i in range(len(rs) - 1)]
    worst = 0.0
    for i in range(1, len(hs)):
        d = abs((hs[i] - hs[i - 1] + 180.0) % 360.0 - 180.0)
        worst = max(worst, d)
    return worst


def cells_of(pts, precision=7):
    return sorted({geohash_encode(pt[0], pt[1], precision) for pt in pts})


def edges_of(pts, precision=7):
    """有序相邻格：同一条路的「格序列」才叫重跑同一条线，光压到同几个格子不算。"""
    seq = []
    for pt in pts:
        c = geohash_encode(pt[0], pt[1], precision)
        if not seq or seq[-1] != c:
            seq.append(c)
    return [f"{a}>{b}" for a, b in zip(seq, seq[1:])]


def overlap(a_cells, b_cells):
    if not a_cells or not b_cells:
        return 0.0
    a, b = set(a_cells), set(b_cells)
    return len(a & b) / min(len(a), len(b))


def route_fingerprint(pts):
    h = hashlib.blake2b(digest_size=8)
    for e in edges_of(pts, 7):
        h.update(e.encode())
    return h.hexdigest()


# ---------------------------------------------------------------- 路线库

class RouteLibrary:
    """历史路线 + 覆盖格。用于判重和选新线。"""

    def __init__(self, path=None):
        self.path = path
        self.routes = []
        if path and os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                self.routes = json.load(f).get("routes", [])

    def add(self, pts, ts, distance_m=None):
        entry = {"cells": cells_of(pts), "edges": edges_of(pts), "ts": ts,
                 "fp": route_fingerprint(pts),
                 "start_cell": geohash_encode(pts[0][0], pts[0][1], 6),
                 "distance_m": distance_m}
        self.routes.append(entry)
        self.routes = self.routes[-300:]
        return entry

    def max_overlap(self, cells=None, pts=None, since_days=None, now=None):
        c = cells if cells is not None else (edges_of(pts) if pts is not None else [])
        best, who = 0.0, None
        for r in self.routes:
            if since_days is not None and now is not None:
                if now - r.get("ts", 0) > since_days * 86400:
                    continue
            o = overlap(c, r.get("edges") or r.get("cells") or [])
            if o > best:
                best, who = o, r
        return best, who

    def save(self):
        if not self.path:
            return
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"routes": self.routes}, f, ensure_ascii=False, indent=2)


def generate_diverse(rng, start, target_m, library=None, tries=20, max_overlap=0.55,
                     max_turn_deg=MAX_TURN_DEG, now=None):
    """生成候选路线，按重叠度 + 转角合规度仲裁，返回 (pts, meta)。"""
    cands = []
    for _ in range(tries):
        pts = wander(rng, start, target_m, max_turn_deg=max_turn_deg)
        edges = edges_of(pts)
        cells = cells_of(pts)
        ov, who = (library.max_overlap(cells=edges) if library else (0.0, None))
        turn = route_max_turn(pts, 10.0)
        cands.append({"pts": pts, "cells": cells, "edges": edges, "overlap": ov,
                      "turn": turn, "fp": route_fingerprint(pts),
                      "distance_m": sum(haversine(pts[i], pts[i + 1]) for i in range(len(pts) - 1))})
    # 先剔掉转角超标的，再按重叠度、再按里程接近度
    ok = [c for c in cands if c["turn"] <= max_turn_deg + 2.0] or cands
    ok.sort(key=lambda c: (c["overlap"], abs(c["distance_m"] - target_m)))
    best = ok[0]
    meta = {"overlap": round(best["overlap"], 3), "cells": len(best["cells"]),
            "fp": best["fp"], "distance_m": round(best["distance_m"], 1),
            "max_turn_deg": round(best["turn"], 1), "turn_limit": max_turn_deg,
            "candidates": len(cands), "accepted": best["overlap"] <= max_overlap}
    return best["pts"], meta
