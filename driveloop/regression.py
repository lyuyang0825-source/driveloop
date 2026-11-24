"""回归对比：同一批场景，候选版本相对基线的安全指标变化。

判断顺序：碰撞（致命）→ 最小 TTC → 峰值减速度 → 接管次数。
输出可直接进 CI 的门禁结论：fail 即阻断合入。
"""

from __future__ import annotations

from dataclasses import dataclass, asdict

THRESHOLDS = {"min_ttc": 2.0, "max_decel": -8.0, "interventions_delta": 1}


@dataclass
class Comparison:
    scenario_id: str
    baseline_ttc: float | None
    candidate_ttc: float | None
    baseline_decel: float | None
    candidate_decel: float | None
    baseline_collision: bool
    candidate_collision: bool
    baseline_interventions: int
    candidate_interventions: int
    status: str  # pass / warn / fail
    reasons: list[str]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["ttc_delta"] = (
            round((self.candidate_ttc or 0) - (self.baseline_ttc or 0), 2)
            if self.candidate_ttc is not None and self.baseline_ttc is not None
            else None
        )
        return d


def _index(data: dict) -> dict[str, dict]:
    return {s["id"]: s for s in data.get("scenarios", [])}


def compare_runs(baseline: dict, candidate: dict) -> list[Comparison]:
    base = _index(baseline)
    cand = _index(candidate)
    ids = sorted(set(base) | set(cand))
    out: list[Comparison] = []
    for sid in ids:
        b = base.get(sid, {})
        c = cand.get(sid, {})
        b_dec = b.get("max_decel")
        b_ttc = b.get("min_ttc")
        c_ttc = c.get("min_ttc")
        c_dec = c.get("max_decel")
        reasons: list[str] = []
        status = "pass"

        if c.get("collision") and not b.get("collision"):
            status = "fail"
            reasons.append("候选版本出现新碰撞")
        elif c.get("collision"):
            status = "fail"
            reasons.append("候选版本仍存在碰撞")

        if c_ttc is not None and c_ttc < THRESHOLDS["min_ttc"]:
            status = "fail" if status != "fail" else status
            reasons.append(f"最小 TTC {c_ttc}s 低于阈值 {THRESHOLDS['min_ttc']}s")
        elif b_ttc is not None and c_ttc is not None and c_ttc < b_ttc - 0.35:
            status = "fail" if status != "fail" else status
            reasons.append(f"最小 TTC 较基线下降 {round(b_ttc - c_ttc, 2)}s")

        if c_dec is not None and c_dec < THRESHOLDS["max_decel"]:
            status = "fail" if status != "fail" else status
            reasons.append(f"峰值减速度 {c_dec}m/s² 超过 {THRESHOLDS['max_decel']}m/s²")

        b_int = int(b.get("interventions", 0))
        c_int = int(c.get("interventions", 0))
        if c_int > b_int + THRESHOLDS["interventions_delta"]:
            if status != "fail":
                status = "warn"
            reasons.append(f"接管次数由 {b_int} 增至 {c_int}")

        if not reasons:
            reasons.append("指标不劣于基线")
        out.append(
            Comparison(
                scenario_id=sid,
                baseline_ttc=b_ttc,
                candidate_ttc=c_ttc,
                baseline_decel=b_dec,
                candidate_decel=c_dec,
                baseline_collision=bool(b.get("collision")),
                candidate_collision=bool(c.get("collision")),
                baseline_interventions=b_int,
                candidate_interventions=c_int,
                status=status,
                reasons=reasons,
            )
        )
    return out


def gate(comparisons: list[Comparison]) -> dict:
    fails = [c for c in comparisons if c.status == "fail"]
    warns = [c for c in comparisons if c.status == "warn"]
    return {
        "decision": "block" if fails else ("review" if warns else "pass"),
        "fail": len(fails),
        "warn": len(warns),
        "pass": sum(1 for c in comparisons if c.status == "pass"),
        "failed_ids": [c.scenario_id for c in fails],
    }
