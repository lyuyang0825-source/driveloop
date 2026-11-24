from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

from .detect import TYPE_LABELS, cluster_scenes, detect_events
from .regression import compare_runs, gate
from .report import render_html
from .scenario import build_cards, to_markdown, write_osc
from .schema import load_csv
from .synth import generate

DEFAULT_LOG = "data/logs/urban_90s.csv"


def mine(log_path: str | Path, out_dir: str | Path, engine: str = "rule-v1") -> dict:
    frames = load_csv(log_path)
    events = detect_events(frames)
    scenes = cluster_scenes(events, frames)
    cards = build_cards(scenes)

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "scenarios.json").write_text(
        json.dumps(cards, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out / "scenarios.md").write_text(to_markdown(cards), encoding="utf-8")
    write_osc(cards, out / "osc")

    with (out / "scenarios.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "types", "start_s", "end_s", "risk", "severity", "min_ttc_s", "max_decel", "weather", "road"])
        for c in cards:
            writer.writerow(
                [
                    c["scenario_id"],
                    "+".join(c["types"]),
                    c["time_window"][0],
                    c["time_window"][1],
                    c["risk"],
                    c["severity"],
                    c["metrics"]["min_ttc_s"],
                    c["metrics"]["max_decel_mps2"],
                    c["odd"]["weather"],
                    c["odd"]["road_type"],
                ]
            )

    meta = {
        "log": Path(log_path).name,
        "frames": len(frames),
        "duration": frames[-1].t if frames else 0,
        "engine": engine,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    (out / "report.html").write_text(render_html(cards, None, meta), encoding="utf-8")
    return {"cards": cards, "events": [e.to_dict() for e in events], "meta": meta}


def _demo_runs(cards: list[dict]) -> tuple[dict, dict]:
    baseline = {"run": "baseline-v1", "scenarios": []}
    candidate = {"run": "candidate-v2", "scenarios": []}
    for i, c in enumerate(cards):
        b_ttc = c["metrics"]["min_ttc_s"] if c["metrics"]["min_ttc_s"] is not None else 3.5
        b_dec = c["metrics"]["max_decel_mps2"] if c["metrics"]["max_decel_mps2"] is not None else -3.0
        baseline["scenarios"].append(
            {"id": c["scenario_id"], "min_ttc": b_ttc, "max_decel": b_dec, "collision": False, "interventions": 0}
        )
        if i == 0:
            candidate["scenarios"].append(
                {"id": c["scenario_id"], "min_ttc": 1.4, "max_decel": -8.6, "collision": True, "interventions": 1}
            )
        elif i == 1:
            candidate["scenarios"].append(
                {"id": c["scenario_id"], "min_ttc": 1.7, "max_decel": -7.8, "collision": False, "interventions": 1}
            )
        else:
            candidate["scenarios"].append(
                {"id": c["scenario_id"], "min_ttc": max(2.05, round(b_ttc - 0.05, 2)), "max_decel": max(round(b_dec - 0.2, 2), -7.9), "collision": False, "interventions": 0}
            )
    return baseline, candidate


def run_demo(out_dir: str = "demo_out") -> dict:
    log = Path(DEFAULT_LOG)
    generate(log.parent)
    result = mine(log, out_dir)
    cards = result["cards"]

    baseline, candidate = _demo_runs(cards)
    (Path("data/runs")).mkdir(parents=True, exist_ok=True)
    (Path("data/runs/baseline_v1.json")).write_text(json.dumps(baseline, ensure_ascii=False, indent=2), encoding="utf-8")
    (Path("data/runs/candidate_v2.json")).write_text(json.dumps(candidate, ensure_ascii=False, indent=2), encoding="utf-8")

    comparisons = compare_runs(baseline, candidate)
    gate_result = gate(comparisons)
    (Path(out_dir) / "regression.json").write_text(
        json.dumps({"gate": gate_result, "comparisons": [c.to_dict() for c in comparisons]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (Path(out_dir) / "report.html").write_text(
        render_html(cards, comparisons, result["meta"]), encoding="utf-8"
    )
    return {"result": result, "comparisons": comparisons, "gate": gate_result}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="长尾场景挖掘与回归")
    parser.add_argument("--generate", metavar="OUT_DIR", help="生成合成日志")
    parser.add_argument("--mine", metavar="LOG_CSV", help="挖掘单份日志")
    parser.add_argument("--out-dir", default="demo_out")
    parser.add_argument("--regress", nargs=2, metavar=("BASELINE", "CANDIDATE"), help="对比两份指标 JSON")
    parser.add_argument("--demo", action="store_true")
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    if args.generate:
        p = generate(args.generate)
        print(f"[driveloop] 合成日志: {p}")
        return 0

    if args.regress:
        base = json.loads(Path(args.regress[0]).read_text(encoding="utf-8"))
        cand = json.loads(Path(args.regress[1]).read_text(encoding="utf-8"))
        comps = compare_runs(base, cand)
        result = {"gate": gate(comps), "comparisons": [c.to_dict() for c in comps]}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["gate"]["decision"] == "pass" else 2

    if args.mine:
        result = mine(args.mine, args.out_dir)
        cards = result["cards"]
        print(f"[driveloop] {len(cards)} 个场景，输出 {args.out_dir}")
        for c in cards:
            print(
                f"  {c['scenario_id']} {TYPE_LABELS.get(c['primary'], c['primary'])} "
                f"{c['time_window'][0]:.1f}-{c['time_window'][1]:.1f}s risk={c['risk']} "
                f"ttc={c['metrics']['min_ttc_s']} decel={c['metrics']['max_decel_mps2']}"
            )
        return 0

    if args.demo:
        result = run_demo(args.out_dir)
        cards = result["result"]["cards"]
        print(f"[driveloop] 场景 {len(cards)} 个，输出 {args.out_dir}")
        for c in cards:
            print(
                f"  {c['scenario_id']} {TYPE_LABELS.get(c['primary'], c['primary'])} "
                f"{c['time_window'][0]:.1f}-{c['time_window'][1]:.1f}s risk={c['risk']} "
                f"ttc={c['metrics']['min_ttc_s']} decel={c['metrics']['max_decel_mps2']}"
            )
        print(f"[driveloop] 回归门禁: {result['gate']['decision']} (fail {result['gate']['fail']})")
        return 0

    parser.error("请使用 --demo / --generate / --mine / --regress")


if __name__ == "__main__":
    sys.exit(main())
