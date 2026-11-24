"""合成一段城市工况日志，用于无实车数据时跑通挖掘链路。

场景脚本（90 秒，10Hz）：
10–16s  邻车道车辆 cut-in，TTC 进入 3s 内
26–32s  行人突然进入本车道（此前不在感知范围）
40–42s  前车急刹，自车约 -8m/s² 制动
55–60s  驾驶员接管
68–82s  能见度降到 30m
85–90s  进入施工路段
"""

from __future__ import annotations

import math
import random
from pathlib import Path

from .schema import Frame, Track, write_csv


def _lerp_speed(t: float) -> float:
    keys = [
        (0, 50), (9, 50), (9.6, 46), (12, 42), (16, 42), (20, 48),
        (26, 50), (26.6, 44), (28, 34), (32, 26), (36, 38), (40, 46),
        (40.8, 30), (41.6, 6), (46, 6), (50, 24), (54, 30), (55, 30),
        (60, 30), (66, 42), (70, 50), (74, 46), (80, 40), (82, 30),
        (86, 26), (90, 20),
    ]
    for i in range(len(keys) - 1):
        t0, v0 = keys[i]
        t1, v1 = keys[i + 1]
        if t0 <= t <= t1:
            k = (t - t0) / max(t1 - t0, 1e-6)
            return v0 + (v1 - v0) * k
    return keys[-1][1]


def _cutin_objects(t: float) -> list[Track]:
    objs: list[Track] = []
    # 邻车道常态车辆
    if t < 9 or t > 20:
        objs.append(Track("v-left", "car", 35.0, 4.0, -3.4, False))
    # cut-in：10s 起横向移动，12s 完成入道，纵向距离 26m 收敛到 14m
    if 9.0 <= t <= 20.0:
        prog = min(1.0, max(0.0, (t - 10.0) / 2.0))
        lat = -3.2 + 3.2 * prog
        dist = 26.0 - 12.0 * min(1.0, max(0.0, (t - 10.0) / 5.0))
        rel = -20.0 if t < 14 else -6.0
        objs.append(Track("v-cutin", "car", max(12.0, dist), rel, lat, prog > 0.85))
    # 行人：26.5s 从路侧进入
    if 26.4 <= t <= 32.0:
        prog = min(1.0, (t - 26.4) / 1.0)
        objs.append(Track("p-1", "pedestrian", max(4.0, 22.0 - 4.0 * max(0.0, t - 26.4)), -10.0, -2.6 + 2.6 * prog, prog > 0.6))
    # 前车急刹：40–44s
    if 38.0 <= t <= 46.0:
        dist = 18.0 - 9.0 * max(0.0, t - 40.0)
        objs.append(Track("v-lead", "car", max(6.0, dist), -18.0 if t < 42 else -4.0, 0.0, True))
    # 背景车流
    if 30 < t < 70:
        objs.append(Track("v-right", "car", 40.0, 6.0, 3.5, False))
    return objs


def make_log(seconds: int = 90, hz: int = 10, seed: int = 7) -> list[Frame]:
    random.seed(seed)
    frames: list[Frame] = []
    n = seconds * hz
    prev_v = _lerp_speed(0)
    for i in range(n + 1):
        t = round(i / hz, 1)
        v_kmh = _lerp_speed(t)
        v_mps = v_kmh / 3.6
        prev_mps = prev_v / 3.6
        accel = (v_mps - prev_mps) / (1 / hz)
        prev_v = v_kmh
        accel += random.uniform(-0.15, 0.15)
        accel = max(-9.5, min(4.0, accel))

        weather = "clear"
        visibility = 1000.0
        if 68 <= t <= 82:
            weather = "fog"
            visibility = 30.0
        road = "construction" if t >= 85 else "urban"

        driver = "engaged"
        if 55 <= t <= 60:
            driver = "takeover"

        frames.append(
            Frame(
                t=t,
                speed_kph=round(v_kmh, 2),
                accel_long=round(accel, 3),
                accel_lat=round(math.sin(t / 6) * 0.2, 3),
                steer_deg=round(math.sin(t / 8) * 4, 2),
                brake=round(max(0.0, -accel / 9.0), 3),
                throttle=round(max(0.0, accel / 4.0), 3),
                lane_id=-1,
                lane_offset=round(random.uniform(-0.3, 0.3), 2),
                weather=weather,
                visibility_m=visibility,
                road_type=road,
                speed_limit_kph=50.0 if road == "urban" else 30.0,
                driver_state=driver,
                objects=_cutin_objects(t),
            )
        )
    return frames


def generate(out_dir: str | Path, seconds: int = 90, hz: int = 10) -> Path:
    out = Path(out_dir)
    p = write_csv(make_log(seconds=seconds, hz=hz), out / "urban_90s.csv")
    return p


if __name__ == "__main__":
    print(generate("data/logs"))
