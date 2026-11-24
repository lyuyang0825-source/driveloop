#!/usr/bin/env python3
"""在 driveloop-argoverse-mini 上跑规则检测器，并输出逐类指标。

标注是 silver label：轨迹参考规则 + 人工抽检，不是逐帧人工金标。
评价只把 TTC < 3.0s 的 near_miss 算正例；TTC 3–4s 作为 warning 单独统计。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from driveloop.detect import TYPE_LABELS, detect_events
from driveloop.schema import load_csv

EVAL_TYPES = ["cut_in", "near_miss", "vru_sudden"]


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def match_events(labels: list[dict], preds: list[dict]) -> tuple[list, list, list]:
    """同类事件一对一匹配；时间重叠或关键点相差 ≤1.5s 算命中。"""
    pairs = []
    for li, lab in enumerate(labels):
        for pi, pred in enumerate(preds):
            if lab["type"] != pred["type"]:
                continue
            ov = _overlap(lab["start_s"], lab["end_s"], pred["start"], pred["end"])
            gap = abs(float(lab.get("key_s", lab["start_s"])) - pred["key_t"])
            if ov > 0 or gap <= 1.5:
                pairs.append((ov, -gap, li, pi))
    pairs.sort(reverse=True)
    used_l, used_p, matched = set(), set(), []
    for _, _, li, pi in pairs:
        if li in used_l or pi in used_p:
            continue
        used_l.add(li)
        used_p.add(pi)
        matched.append((li, pi))
    tp_l = {li for li, _ in matched}
    tp_p = {pi for _, pi in matched}
    fn = [lab for i, lab in enumerate(labels) if i not in tp_l]
    fp = [pred for i, pred in enumerate(preds) if i not in tp_p]
    return matched, fp, fn


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="data/real/argoverse")
    ap.add_argument("--out", default="data/real/argoverse/eval_report.json")
    ap.add_argument("--dataset-name", default=None)
    args = ap.parse_args(argv)

    data = Path(args.data_dir)
    labels = {}
    for line in (data / "labels.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            labels[row["clip_id"]] = row

    per_type = {t: {"tp": 0, "fp": 0, "fn": 0, "support": 0} for t in EVAL_TYPES}
    strict = {"tp": 0, "fp": 0, "fn": 0, "support": 0}
    warnings = 0
    details = []
    neg_fp = 0

    for clip_id in sorted(labels):
        csv_path = data / "clips" / f"{clip_id}.csv"
        frames = load_csv(csv_path)
        raw_preds = detect_events(frames)
        preds = []
        for e in raw_preds:
            item = {"type": e.type, "start": e.start, "end": e.end, "key_t": e.key_t, "detail": e.detail}
            if e.type == "near_miss" and float(e.detail.get("ttc_s", 99)) >= 3.0:
                warnings += 1
                continue
            if e.type in EVAL_TYPES:
                preds.append(item)
        labs = labels[clip_id]["events"]
        for t in EVAL_TYPES:
            per_type[t]["support"] += sum(1 for e in labs if e["type"] == t)
        matched, fp, fn = match_events(labs, preds)
        # 语义审计：只把 NGSIM 的 same_direction_cut_in 算严格 cut-in；
        # Argoverse 的 path_intrusion_proxy 不算严格同类，检测器在那些 clip 上的
        # cut_in 预测在这里记 FP。
        strict_labs = [e for e in labs if e["type"] == "cut_in" and e.get("semantics") == "same_direction_cut_in"]
        cut_preds = [e for e in preds if e["type"] == "cut_in"]
        strict["support"] += len(strict_labs)
        sm, sfp, sfn = match_events(strict_labs, cut_preds)
        strict["tp"] += len(sm)
        strict["fp"] += len(sfp)
        strict["fn"] += len(sfn)
        for t in EVAL_TYPES:
            per_type[t]["tp"] += sum(1 for li, _ in matched if labs[li]["type"] == t)
            per_type[t]["fp"] += sum(1 for e in fp if e["type"] == t)
            per_type[t]["fn"] += sum(1 for e in fn if e["type"] == t)
        if not labs and preds:
            neg_fp += 1
        details.append(
            {
                "clip_id": clip_id,
                "labels": [(e["type"], e["start_s"], e["end_s"]) for e in labs],
                "predicted": [(e["type"], round(e["start"], 1), round(e["end"], 1)) for e in preds],
                "matched": len(matched),
            }
        )

    rows = []
    total = {"tp": 0, "fp": 0, "fn": 0, "support": 0}
    for t in EVAL_TYPES:
        d = per_type[t]
        p = d["tp"] / (d["tp"] + d["fp"]) if d["tp"] + d["fp"] else 0.0
        r = d["tp"] / (d["tp"] + d["fn"]) if d["tp"] + d["fn"] else 0.0
        f = 2 * p * r / (p + r) if p + r else 0.0
        d.update(precision=round(p, 3), recall=round(r, 3), f1=round(f, 3))
        rows.append({"type": t, "label": TYPE_LABELS.get(t, t), **d})
        for k in total:
            total[k] += d[k]
    mp = total["tp"] / (total["tp"] + total["fp"]) if total["tp"] + total["fp"] else 0.0
    mr = total["tp"] / (total["tp"] + total["fn"]) if total["tp"] + total["fn"] else 0.0
    mf = 2 * mp * mr / (mp + mr) if mp + mr else 0.0
    sp = strict["tp"] / (strict["tp"] + strict["fp"]) if strict["tp"] + strict["fp"] else 0.0
    sr = strict["tp"] / (strict["tp"] + strict["fn"]) if strict["tp"] + strict["fn"] else 0.0
    sf1 = 2 * sp * sr / (sp + sr) if sp + sr else 0.0
    strict.update(precision=round(sp, 3), recall=round(sr, 3), f1=round(sf1, 3))
    result = {
        "dataset": args.dataset_name or f"driveloop-{data.name}-mini",
        "clips": len(labels),
        "positive_clips": sum(1 for x in labels.values() if x["events"]),
        "negative_clips": sum(1 for x in labels.values() if not x["events"]),
        "warnings_ttc_3_4s": warnings,
        "negative_clips_with_fp": neg_fp,
        "per_type": rows,
        "strict_cut_in": strict,
        "micro": {
            "tp": total["tp"],
            "fp": total["fp"],
            "fn": total["fn"],
            "support": total["support"],
            "precision": round(mp, 3),
            "recall": round(mr, 3),
            "f1": round(mf, 3),
        },
        "details": details,
        "note": (
            "silver labels；near_miss 只评 TTC<3.0s，3–4s 计 warning；"
            "strict_cut_in 只把 NGSIM same_direction_cut_in 算严格同类，"
            "Argoverse path_intrusion_proxy 上的 cut_in 预测记 FP"
        ),
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    md = [
        "# driveloop 真实数据评测",
        "",
        f"- clips: {result['clips']}（正例 {result['positive_clips']} / 负例 {result['negative_clips']}）",
        f"- TTC 3–4s warning: {warnings}",
        f"- 负例误报 clip: {neg_fp}",
        "",
        "| 类型 | 标签 | 支持数 | TP | FP | FN | Precision | Recall | F1 |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in rows:
        md.append(
            f"| {r['type']} | {r['label']} | {r['support']} | {r['tp']} | {r['fp']} | {r['fn']} | "
            f"{r['precision']:.2f} | {r['recall']:.2f} | {r['f1']:.2f} |"
        )
    md += [
        "",
        f"微平均：precision {mp:.2f} / recall {mr:.2f} / F1 {mf:.2f}。",
        "",
        f"严格 cut-in 子集（只算 NGSIM 同向切入）：support {strict['support']} / TP {strict['tp']} / "
        f"FP {strict['fp']} / FN {strict['fn']}，precision {sp:.2f} / recall {sr:.2f} / F1 {sf1:.2f}。",
        "> 16 个 `cut_in` 标签里只有 10 个是严格同向切入；另外 6 个是 Argoverse 的路径侵入 proxy。",
        "",
        "> 标注为 silver label：轨迹参考规则 + 人工抽检，不是逐帧人工金标。",
        "> `hard_brake`、`takeover`、`low_visibility`、`construction` 在这个真实子集里没有样本，",
        "> 仍由合成 demo 覆盖，不能把本表当成八类完整评测。",
    ]
    (data / "eval_report.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
