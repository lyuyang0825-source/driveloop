#!/usr/bin/env python3
"""把一份 Argoverse 2 motion-forecasting parquet 转成 driveloop CSV。

用法:
  python3 scripts/import_argoverse.py \
    --parquet /tmp/scenario_xxx.parquet \
    --out data/real/argoverse/clips/av2_0001.csv
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from driveloop.argoverse import frames_from_rows
from driveloop.schema import write_csv


def read_parquet(path: Path) -> list[dict]:
    try:
        import pandas as pd
    except ImportError as e:
        raise SystemExit("需要 pandas + pyarrow: pip install pandas pyarrow") from e
    df = pd.read_parquet(path)
    rows = df.to_dict("records")
    # 统一成标准库类型，避免 numpy 标量进入 schema。
    out = []
    for r in rows:
        out.append(
            {
                "track_id": str(r["track_id"]),
                "object_type": str(r["object_type"]),
                "timestep": int(r["timestep"]),
                "position_x": float(r["position_x"]),
                "position_y": float(r["position_y"]),
                "heading": float(r["heading"]),
                "velocity_x": float(r.get("velocity_x", 0.0)),
                "velocity_y": float(r.get("velocity_y", 0.0)),
                "observed": bool(r.get("observed", True)),
                "focal_track_id": str(r.get("focal_track_id", "")),
            }
        )
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--parquet", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--duration", type=float, default=5.0)
    p.add_argument("--ego-id", default="AV")
    args = p.parse_args(argv)

    frames = frames_from_rows(read_parquet(Path(args.parquet)), ego_id=args.ego_id, duration_s=args.duration)
    out = write_csv(frames, Path(args.out))
    print(f"[argoverse] {len(frames)} 帧 -> {out}")
    print(f"[argoverse] ego 速度 {frames[0].speed_kph:.1f} -> {frames[-1].speed_kph:.1f} km/h")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
