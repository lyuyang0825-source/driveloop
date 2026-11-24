#!/usr/bin/env python3
"""从 NGSIM US-101 轨迹构建 30 段真实驾驶 clip 中的 14 段。

10 段是严格定义的同向 cut-in：旁车从相邻车道进入 ego 车道，ego 在后方 5–35m；
4 段是高速跟驰负例。NGSIM 是 10Hz 实车轨迹，不是仿真。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from driveloop.ngsim import frames_from_rows
from driveloop.schema import write_csv

COLS = [
    "vid", "frame", "total", "time", "x", "y", "gx", "gy", "length", "width",
    "cls", "vel", "acc", "lane", "o_zone", "u1", "u2", "u3",
]

# 由 scripts/find_ngsim_cutin.py 的全量扫描得到；按 gap 20–35m、ego 速度 ≥40kph 选前 10。
CUTINS = [
    ("ngsim_0001_cutin", 689, 686, 1810, 28.3),
    ("ngsim_0002_cutin", 1722, 1719, 5029, 32.8),
    ("ngsim_0003_cutin", 983, 966, 2664, 32.0),
    ("ngsim_0004_cutin", 2158, 2159, 6479, 31.4),
    ("ngsim_0005_cutin", 617, 612, 1661, 30.8),
    ("ngsim_0006_cutin", 2566, 2565, 7441, 31.0),
    ("ngsim_0007_cutin", 2743, 2745, 8059, 27.6),
    ("ngsim_0008_cutin", 1984, 1978, 5664, 34.2),
    ("ngsim_0009_cutin", 1969, 1963, 5675, 26.7),
    ("ngsim_0010_cutin", 997, 987, 2447, 33.9),
]

# 高速跟驰、无 cut-in 的负例；frame 取轨迹中段。
NEGATIVES = [
    ("ngsim_0011_negative", 5, 300),
    ("ngsim_0012_negative", 9, 300),
    ("ngsim_0013_negative", 20, 300),
    ("ngsim_0014_negative", 25, 350),
]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="/tmp/ngsim/trajectories-0750am-0805am.txt")
    ap.add_argument("--out", default="data/real/ngsim")
    args = ap.parse_args(argv)

    raw = Path(args.raw)
    if not raw.exists():
        raise SystemExit(f"找不到 NGSIM 原始文件: {raw}\n先下载 US-101 15 分钟轨迹并解压。")
    df = pd.read_csv(raw, sep=r"\s+", header=None, names=COLS)
    df = df.sort_values(["vid", "frame"])
    by_vid = {int(k): g for k, g in df.groupby("vid", sort=False)}

    out = Path(args.out)
    (out / "clips").mkdir(parents=True, exist_ok=True)
    labels, clips = [], []
    selection = {
        "dataset": "driveloop-ngsim-mini",
        "version": "0.1.0",
        "source": "NGSIM US-101 07:50–08:05",
        "license": "CC-BY-SA-3.0",
        "clips": [],
    }

    def build(clip_id: str, ego_id: int, center: int, events: list[dict], note: str):
        start = center - 20
        g = by_vid[ego_id]
        g = g[(g.frame >= start) & (g.frame < start + 50)]
        if len(g) != 50:
            raise ValueError(f"{clip_id}: ego {ego_id} 只有 {len(g)} 帧")
        rows = []
        for _, r in g.iterrows():
            rows.append(r.to_dict())
        # 每帧所有目标；converter 会按 70m 截断。
        all_rows = df[(df.frame >= start) & (df.frame < start + 50)]
        frames = frames_from_rows(all_rows.to_dict("records"), ego_id=str(ego_id), duration_s=4.9, max_objects=16)
        path = out / "clips" / f"{clip_id}.csv"
        write_csv(frames, path)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
        labels.append(
            {
                "clip_id": clip_id,
                "source": "NGSIM US-101",
                "license": "CC-BY-SA-3.0",
                "duration_s": 4.9,
                "label_quality": "silver",
                "events": events,
                "note": note,
            }
        )
        clips.append(
            {
                "clip_id": clip_id,
                "source": "NGSIM US-101",
                "file": f"clips/{clip_id}.csv",
                "sha256_16": digest,
                "frames": len(frames),
                "ego_id": str(ego_id),
                "start_frame": int(start),
            }
        )
        selection["clips"].append(
            {"clip_id": clip_id, "ego_id": ego_id, "center_frame": center, "note": note}
        )

    for clip_id, ego, actor, center, gap in CUTINS:
        # 用实际帧算证据；actor 在 center 帧的纵向差就是 gap。
        g = by_vid[ego]
        row = g[g.frame == center].iloc[0]
        a = by_vid[actor]
        a_prev = a[a.frame == center - 8].iloc[0]
        a_now = a[a.frame == center].iloc[0]
        lat_before = float(a_prev.x) - float(row.x)
        lat_after = float(a_now.x) - float(row.x)
        build(
            clip_id, ego, center,
            [
                {
                    "type": "cut_in",
                    "start_s": 2.0,
                    "end_s": 2.6,
                    "key_s": 2.0,
                    "evidence": {
                        "object_id": str(actor),
                        "dist_m": round(float(gap), 1),
                        "lat_before_m": round(lat_before, 2),
                        "lat_after_m": round(lat_after, 2),
                        "ego_speed_kph": round(float(row.vel) * 1.09728, 1),
                    },
                    "note": "同向相邻车道目标切入 ego 车道，ego 在后方 5–35m",
                }
            ],
            "true same-direction cut-in",
        )

    for clip_id, ego, center in NEGATIVES:
        build(clip_id, ego, center, [], "highway car-following negative")

    (out / "labels.jsonl").write_text(
        "\n".join(json.dumps(x, ensure_ascii=False) for x in labels) + "\n", encoding="utf-8"
    )
    (out / "selection.json").write_text(
        json.dumps(selection, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (out / "manifest.json").write_text(
        json.dumps(
            {
                "dataset": "driveloop-ngsim-mini",
                "license": "CC-BY-SA-3.0",
                "source": "NGSIM US-101",
                "source_url": "https://data.transportation.gov/Automobiles/Next-Generation-Simulation-NGSIM-Vehicle-Trajector/8ect-6jqj",
                "citation": "FHWA, Next Generation Simulation (NGSIM) Vehicle Trajectories and Supporting Data.",
                "clips": clips,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"built {len(clips)} clips -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
