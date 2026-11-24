"""长尾事件检测：只用车端信号 + 感知目标，不依赖高精地图与人工看片。

检测器输出“事件”，再按时间邻近聚类成“场景”，避免同一段危险工况被拆成十几条。
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict

from .schema import Frame, Track

VRU_CLASSES = {"pedestrian", "cyclist", "bicycle", "motorcycle", "rider"}


@dataclass
class Event:
    type: str
    start: float
    end: float
    score: int
    key_t: float
    detail: dict = field(default_factory=dict)
    involved: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Scene:
    id: str
    primary: str
    types: list[str]
    start: float
    end: float
    risk: int
    severity: str
    events: list[Event]
    key_t: float
    odd: dict
    ego_speed_kph: float
    min_ttc: float | None
    max_decel: float | None
    involved: list[str]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["events"] = [e.to_dict() for e in self.events]
        return d


def _ttc(obj: Track, ego_speed_mps: float) -> float | None:
    if not obj.in_path or obj.dist_m <= 0:
        return None
    closing = -obj.rel_speed_kph / 3.6
    if closing <= 1.0:
        return None
    return obj.dist_m / closing


def detect_events(frames: list[Frame]) -> list[Event]:
    raw: list[tuple[str, float, int, dict, list[str]]] = []

    for i, fr in enumerate(frames):
        prev = frames[i - 1] if i > 0 else None

        # 1) 急刹（持续 0.4s 以上才能算，避免单帧噪声）
        if fr.accel_long <= -6.0 and fr.speed_kph > 15:
            raw.append(("hard_brake", fr.t, 40, {"accel_mps2": round(fr.accel_long, 2)}, []))

        # 2) 接管
        if fr.driver_state != "engaged":
            raw.append(("takeover", fr.t, 70, {"state": fr.driver_state}, []))

        # 3) 低能见度
        if fr.visibility_m < 50:
            raw.append(("low_visibility", fr.t, 35, {"visibility_m": fr.visibility_m, "weather": fr.weather}, []))

        # 4) 施工路段
        if fr.road_type == "construction":
            raw.append(("construction", fr.t, 25, {"road_type": fr.road_type}, []))

        # 5) 超速
        if fr.speed_kph > fr.speed_limit_kph + 10:
            raw.append(("speed_over", fr.t, 20, {"speed_kph": fr.speed_kph, "limit": fr.speed_limit_kph}, []))

        for obj in fr.objects:
            ttc = _ttc(obj, fr.speed_mps)

            # 6) 近碰撞：TTC < 2.5s 为高危，< 4s 为 warning
            if ttc is not None and ttc < 4.0:
                score = 60 if ttc < 2.5 else 45
                raw.append(
                    ("near_miss", fr.t, score,
                     {"ttc_s": round(ttc, 2), "dist_m": round(obj.dist_m, 1), "cls": obj.cls},
                     [obj.id])
                )

            # 7) cut-in：本帧在车道内，0.8 秒前还不在，且距离够近
            if obj.in_path and obj.cls not in VRU_CLASSES and fr.t > 0:
                was_out = False
                for back in range(1, 9):
                    j = i - back
                    if j < 0:
                        break
                    prev_obj = next((o for o in frames[j].objects if o.id == obj.id), None)
                    if prev_obj is None:
                        continue
                    if not prev_obj.in_path:
                        was_out = True
                        break
                if was_out and obj.dist_m < 35:
                    raw.append(
                        ("cut_in", fr.t, 55,
                         {"dist_m": round(obj.dist_m, 1), "lat_m": round(obj.lat_m, 2), "cls": obj.cls},
                         [obj.id])
                    )

            # 8) VRU 突然进入本车道
            if obj.cls in VRU_CLASSES and obj.in_path and obj.dist_m < 20:
                prev_obj = next((o for o in frames[i - 1].objects if o.id == obj.id), None) if i > 0 else None
                entered_path = prev_obj is not None and not prev_obj.in_path
                if entered_path or obj.dist_m < 20 or (ttc is not None and ttc < 4.0):
                    raw.append(
                        ("vru_sudden", fr.t, 65,
                         {"dist_m": round(obj.dist_m, 1), "cls": obj.cls, "ttc_s": round(ttc, 2) if ttc else None},
                         [obj.id])
                    )

    # 同类事件按时间合并（间隔 ≤ 2.5s 视为同一段）
    grouped: dict[str, list[tuple[float, int, dict, list[str]]]] = {}
    for typ, t, score, detail, inv in raw:
        grouped.setdefault(typ, []).append((t, score, detail, inv))

    events: list[Event] = []
    for typ, items in grouped.items():
        items.sort(key=lambda x: x[0])
        cur = [items[0]]
        for item in items[1:]:
            if item[0] - cur[-1][0] <= 2.5:
                cur.append(item)
            else:
                events.append(_pack_event(typ, cur))
                cur = [item]
        events.append(_pack_event(typ, cur))

    events.sort(key=lambda e: (e.start, -e.score))
    return events


def _pack_event(typ: str, items: list[tuple[float, int, dict, list[str]]]) -> Event:
    best = max(items, key=lambda x: x[1])
    key_t = best[0]
    detail = best[2]
    if typ == "near_miss":
        worst = min((i for i in items if i[2].get("ttc_s") is not None), key=lambda x: x[2]["ttc_s"], default=None)
        if worst:
            key_t, detail = worst[0], worst[2]
    elif typ == "hard_brake":
        worst = min(items, key=lambda x: x[2].get("accel_mps2", 0))
        key_t, detail = worst[0], worst[2]
    return Event(
        type=typ,
        start=items[0][0],
        end=items[-1][0],
        score=best[1],
        key_t=key_t,
        detail=detail,
        involved=sorted({i for item in items for i in item[3]}),
    )


PRIORITY = ["takeover", "vru_sudden", "cut_in", "near_miss", "hard_brake", "low_visibility", "construction", "speed_over"]

TYPE_LABELS = {
    "takeover": "驾驶员接管",
    "vru_sudden": "行人/两轮车突入",
    "near_miss": "近碰撞（低 TTC）",
    "cut_in": "旁车切入",
    "hard_brake": "急刹",
    "low_visibility": "低能见度",
    "construction": "施工路段",
    "speed_over": "超速",
}


def _severity(risk: int) -> str:
    if risk >= 70:
        return "high"
    if risk >= 45:
        return "medium"
    return "low"


def cluster_scenes(events: list[Event], frames: list[Frame], gap_s: float = 2.5) -> list[Scene]:
    if not events:
        return []
    clusters: list[list[Event]] = []
    for ev in events:
        if clusters and ev.start - max(e.end for e in clusters[-1]) <= gap_s:
            clusters[-1].append(ev)
        else:
            clusters.append([ev])

    scenes: list[Scene] = []
    for idx, group in enumerate(clusters, start=1):
        types = sorted({e.type for e in group})
        primary = next(t for t in PRIORITY if t in types)
        risk = min(100, max(e.score for e in group) + 5 * (len(types) - 1))
        key_ev = max(group, key=lambda e: e.score)
        key_frame = min(frames, key=lambda f: abs(f.t - key_ev.key_t))
        odd = {
            "weather": key_frame.weather,
            "visibility_m": key_frame.visibility_m,
            "road_type": key_frame.road_type,
            "speed_limit_kph": key_frame.speed_limit_kph,
        }
        ttcs = [e.detail["ttc_s"] for e in group if e.type == "near_miss" and e.detail.get("ttc_s")]
        decels = [e.detail["accel_mps2"] for e in group if e.type == "hard_brake" and e.detail.get("accel_mps2")]
        involved = sorted({i for e in group for i in e.involved})
        scenes.append(
            Scene(
                id=f"SC-{idx:03d}",
                primary=primary,
                types=types,
                start=round(min(e.start for e in group), 1),
                end=round(max(e.end for e in group), 1),
                risk=risk,
                severity=_severity(risk),
                events=group,
                key_t=round(key_ev.key_t, 1),
                odd=odd,
                ego_speed_kph=round(key_frame.speed_kph, 1),
                min_ttc=round(min(ttcs), 2) if ttcs else None,
                max_decel=round(min(decels), 2) if decels else None,
                involved=involved,
            )
        )
    return scenes
