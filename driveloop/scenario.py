"""场景卡与 OpenSCENARIO 骨架导出。

场景卡是给“人”看的：为什么危险、关键帧在哪、该标什么、回归要断言什么。
OSC 是给“仿真”看的：把触发条件落成可执行的最小骨架（地图/路线需按项目绑定）。
"""

from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

from .detect import Scene, TYPE_LABELS

LABELS = {
    "near_miss": ["目标类别", "相对距离", "相对速度", "TTC", "是否在规划路径内"],
    "cut_in": ["切入起始帧", "横向速度", "车道归属", "是否打灯", "切入后 TTC"],
    "vru_sudden": ["行人类别", "遮挡情况", "进入路径时间", "横向速度", "运动意图"],
    "hard_brake": ["制动触发原因", "峰值减速度", "制动距离", "后车距离"],
    "takeover": ["接管原因", "接管时刻", "系统状态", "驾驶员动作"],
    "low_visibility": ["天气", "能见度", "传感器置信度", "灯光状态"],
    "construction": ["锥桶/围挡", "临时限速", "车道线缺失", "施工人员"],
    "speed_over": ["限速牌", "超速幅度", "路段类型"],
}

ASSERTIONS = {
    "near_miss": ["最小 TTC ≥ 2.0s", "全程无碰撞", "峰值减速度不超过 8m/s²"],
    "cut_in": ["切入后 1.5s 内横向跟踪误差 < 0.5m", "TTC ≥ 2.0s 或已完成避让"],
    "vru_sudden": ["目标进入路径 0.3s 内被检出", "30m 内开始减速", "无碰撞"],
    "hard_brake": ["制动响应延迟 < 0.3s", "制动距离不超过标定值", "后车 TTC ≥ 1.5s"],
    "takeover": ["接管提示提前 ≥ 2s", "交接后 1s 内横向抖动 < 0.2m"],
    "low_visibility": ["能见度 30m 下 AEB 仍触发", "误检率不超过基线"],
    "construction": ["识别临时限速", "锥桶区域不越界"],
    "speed_over": ["限速识别误差 ≤ 5km/h", "主动降速至限速 +5km/h 内"],
}

TYPE_PRIORITY_SCORE = {}


def build_card(scene: Scene) -> dict:
    primary_event = max(scene.events, key=lambda e: e.score)
    return {
        "scenario_id": scene.id,
        "title": f"{TYPE_LABELS.get(scene.primary, scene.primary)}｜{scene.start:.1f}–{scene.end:.1f}s",
        "primary": scene.primary,
        "types": scene.types,
        "time_window": [scene.start, scene.end],
        "key_frame_t": scene.key_t,
        "risk": scene.risk,
        "severity": scene.severity,
        "trigger": {
            "event": primary_event.type,
            "detail": primary_event.detail,
            "events": [{"type": e.type, "t": e.start, "detail": e.detail} for e in scene.events],
        },
        "odd": scene.odd,
        "ego_speed_kph": scene.ego_speed_kph,
        "metrics": {
            "min_ttc_s": scene.min_ttc,
            "max_decel_mps2": scene.max_decel,
            "duration_s": round(scene.end - scene.start, 1),
        },
        "involved": scene.involved,
        "suggested_labels": sorted({x for t in scene.types for x in LABELS.get(t, [])}),
        "regression_assertions": [a for t in scene.types for a in ASSERTIONS.get(t, [])],
        "replay": {"start_s": scene.start, "end_s": scene.end},
    }


def build_cards(scenes: list[Scene]) -> list[dict]:
    return [build_card(s) for s in scenes]


def to_markdown(cards: list[dict]) -> str:
    lines = ["# 场景卡清单", ""]
    for c in cards:
        lines.append(f"## {c['scenario_id']} · {c['title']}")
        lines.append("")
        lines.append(
            f"- 风险：{c['risk']}/100（{c['severity']}）｜自车 {c['ego_speed_kph']}km/h｜"
            f"TTC {c['metrics']['min_ttc_s']}s｜峰值减速度 {c['metrics']['max_decel_mps2']}m/s²"
        )
        lines.append(
            f"- ODD：{c['odd']['weather']}／能见度 {c['odd']['visibility_m']}m／"
            f"{c['odd']['road_type']}／限速 {c['odd']['speed_limit_kph']}km/h"
        )
        lines.append(f"- 触发：{c['trigger']['event']} {c['trigger']['detail']}")
        lines.append(f"- 建议标注：{'、'.join(c['suggested_labels'])}")
        lines.append(f"- 回归断言：{'；'.join(c['regression_assertions'])}")
        lines.append("")
    return "\n".join(lines)


