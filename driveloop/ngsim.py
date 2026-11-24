"""NGSIM US-101 轨迹 -> driveloop 车端 CSV 的转换核心。

NGSIM 是 10Hz 的实车轨迹：Local_X 横向、Local_Y 纵向、Lane_ID 车道、
v_Vel 车速、v_Acc 加速度。它没有 CAN 踏板，所以 brake/throttle 由加速度反推。
NGSIM 只有机动车，没有行人/骑行者；VRU 仍由 Argoverse 子集覆盖。
"""

from __future__ import annotations

import math
from collections import defaultdict

from .schema import Frame, Track

# NGSIM v_Class: 1 motorcycle, 2 auto, 3 truck.
CLASS_MAP = {1: "motorcycle", 2: "car", 3: "truck"}

FPS = 10.0
DT = 1.0 / FPS
FT_TO_M = 0.3048
FTPS_TO_KPH = 1.09728


def _num(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def frames_from_rows(
    rows: list[dict],
    ego_id: str,
    duration_s: float = 5.0,
    max_objects: int = 16,
) -> list[Frame]:
    """把 NGSIM 的逐帧行记录转成 Frame 列表。

    行记录至少包含: frame, vid, x, y, lane, vel, acc, cls。
    坐标已经是路段局部坐标：x 横向、y 沿行驶方向，所以不需要旋转。
    """
    by_frame: dict[int, dict[str, dict]] = defaultdict(dict)
    for r in rows:
        by_frame[int(_num(r.get("frame"), -1))][str(r.get("vid"))] = r

    frames_sorted = sorted(by_frame)
    n_frames = int(round(duration_s / DT)) + 1
    if len(frames_sorted) < n_frames:
        raise ValueError(f"帧数不足: {len(frames_sorted)} < {n_frames}")
    timesteps = frames_sorted[:n_frames]
    if any(b - a != 1 for a, b in zip(timesteps, timesteps[1:])):
        raise ValueError("NGSIM 帧不连续，无法按 10Hz 转换")

    ego_by_t = {t: by_frame[t][ego_id] for t in timesteps if ego_id in by_frame[t]}
    if len(ego_by_t) != len(timesteps):
        raise ValueError(f"ego {ego_id} 在部分帧缺失")

    # 车道中心：同一帧同一 Lane_ID 的车辆横向位置中位数。
    lane_centers: dict[int, list[float]] = defaultdict(list)
    for t in timesteps:
        for r in by_frame[t].values():
            lane_centers[int(_num(r.get("lane")))].append(_num(r.get("x")))
    lane_center = {k: sorted(v)[len(v) // 2] for k, v in lane_centers.items() if v}

    frames: list[Frame] = []
    for i, t in enumerate(timesteps):
        ego = ego_by_t[t]
        ex, ey = _num(ego.get("x")), _num(ego.get("y"))
        speed_kph = _num(ego.get("vel")) * FTPS_TO_KPH
        accel = _num(ego.get("acc")) * FT_TO_M
        lane = int(_num(ego.get("lane")))

        objects: list[Track] = []
        for vid, r in by_frame[t].items():
            if vid == ego_id:
                continue
            ox, oy = _num(r.get("x")), _num(r.get("y"))
            dx, dy = ox - ex, oy - ey
            dist = math.hypot(dx, dy)
            if dist > 70.0:
                continue
            lat = dx
            x_fwd = dy
            rel_speed_kph = (_num(r.get("vel")) - _num(ego.get("vel"))) * FTPS_TO_KPH
            objects.append(
                Track(
                    id=vid,
                    cls=CLASS_MAP.get(int(_num(r.get("cls"), 2)), "other"),
                    dist_m=round(dist, 2),
                    rel_speed_kph=round(rel_speed_kph, 2),
                    lat_m=round(lat, 2),
                    in_path=bool(abs(lat) < 1.8 and 0.0 < x_fwd < 70.0),
                )
            )

        # 近处目标全保留，远处补到 max_objects。
        near = [o for o in objects if o.dist_m <= 40.0]
        far = sorted([o for o in objects if o.dist_m > 40.0], key=lambda o: o.dist_m)
        keep = sorted(near, key=lambda o: o.dist_m) + far[: max(0, max_objects - len(near))]
        keep = keep[:max_objects]

        frames.append(
            Frame(
                t=round(i / FPS, 1),
                speed_kph=round(speed_kph, 2),
                accel_long=round(accel, 3),
                accel_lat=0.0,
                steer_deg=0.0,
                brake=round(_clamp(-accel / 8.0, 0.0, 1.0), 3),
                throttle=round(_clamp(accel / 5.0, 0.0, 1.0), 3),
                lane_id=lane,
                lane_offset=round(ex - lane_center.get(lane, ex), 2),
                weather="clear",
                visibility_m=10000.0,
                road_type="highway",
                speed_limit_kph=105.0,
                driver_state="engaged",
                objects=keep,
            )
        )
    return frames
