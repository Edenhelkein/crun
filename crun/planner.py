"""会话规划：在"不重复、不定时、不越界"约束下选起点/时间/距离。"""
import json
import os
import random
import time

from .geo import geohash_encode, offset


class Planner:
    def __init__(self, state_path=None, min_gap_days=10, min_hours_between=14):
        self.state_path = state_path
        self.min_gap_days = min_gap_days
        self.min_hours_between = min_hours_between
        self.runs = []
        if state_path and os.path.exists(state_path):
            with open(state_path, encoding="utf-8") as f:
                self.runs = json.load(f).get("runs", [])

    def recent_geohashes(self):
        return {r["geohash6"] for r in self.runs}

    def plan(self, rng=None, origin=None, distance_m=2500.0, now_ts=None):
        rng = rng or random.Random()
        now_ts = now_ts or time.time()
        last = max((r.get("start_ts", 0) for r in self.runs), default=0)
        earliest = max(now_ts, last + self.min_hours_between * 3600)
        start_ts = earliest + rng.uniform(0, 3600)  # 1h 抖动

        # 起点抖动：候选直到不撞历史 geohash6
        seen = self.recent_geohashes()
        base = origin or (30.0, 120.0)
        chosen, gh = base, ""
        for _ in range(16):
            cand = offset(base[0], base[1], rng.uniform(-1800, 1800), rng.uniform(-1800, 1800))
            g = geohash_encode(cand[0], cand[1], 6)
            chosen, gh = cand, g
            if g not in seen:
                break

        # 时段抖动：避开历史 15min 桶
        buckets = {int((r.get("start_ts", 0) % 86400) // 900) for r in self.runs}
        for _ in range(24):
            if int((start_ts % 86400) // 900) not in buckets:
                break
            start_ts += 1500

        dist = round(rng.uniform(distance_m * 0.85, distance_m * 1.15), 0)
        pace = round(rng.uniform(330.0, 420.0), 0)  # 5:30-7:00 /km
        return {"start_ts": round(start_ts, 1), "origin": [round(chosen[0], 6), round(chosen[1], 6)],
                "geohash6": gh, "distance_m": dist, "pace_s_per_km": pace}

    def register(self, run):
        self.runs.append(run)
        if self.state_path:
            os.makedirs(os.path.dirname(os.path.abspath(self.state_path)), exist_ok=True)
            with open(self.state_path, "w", encoding="utf-8") as f:
                json.dump({"runs": self.runs[-200:]}, f, ensure_ascii=False, indent=2)
