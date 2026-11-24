"""Argoverse 2 轨迹 -> driveloop 车端 CSV 的转换核心。

只依赖标准库，方便在 CI 和没有 pandas 的环境里单测。
真实 parquet 的读取放在 scripts/import_argoverse.py。
"""

from __future__ import annotations

import math
from collections import defaultdict

from .schema import Frame, Track

# Argoverse 2 的物体类型里，只有这些会移动，才值得放进 objects。
DYNAMIC_TYPES = {
    "vehicle",
    "bus",
    "truck",
    "motorcyclist",
    "motorcycle",
    "cyclist",
    "pedestrian",
    "riderless_bicycle",
    "rider",
    "stroller",
    "wheelchair",
    "personal_mobility",
}

CLASS_MAP = {
    "vehicle": "car",
    "bus": "bus",
    "truck": "truck",
    "pedestrian": "pedestrian",
    "cyclist": "cyclist",
    "riderless_bicycle": "bicycle",
    "motorcyclist": "motorcycle",
    "motorcycle": "motorcycle",
    "rider": "motorcycle",
    "stroller": "pedestrian",
    "wheelchair": "pedestrian",
    "personal_mobility": "pedestrian",
}


def _central_diff(values: list[float], dt: float) -> list[float]:
    n = len(values)
    if n == 0:
        return []
    if n == 1:
        return [0.0]
    out = [0.0] * n
    out[0] = (values[1] - values[0]) / dt
    out[-1] = (values[-1] - values[-2]) / dt
    for i in range(1, n - 1):
        out[i] = (values[i + 1] - values[i - 1]) / (2 * dt)
    return out


def _moving_average(values: list[float], window: int) -> list[float]:
    if window <= 1 or len(values) <= 1:
        return list(values)
    half = window // 2
    out = []
    for i in range(len(values)):
        lo = max(0, i - half)
        hi = min(len(values), i + half + 1)
        out.append(sum(values[lo:hi]) / (hi - lo))
    return out