OSC_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<!-- 由 driveloop 自动生成：最小可执行骨架，roadId / laneId / 路线需按项目地图绑定 -->
<OpenSCENARIO>
  <FileHeader revMajor="1" revMinor="2" date="{date}" description="{title}" author="driveloop"/>
  <RoadNetwork>
    <LogicFile file="map.xodr"/>
  </RoadNetwork>
  <Entities>
    <ScenarioObject name="Ego">
      <Vehicle name="ego" vehicleCategory="car">
        <BoundingRectangle length="4.8" width="1.9" height="1.6"/>
        <Performance maxSpeed="60" maxAcceleration="4" maxDeceleration="9"/>
        <Axles><FrontAxle maxSteering="0.5" wheelDiameter="0.6" trackWidth="1.6" positionX="1.4" positionZ="0.3"/></Axles>
      </Vehicle>
    </ScenarioObject>
    <ScenarioObject name="Target">
      <Vehicle name="target" vehicleCategory="car">
        <BoundingRectangle length="4.5" width="1.8" height="1.5"/>
      </Vehicle>
    </ScenarioObject>
  </Entities>
  <Storyboard>
    <Init>
      <Actions>
        <PrivateAction>
          <TeleportAction>
            <Position><LanePosition roadId="1" laneId="{lane}" s="0"/></Position>
          </TeleportAction>
        </PrivateAction>
        <PrivateAction>
          <SpeedAction>
            <SpeedActionDynamics dynamicsShape="step" value="0"/>
            <SpeedTargetValueType value="absolute"/>
            <TargetAbsolute><Value value="{ego_speed}"/></TargetAbsolute>
          </SpeedAction>
        </PrivateAction>
      </Actions>
    </Init>
    <Story name="{title}">
      <Act name="Act">
        <ManeuverGroup name="TargetBehavior" maximumExecutionCount="1">
          <Actors><EntityRef entityRef="Target"/></Actors>
          <Maneuver name="Maneuver">
            <Event name="TriggerEvent" priority="override">
              <Action>
                <PrivateAction>
                  <LongitudinalDistanceAction continuous="false" distance="{distance}" freespace="true" entityRef="Ego">
                    <DynamicConstraints maxAcceleration="3" maxDeceleration="6" maxSpeed="20"/>
                  </LongitudinalDistanceAction>
                </PrivateAction>
              </Action>
              <StartTrigger>
                <ConditionGroup>
                  <Condition name="Start" delay="0" conditionEdge="rising">
                    <ByValueCondition>
                      <SimulationTimeCondition value="{start_s}" rule="greaterThan"/>
                    </ByValueCondition>
                  </Condition>
                </ConditionGroup>
              </StartTrigger>
            </Event>
          </Maneuver>
        </ManeuverGroup>
        <StartTrigger><ConditionGroup><Condition name="ActStart" delay="0" conditionEdge="rising">
          <ByValueCondition><SimulationTimeCondition value="0" rule="greaterThan"/></ByValueCondition>
        </Condition></ConditionGroup></StartTrigger>
        <StopTrigger><ConditionGroup><Condition name="ActStop" delay="0" conditionEdge="rising">
          <ByValueCondition><SimulationTimeCondition value="{end_s}" rule="greaterThan"/></ByValueCondition>
        </Condition></ConditionGroup></StopTrigger>
      </Act>
      <StopTrigger/>
    </Story>
    <StopTrigger>
      <ConditionGroup><Condition name="End" delay="0" conditionEdge="rising">
        <ByValueCondition><SimulationTimeCondition value="{end_s}" rule="greaterThan"/></ByValueCondition>
      </Condition></ConditionGroup>
    </StopTrigger>
  </Storyboard>
</OpenSCENARIO>
"""


def to_osc(card: dict, lane: int = -1, distance: float = 15.0) -> str:
    detail = card["trigger"]["detail"]
    dist = float(detail.get("dist_m", distance))
    return OSC_TEMPLATE.format(
        date="2026-11-24T10:00:00",
        title=escape(card["title"]),
        lane=lane,
        ego_speed=card["ego_speed_kph"] / 3.6,
        distance=round(dist, 1),
        start_s=card["replay"]["start_s"],
        end_s=card["replay"]["end_s"],
    )


def write_osc(cards: list[dict], out_dir: str | Path) -> list[Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for card in cards:
        p = out / f"{card['scenario_id']}.xosc"
        p.write_text(to_osc(card), encoding="utf-8")
        paths.append(p)
    return paths
