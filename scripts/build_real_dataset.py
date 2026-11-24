#!/usr/bin/env python3
"""根据 selection.json 重建 driveloop 真实数据子集。

数据源：Argoverse 2 Motion Forecasting（val/train），CC BY-NC-SA 4.0。
脚本只下载需要用到的 parquet，不把原始传感器数据放进仓库。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from driveloop.argoverse import frames_from_rows
from driveloop.schema import write_csv

BASE = "https://argoverse.s3.amazonaws.com/datasets/av2/motion-forecasting"
LICENSE = "CC-BY-NC-SA-4.0"


def download(url: str, path: Path, retries: int = 3) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(url, timeout=60) as r, path.open("wb") as f:
                f.write(r.read())
            if path.stat().st_size < 10_000 or path.read_bytes()[:4] != b"PAR1":
                raise ValueError("下载内容不是完整 parquet")
            return
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as e:
            if path.exists():
                path.unlink()
            if attempt == retries:
                raise SystemExit(f"下载失败 {url}: {e}")
            time.sleep(1.5 * attempt)


def read_rows(path: Path) -> list[dict]:
    import pandas as pd

    df = pd.read_parquet(path)
    rows = []
    for r in df.to_dict("records"):
        rows.append(
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
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selection", default="data/real/argoverse/selection.json")
    ap.add_argument("--out-dir", default="data/real/argoverse")
    ap.add_argument("--cache", default="/tmp/driveloop-argoverse-cache")
    args = ap.parse_args(argv)

    sel_path = Path(args.selection)
    out_dir = Path(args.out_dir)
    cache = Path(args.cache)
    payload = json.loads(sel_path.read_text(encoding="utf-8"))
    clips = payload["clips"]

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "clips").mkdir(exist_ok=True)
    (out_dir / "selection.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    manifest = {
        "dataset": payload["dataset"],
        "version": payload["version"],
        "license": LICENSE,
        "source": payload["source"],
        "source_url": "https://www.argoverse.org/av2.html",
        "citation": (
            "Wilson et al., Argoverse 2: Next Generation Datasets for Self-Driving "
            "Perception and Forecasting, NeurIPS 2021 Datasets and Benchmarks."
        ),
        "clips": [],
    }
    labels = []

    for c in clips:
        sid = c["scenario_id"]
        split = c["split"]
        local = cache / split / f"scenario_{sid}.parquet"
        if not local.exists():
            url = f"{BASE}/{split}/{sid}/scenario_{sid}.parquet"
            print(f"[fetch] {sid[:8]} {split}")
            download(url, local)
        frames = frames_from_rows(
            read_rows(local),
            ego_id="AV",
            duration_s=float(c["duration_s"]),
            max_objects=24,
        )
        csv_path = out_dir / "clips" / f"{c['clip_id']}.csv"
        write_csv(frames, csv_path)
        digest = hashlib.sha256(csv_path.read_bytes()).hexdigest()[:16]
        labels.append(
            {
                "clip_id": c["clip_id"],
                "scenario_id": sid,
                "city": c["city"],
                "source": "Argoverse 2 Motion Forecasting",
                "split": split,
                "license": LICENSE,
                "duration_s": c["duration_s"],
                "label_quality": "silver",
                "events": c["events"],
                "note": c["note"],
            }
        )
        manifest["clips"].append(
            {
                "clip_id": c["clip_id"],
                "scenario_id": sid,
                "city": c["city"],
                "split": split,
                "file": f"clips/{c['clip_id']}.csv",
                "sha256_16": digest,
                "frames": len(frames),
                "mean_speed_kph": round(sum(f.speed_kph for f in frames) / len(frames), 1),
                "max_objects": max(len(f.objects) for f in frames),
                "event_types": sorted({e["type"] for e in c["events"]}),
            }
        )
        print(f"[ok] {c['clip_id']} {len(frames)} 帧 {list({e['type'] for e in c['events']})}")

    (out_dir / "labels.jsonl").write_text(
        "\n".join(json.dumps(x, ensure_ascii=False) for x in labels) + "\n", encoding="utf-8"
    )
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"[done] {len(clips)} clips -> {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