def _unwrap_angles(values: list[float]) -> list[float]:
    if not values:
        return []
    out = [values[0]]
    for v in values[1:]:
        prev = out[-1]
        while v - prev > math.pi:
            v -= 2 * math.pi
        while v - prev < -math.pi:
            v += 2 * math.pi
        out.append(v)
    return out


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _num(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _class_of(obj_type: str) -> str:
    return CLASS_MAP.get(str(obj_type), "other")


def frames_from_rows(
    rows: list[dict],
    ego_id: str = "AV",
    duration_s: float = 5.0,
    dt: float = 0.1,
    max_objects: int = 24,
) -> list[Frame]:
    """把 Argoverse 2 motion-forecasting 的行记录转成 Frame 列表。

    行记录至少包含:
      track_id, object_type, timestep, position_x, position_y, heading,
      velocity_x, velocity_y, observed
    ego_id 默认 "AV"（Argoverse 日志里的自动驾驶车），找不到时退化为
    focal_track_id（如果行里带了）。
    """
    if not rows:
        raise ValueError("rows 为空")

    # 只保留 0..n-1 的连续 timestep，避免末尾缺帧把插值搞坏。
    by_t: dict[int, dict[str, dict]] = defaultdict(dict)
    for r in rows:
        if not bool(r.get("observed", True)):
            continue
        t = int(_num(r.get("timestep"), -1))
        if t < 0:
            continue
        by_t[t][str(r.get("track_id"))] = r

    n_frames = int(round(duration_s / dt)) + 1
    timesteps = [t for t in range(n_frames) if t in by_t]
    if len(timesteps) < 10:
        raise ValueError(f"有效 timestep 太少: {len(timesteps)}")
    if timesteps != list(range(len(timesteps))):
        raise ValueError("timestep 不连续，无法按 10Hz 转换")

    ego_rows = by_t[0].get(ego_id)
    if ego_rows is None:
        # 退化为 focal 轨道：有些导出文件只保留了 focal_track_id。
        focal = next((r.get("focal_track_id") for r in rows if r.get("focal_track_id")), None)
        if focal and str(focal) in by_t[0]:
            ego_id = str(focal)
        else:
            raise ValueError(f"找不到 ego 轨道 {ego_id!r}")

    ego_by_t = {t: by_t[t][ego_id] for t in timesteps if ego_id in by_t[t]}
    if len(ego_by_t) != len(timesteps):
        raise ValueError("ego 轨道在部分 timestep 缺失")

    xs = [_num(ego_by_t[t].get("position_x")) for t in timesteps]
    ys = [_num(ego_by_t[t].get("position_y")) for t in timesteps]
    hs = [_num(ego_by_t[t].get("heading")) for t in timesteps]
    hs = _unwrap_angles(hs)

    vx = _central_diff(xs, dt)
    vy = _central_diff(ys, dt)
    speed = _moving_average([math.hypot(a, b) for a, b in zip(vx, vy)], 5)
    accel = _moving_average(_central_diff(speed, dt), 3)
    yaw_rate = _moving_average(_central_diff(hs, dt), 5)

    frames: list[Frame] = []
    for i, t in enumerate(timesteps):
        ego = ego_by_t[t]
        eh = hs[i]
        ex, ey = xs[i], ys[i]
        speed_mps = speed[i]
        # 自行车模型近似，仅用于填字段；检测器不依赖它做判定。
        steer = 0.0
        if speed_mps > 2.0:
            steer = math.degrees(math.atan2(2.7 * yaw_rate[i], speed_mps))
        steer = _clamp(steer, -35.0, 35.0)

        objects: list[Track] = []
        for tid, r in by_t[t].items():
            if tid == ego_id:
                continue
            if str(r.get("object_type")) not in DYNAMIC_TYPES:
                continue
            ox = _num(r.get("position_x"))
            oy = _num(r.get("position_y"))
            dx, dy = ox - ex, oy - ey
            dist = math.hypot(dx, dy)
            if dist > 80.0:
                continue
            x_fwd = dx * math.cos(eh) + dy * math.sin(eh)
            lat = -dx * math.sin(eh) + dy * math.cos(eh)

            prev = by_t.get(t - 1, {}).get(tid) if t > 0 else None
            if prev is not None:
                gvx = (_num(r.get("position_x")) - _num(prev.get("position_x"))) / dt
                gvy = (_num(r.get("position_y")) - _num(prev.get("position_y"))) / dt
                v_long = gvx * math.cos(eh) + gvy * math.sin(eh)
            else:
                v_long = 0.0
            rel_speed_kph = (v_long - speed_mps) * 3.6

            objects.append(
                Track(
                    id=tid,
                    cls=_class_of(str(r.get("object_type"))),
                    dist_m=round(dist, 2),
                    rel_speed_kph=round(rel_speed_kph, 2),
                    lat_m=round(lat, 2),
                    in_path=bool(abs(lat) < 1.8 and 0.0 < x_fwd < 80.0),
                )
            )

        # 先保留 40m 内的全部目标，再按距离补齐到 max_objects。
        near = [o for o in objects if o.dist_m <= 40.0]
        far = sorted([o for o in objects if o.dist_m > 40.0], key=lambda o: o.dist_m)
        keep = sorted(near, key=lambda o: o.dist_m) + far[: max(0, max_objects - len(near))]
        keep = keep[:max_objects]

        frames.append(
            Frame(
                t=round(i * dt, 1),
                speed_kph=round(speed_mps * 3.6, 2),
                accel_long=round(accel[i], 3),
                accel_lat=round(speed_mps * yaw_rate[i], 3),
                steer_deg=round(steer, 2),
                brake=round(_clamp(-accel[i] / 8.0, 0.0, 1.0), 3),
                throttle=round(_clamp(accel[i] / 5.0, 0.0, 1.0), 3),
                lane_id=0,
                lane_offset=0.0,
                weather="clear",
                visibility_m=10000.0,
                road_type="urban",
                speed_limit_kph=50.0,
                driver_state="engaged",
                objects=keep,
            )
        )
    return frames
