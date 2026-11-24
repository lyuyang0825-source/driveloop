"""单文件 HTML 报告：不依赖前端框架，双击即可看。"""

from __future__ import annotations

import html

from .detect import TYPE_LABELS
from .regression import Comparison, gate

SEVERITY_LABEL = {"high": "高危", "medium": "中等", "low": "低"}
SEVERITY_COLOR = {"high": "#ff5c62", "medium": "#ffc46e", "low": "#7adcb4"}
STATUS_COLOR = {"fail": "#ff5c62", "warn": "#ffc46e", "pass": "#7adcb4"}


def _e(x) -> str:
    return html.escape(str(x))


def render_html(cards: list[dict], comparisons: list[Comparison] | None, meta: dict) -> str:
    counts = {"high": 0, "medium": 0, "low": 0}
    for c in cards:
        counts[c["severity"]] += 1

    rows = []
    for c in cards:
        color = SEVERITY_COLOR[c["severity"]]
        rows.append(
            "<tr>"
            f"<td class='mono'>{_e(c['scenario_id'])}</td>"
            f"<td>{_e(TYPE_LABELS.get(c['primary'], c['primary']))}</td>"
            f"<td class='mono'>{c['time_window'][0]:.1f}–{c['time_window'][1]:.1f}s</td>"
            f"<td><span class='tag' style='background:{color}22;color:{color}'>{SEVERITY_LABEL[c['severity']]} {c['risk']}</span></td>"
            f"<td class='mono'>{c['metrics']['min_ttc_s'] if c['metrics']['min_ttc_s'] is not None else '—'}</td>"
            f"<td class='mono'>{c['metrics']['max_decel_mps2'] if c['metrics']['max_decel_mps2'] is not None else '—'}</td>"
            f"<td>{_e(c['odd']['weather'])} / {c['odd']['visibility_m']:.0f}m / {_e(c['odd']['road_type'])}</td>"
            "<td>"
            + "<br>".join(
                _e(e["type"]) + " @" + f"{e['t']:.1f}s" for e in c["trigger"]["events"]
            )
            + "</td>"
            "</tr>"
        )

    detail_blocks = []
    for c in cards:
        detail_blocks.append(
            f"<section class='card'><h3>{_e(c['scenario_id'])} · {_e(c['title'])}</h3>"
            f"<p class='muted'>触发：{_e(c['trigger']['event'])} {_e(c['trigger']['detail'])}"
            f"｜关键帧 {c['key_frame_t']}s｜自车 {c['ego_speed_kph']}km/h</p>"
            f"<p>建议标注：{_e('、'.join(c['suggested_labels']))}</p>"
            f"<p>回归断言：{_e('；'.join(c['regression_assertions']))}</p></section>"
        )

    regression_html = ""
    if comparisons:
        g = gate(comparisons)
        reg_rows = []
        for c in comparisons:
            color = STATUS_COLOR[c.status]
            reg_rows.append(
                "<tr>"
                f"<td class='mono'>{_e(c.scenario_id)}</td>"
                f"<td class='mono'>{c.baseline_ttc if c.baseline_ttc is not None else '—'}</td>"
                f"<td class='mono'>{c.candidate_ttc if c.candidate_ttc is not None else '—'}</td>"
                f"<td class='mono'>{c.baseline_decel if c.baseline_decel is not None else '—'}</td>"
                f"<td class='mono'>{c.candidate_decel if c.candidate_decel is not None else '—'}</td>"
                f"<td class='mono'>{'是' if c.candidate_collision else '否'}</td>"
                f"<td><span class='tag' style='background:{color}22;color:{color}'>{c.status}</span></td>"
                f"<td>{_e('；'.join(c.reasons))}</td>"
                "</tr>"
            )
        regression_html = f"""
<h2>回归门禁</h2>
<p class="muted">结论：<b>{g['decision']}</b>（fail {g['fail']} / warn {g['warn']} / pass {g['pass']}）</p>
<table><thead><tr><th>场景</th><th>基线 TTC</th><th>候选 TTC</th><th>基线减速度</th><th>候选减速度</th><th>碰撞</th><th>状态</th><th>原因</th></tr></thead>
<tbody>{''.join(reg_rows)}</tbody></table>
"""

    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>driveloop 长尾场景报告</title>
<style>
:root{{color-scheme:dark}}
body{{margin:0;padding:40px;background:#0b0b12;color:#e9eaf0;font:15px/1.65 -apple-system,"Noto Sans CJK SC",sans-serif}}
h1{{font-size:26px;margin:0 0 6px}} h2{{margin-top:40px;font-size:19px}} h3{{font-size:16px;margin:0 0 8px}}
.muted{{color:#9aa0b4}} .mono{{font-family:ui-monospace,Menlo,monospace;font-size:13px}}
.wrap{{max-width:1180px;margin:0 auto}}
.kpis{{display:flex;gap:14px;margin:24px 0;flex-wrap:wrap}}
.kpi{{background:#141422;border:1px solid #23233a;border-radius:12px;padding:14px 20px;min-width:120px}}
.kpi b{{display:block;font-size:24px}} .kpi span{{color:#9aa0b4;font-size:12px}}
table{{width:100%;border-collapse:collapse;margin-top:12px;font-size:13px}}
th,td{{text-align:left;padding:10px 12px;border-bottom:1px solid #23233a;vertical-align:top}}
th{{color:#9aa0b4;font-weight:500;font-size:12px;text-transform:uppercase;letter-spacing:.04em}}
.tag{{display:inline-block;padding:2px 9px;border-radius:999px;font-size:12px}}
.card{{background:#12121e;border:1px solid #23233a;border-radius:12px;padding:16px 20px;margin:14px 0}}
.card p{{margin:4px 0}}
footer{{margin-top:48px;color:#6f7488;font-size:12px}}
</style></head><body><div class="wrap">
<h1>driveloop · 长尾场景挖掘报告</h1>
<p class="muted">日志 {_e(meta.get('log', '—'))}｜{meta.get('frames', 0)} 帧 / {meta.get('duration', 0):.0f}s｜
检测器 {_e(meta.get('engine', 'rule-v1'))}｜生成 {_e(meta.get('generated_at', ''))}</p>
<div class="kpis">
  <div class="kpi"><b>{len(cards)}</b><span>场景总数</span></div>
  <div class="kpi"><b style="color:#ff5c62">{counts['high']}</b><span>高危（≥70）</span></div>
  <div class="kpi"><b style="color:#ffc46e">{counts['medium']}</b><span>中等（45–69）</span></div>
  <div class="kpi"><b>{round(100 * len(cards) / max(meta.get('duration', 1), 1), 1)}</b><span>每百秒场景</span></div>
</div>
<h2>场景清单</h2>
<table><thead><tr><th>ID</th><th>主类型</th><th>时间窗</th><th>风险</th><th>TTC(s)</th><th>峰值减速度</th><th>ODD</th><th>事件</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table>
{regression_html}
<h2>场景卡</h2>
{''.join(detail_blocks)}
<footer>规则基线输出，仅用于数据筛选与回归排序；场景卡不构成安全认证结论。合成日志仅用于演示链路。</footer>
</div></body></html>
"""
