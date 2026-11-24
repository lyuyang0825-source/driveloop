#!/usr/bin/env python3
"""把 NGSIM 高速 cut-in 与 Argoverse 城市 AV 场景拼成统一评测集。

最终 30 段：
- NGSIM 10 段同向 cut-in + 4 段高速跟驰负例
- Argoverse 8 段 near-miss + 3 段 VRU + 5 段城市负例

Argoverse 里原来的 cut-in 标签不作为 cut_in 金标：人工抽检发现多数是
交叉口横穿/对向目标进入路径，语义不纯；它们仍留在源目录，供后续做
path_intrusion 专项，不混进本评测。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARG = ROOT / "data/real/argoverse"
NG = ROOT / "data/real/ngsim"

ARG_NEAR = [f"av2_{i:04d}_nearmiss" for i in range(7, 15)]
ARG_VRU = [f"av2_{i:04d}_vru" for i in range(17, 20)]
ARG_NEG = [f"av2_{i:04d}_negative" for i in range(20, 25)]
KEEP_EVENT = {"near_miss": "near_miss", "vru_sudden": "vru_sudden"}


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/real/driving_longtail")
    args = ap.parse_args(argv)
    out = Path(args.out)
    clips_dir = out / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)

    labels: list[dict] = []
    manifest_clips: list[dict] = []

    def add(src: Path, row: dict, keep_types: set[str] | None, semantic: str):
        cid = row["clip_id"]
        shutil.copy2(src / "clips" / f"{cid}.csv", clips_dir / f"{cid}.csv")
        events = []
        for e in row.get("events", []):
            # Argoverse 的 cut_in 保留，但打上 path_intrusion_proxy：
            # 它和检测器的路径侵入定义一致，不等于严格同向变道。
            if e["type"] == "cut_in":
                pass
            elif keep_types is not None and e["type"] not in keep_types:
                continue
            ev = dict(e)
            if e["type"] == "cut_in":
                ev["semantics"] = "path_intrusion_proxy" if "Argoverse" in row["source"] else semantic
            else:
                ev["semantics"] = "primary_event"
            events.append(ev)
        row = dict(row)
        row["events"] = events
        row["semantic_profile"] = semantic
        labels.append(row)
        p = clips_dir / f"{cid}.csv"
        manifest_clips.append(
            {
                "clip_id": cid,
                "source": row["source"],
                "license": row["license"],
                "file": f"clips/{cid}.csv",
                "sha256_16": hashlib.sha256(p.read_bytes()).hexdigest()[:16],
                "frames": 50,
            }
        )

    ng_labels = {r["clip_id"]: r for r in read_jsonl(NG / "labels.jsonl")}
    for cid in sorted(ng_labels):
        add(NG, ng_labels[cid], None, "same_direction_cut_in" if ng_labels[cid]["events"] else "negative")

    arg_labels = {r["clip_id"]: r for r in read_jsonl(ARG / "labels.jsonl")}
    for cid in ARG_NEAR:
        add(ARG, arg_labels[cid], {"near_miss"}, "near_miss")
    for cid in ARG_VRU:
        add(ARG, arg_labels[cid], {"vru_sudden"}, "vru_sudden")
    for cid in ARG_NEG:
        add(ARG, arg_labels[cid], set(), "negative")

    (out / "labels.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in labels) + "\n", encoding="utf-8"
    )
    (out / "manifest.json").write_text(
        json.dumps(
            {
                "dataset": "driveloop-real-longtail-mini",
                "version": "0.2.0",
                "sources": [
                    {
                        "name": "NGSIM US-101",
                        "license": "CC-BY-SA-3.0",
                        "url": "https://data.transportation.gov/Automobiles/Next-Generation-Simulation-NGSIM-Vehicle-Trajector/8ect-6jqj",
                        "role": "同向 cut-in、高速跟驰负例",
                    },
                    {
                        "name": "Argoverse 2 Motion Forecasting",
                        "license": "CC-BY-NC-SA-4.0",
                        "url": "https://www.argoverse.org/av2.html",
                        "role": "AV 城市 near-miss、VRU、负例",
                    },
                ],
                "counts": {
                    "clips": len(labels),
                    "positive": sum(1 for x in labels if x["events"]),
                    "negative": sum(1 for x in labels if not x["events"]),
                },
                "clips": manifest_clips,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (out / "selection.json").write_text(
        json.dumps(
            {
                "near_miss": ARG_NEAR,
                "vru_sudden": ARG_VRU,
                "negative_argoverse": ARG_NEG,
                "cut_in_ngsim": [c for c in sorted(ng_labels) if ng_labels[c]["events"]],
                "negative_ngsim": [c for c in sorted(ng_labels) if not ng_labels[c]["events"]],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"assembled {len(labels)} clips -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
