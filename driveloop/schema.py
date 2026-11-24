"""行车数据模型与 CSV 读写。

字段刻意保持“车端可采、无需高精地图”：
CAN 车速/加速度/踏板 + 感知目标列表 + 天气与能见度 + 驾驶员接管状态。
这样即使没有仿真器，也能先用实车日志跑通长尾挖掘。
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path

CSV_FIELDS = [
    "t", "speed_kph", "accel_long", "accel_lat", "steer_deg",
    "brake", "throttle", "lane_id", "lane_offset", "weather",
    "visibility_m", "road_type", "speed_limit_kph", "driver_state", "objects",
]


@dataclass
class Track:
    id: str
    cls: str
    dist_m: float
    rel_speed_kph: float
    lat_m: float
    in_path: bool

    @classmethod
    def from_dict(cls, d: dict) -> "Track":
        return cls(
            id=str(d.get("id", "?"))[:24],
            cls=str(d.get("cls", "unknown"))[:24],
            dist_m=float(d.get("dist_m", 0)),
            rel_speed_kph=float(d.get("rel_speed_kph", 0)),
            lat_m=float(d.get("lat_m", 0)),
            in_path=bool(d.get("in_path", False)),
        )


@dataclass
class Frame:
    t: float
    speed_kph: float
    accel_long: float
    accel_lat: float
    steer_deg: float
    brake: float
    throttle: float
    lane_id: int
    lane_offset: float
    weather: str
    visibility_m: float
    road_type: str
    speed_limit_kph: float
    driver_state: str
    objects: list[Track] = field(default_factory=list)

    @property
    def speed_mps(self) -> float:
        return self.speed_kph / 3.6


def parse_row(row: dict) -> Frame:
    raw_objects = row.get("objects") or "[]"
    try:
        objs = json.loads(raw_objects)
    except json.JSONDecodeError:
        objs = []
    return Frame(
        t=float(row["t"]),
        speed_kph=float(row["speed_kph"]),
        accel_long=float(row["accel_long"]),
        accel_lat=float(row.get("accel_lat", 0)),
        steer_deg=float(row.get("steer_deg", 0)),
        brake=float(row.get("brake", 0)),
        throttle=float(row.get("throttle", 0)),
        lane_id=int(row.get("lane_id", 0)),
        lane_offset=float(row.get("lane_offset", 0)),
        weather=row.get("weather", "clear"),
        visibility_m=float(row.get("visibility_m", 1000)),
        road_type=row.get("road_type", "urban"),
        speed_limit_kph=float(row.get("speed_limit_kph", 50)),
        driver_state=row.get("driver_state", "engaged"),
        objects=[Track.from_dict(o) for o in objs],
    )


def load_csv(path: str | Path) -> list[Frame]:
    p = Path(path)
    with p.open(newline="", encoding="utf-8") as f:
        return [parse_row(row) for row in csv.DictReader(f)]


def write_csv(frames: list[Frame], path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for fr in frames:
            row = asdict(fr)
            row["objects"] = json.dumps(row["objects"], ensure_ascii=False)
            writer.writerow(row)
    return p
