# 数据卡：driveloop-real-longtail-mini

版本 `0.2.0` · 30 段 · 30 × 50 帧 · 10Hz · 约 2.5MB

这是一份**真实轨迹的小型验证集**，用来回答一个问题：driveloop 的规则检测器放到真实驾驶数据上，能不能把 cut-in、near-miss、VRU 挖出来，同时不把正常跟驰误报成事件。

它**不是**感知算法 benchmark，也**不是**安全认证数据集。30 段只够做接入验证和面试讲解，不够做统计显著性结论。

## 1. 数据构成

| 来源 | 片段数 | 内容 | 许可 |
|---|---:|---|---|
| NGSIM US-101（07:50–08:05） | 14 | 10 段严格同向 cut-in + 4 段高速跟驰负例 | CC BY-SA 3.0 |
| Argoverse 2 Motion Forecasting | 16 | 8 段 AV 城市 near-miss + 3 段 VRU + 5 段城市负例 | CC BY-NC-SA 4.0 |
| **合计** | **30** | 21 段正例 / 9 段负例 | 组合后按 **CC BY-NC-SA 4.0** 分发 |

NGSIM 原始文件为 1,180,598 行、2,169 辆车、15 分钟、10Hz。Argoverse 每个 scenario 名义 11 秒，但 `observed=True` 只有前 50 个 timestep，也就是 5 秒历史；所以本数据集全部 clip 都是 5 秒左右、50 帧，不是 9 秒。

## 2. 为什么选这两个源

- **NGSIM 补“真同向 cut-in”**：高速实车轨迹，有 `Local_X/Local_Y`、`Lane_ID`、`v_Vel/v_Acc`，能直接构造“旁车从相邻车道进入自车路径、自车在后方 5–35m”的正例。
- **Argoverse 补“AV 视角”**：Argoverse 2 的 `AV` track 是自动驾驶车，城市道路，有行人和骑行者，能补 near-miss 与 VRU。
- **没有选 nuScenes mini 做主体**：官方包约 4.17GB，实测约 90KB/s，完整下载要十几小时；对 30 段验证集不划算。
- **没有把 Argoverse 的 cut-in 当严格 cut-in**：Argoverse AV 日志里大量“进入路径”的目标其实是交叉口横穿、对向车或跨多车道目标。人工抽检后，只把其中 6 个标成 `path_intrusion_proxy`，不冒充同向变道。

## 3. 片段选择规则

### NGSIM 的 10 段 cut-in

在全部 1,180,598 行上扫描，满足以下条件的 ego/actor 对：

1. ego 在事件前后各有至少 20/29 帧，5 秒窗口连续；
2. actor 在事件前 0.8s 的横向偏移绝对值在 1.8–6.5m；
3. actor 在事件帧的横向偏移绝对值小于 1.6m；
4. actor 在 ego 正前方 4–36m；
5. 0.8s 内横向靠近量大于 0.6m，且方向一致；
6. ego 速度大于 25ft/s（约 27km/h）。

按横向靠近量排序，取 10 个不同 ego。事件帧的 actor 距离为 26.7–34.2m，ego 速度为 36.8–60.9km/h。

> 注：NGSIM 的 `Lane_ID` 在部分车辆上有跳变/滞后，所以标签证据用**横向偏移** `lat_before_m` / `lat_after_m`，不用 `Lane_ID` 差一作为判据。

### Argoverse 的 8 + 3 + 5

- **near-miss**：目标在 ego 路径内，TTC < 3.0s，距离 35m 内；取检测器报告里 TTC 最小的 8 段；
- **vru_sudden**：行人/骑行者进入 ego 路径且距离 < 20m；取 3 段；
- **负例**：正常跟车/直行，无任何标注事件；取 5 段城市负例。

## 4. 字段映射

统一写到 `driveloop/schema.py` 的 15 列 CSV。核心映射：

| 目标字段 | NGSIM | Argoverse 2 |
|---|---|---|
| `speed_kph` | `v_Vel` ft/s × 1.09728 | 位置差分后平滑，m/s × 3.6 |
| `accel_long` | `v_Acc` ft/s² × 0.3048 | 速度差分后平滑 |
| `brake` / `throttle` | `clamp(-a/8)` / `clamp(a/5)` | 同左 |
| `lane_id` | `Lane_ID` | 固定 0（无地图） |
| `lane_offset` | 同帧同车道横向中位数差值 | 固定 0 |
| `objects[].lat_m` | `Local_X` 差 | ego 坐标系横向投影 |
| `objects[].in_path` | `|lat|<1.8m` 且前方 0–70m | `|lat|<1.8m` 且前方 0–80m |
| `weather` / `visibility_m` | `clear` / 10000 | `clear` / 10000 |
| `road_type` / `speed_limit_kph` | `highway` / 105 | `urban` / 50 |
| `driver_state` | `engaged` | `engaged` |

两源都**没有 CAN 踏板、没有高精地图、没有车道中心线真值**；`brake/throttle/lane_offset/限速` 是反推或默认值，不能当成实车信号真值。

## 5. 标签

| 类型 | 标签数 | 语义 |
|---|---:|---|
| `cut_in` | 16 | 10 个 `same_direction_cut_in`（NGSIM）+ 6 个 `path_intrusion_proxy`（Argoverse） |
| `near_miss` | 8 | TTC < 3.0s；3–4s 只算 warning，不算正例 |
| `vru_sudden` | 3 | 行人/两轮车进入路径 20m 内 |
| 负例 | 9 段 | 无事件 |

标签质量是 **silver**：轨迹规则生成 + 人工抽检，不是逐帧人工金标。`label_quality` 字段已写入每一行。

### 语义审计（重要）

16 个 `cut_in` 里只有 10 个是严格“同向相邻车道切入”。另外 6 个来自 Argoverse，人工看轨迹是横穿/对向/跨多车道目标进入路径，标成 `path_intrusion_proxy`。

所以：

- **检测器口径**（路径侵入）下，`cut_in` 16/16，P/R/F1 = 1.00；
- **严格同向变道口径**下，support 10，TP 10，FP 6（6 个 proxy 片段上的 cut_in 预测），precision 0.62，recall 1.00，F1 0.77。

面试里不要把 16/16 说成“变道识别精度 100%”。正确的说法是：“路径侵入召回 100%；严格同向变道只有 10 个正例，另外 6 个暴露了没有车道方向/地图时的语义混淆。”

## 6. 评测结果

在 30 段上跑 `scripts/eval_real_dataset.py`：

| 类型 | 支持数 | TP | FP | FN | Precision | Recall | F1 |
|---|---:|---:|---:|---:|---:|---:|---:|
| cut_in（含 proxy） | 16 | 16 | 0 | 0 | 1.00 | 1.00 | 1.00 |
| near_miss | 8 | 8 | 1 | 0 | 0.89 | 1.00 | 0.94 |
| vru_sudden | 3 | 3 | 0 | 0 | 1.00 | 1.00 | 1.00 |

- 微平均：precision 0.96 / recall 1.00 / F1 0.98；
- 严格 cut-in：precision 0.62 / recall 1.00 / F1 0.77；
- TTC 3–4s warning：0；
- 9 段负例误报：0；
- 唯一一个 `near_miss` FP 在 `av2_0017_vru` 的 4.2s，同一目标同时被报 cut_in，属于 VRU 片段尾部的边界事件。

**这些数字是 silver label 上的一致性回归，不是独立泛化指标。** 标签由轨迹规则生成，检测器也按轨迹规则判定，存在同源循环；它的价值是证明“真实数据能跑通、负例不炸”，不是证明模型泛化。

## 7. 覆盖与缺口

| 类型 | 真实集 | 说明 |
|---|---|---|
| `cut_in` | 10 严格 + 6 proxy | 严格正例只来自 NGSIM 高速 |
| `near_miss` | 8 | Argoverse 城市 AV |
| `vru_sudden` | 3 | Argoverse 行人/骑行者 |
| `hard_brake` | 0 | NGSIM `v_Acc` 最大减速度约 -3.4m/s²，达不到 -6m/s² 阈值 |
| `takeover` | 0 | 公开轨迹没有接管状态 |
| `low_visibility` | 0 | 无天气/能见度真值 |
| `construction` | 0 | 无路型/施工真值 |

因此不能说“真实数据覆盖八类”。`hard_brake/takeover/low_visibility/construction` 仍由合成 demo 覆盖。

## 8. 已知限制

1. **30 段太小**：只能做接入验证，不能做置信区间或显著性检验。
2. **5 秒太短**：看不到长时交互、连续变道和完整博弈。
3. **没有地图/车道方向**：`cut_in` 无法区分同向变道、横穿、对向；这是 6 个 proxy 的根因。
4. **NGSIM 车道 ID 有噪声**：部分帧 `Lane_ID` 跳变但横向位置未变；本项目改用横向几何判定。
5. **NGSIM 只有机动车**：没有行人/骑行者，VRU 全靠 Argoverse。
6. **Argoverse 是 AV 日志**：AV 行为偏保守，cut-in 密度和人类驾驶不同。
7. **没有 CAN**：`brake/throttle` 是加速度反推，不是踏板真值；`lane_offset` 是估计值。
8. **限速/路型是默认值**：NGSIM 统一 105km/h，Argoverse 统一 50km/h，不能用于超速评测。
9. **轨迹有噪声**：NGSIM `v_Acc` 分辨率粗，Argoverse 位置差分在停车/边界处会有抖动。
10. **不是安全结论**：规则检测器的风险分只用于排序和派活，不构成安全认证。

## 9. 许可与引用

- 代码：MIT（见仓库根 `LICENSE`）。
- NGSIM：CC BY-SA 3.0。来源：FHWA / USDOT，[数据页](https://data.transportation.gov/Automobiles/Next-Generation-Simulation-NGSIM-Vehicle-Trajector/8ect-6jqj)。
- Argoverse 2：CC BY-NC-SA 4.0。来源：[argoverse.org/av2.html](https://www.argoverse.org/av2.html)。
- 本目录的派生 CSV 同时包含两源，按最严格的 **CC BY-NC-SA 4.0** 分发；**不得用于商业用途**，再分发需保留署名与相同方式共享。
- 原始 NGSIM txt / Argoverse parquet **不进入 Git**；仓库只保留转换后的 30 段 CSV。

引用：

> Wilson et al., Argoverse 2: Next Generation Datasets for Self-Driving Perception and Forecasting, NeurIPS 2021 Datasets and Benchmarks.

> FHWA, Next Generation Simulation (NGSIM) Vehicle Trajectories and Supporting Data.

## 10. 复现

```bash
# 构建脚本依赖 pandas：pip install pandas
# 1) NGSIM：下载 US-101 15 分钟轨迹，解压到 /tmp/ngsim/
python3 scripts/build_ngsim_dataset.py --raw /tmp/ngsim/trajectories-0750am-0805am.txt

# 2) Argoverse：按 data/real/argoverse/selection.json 从 S3 拉取并转换
python3 scripts/build_real_dataset.py

# 3) 拼成 30 段统一评测集
python3 scripts/assemble_real_dataset.py

# 4) 评测
python3 scripts/eval_real_dataset.py \
  --data-dir data/real/driving_longtail \
  --out data/real/driving_longtail/eval_report.json \
  --dataset-name driveloop-real-longtail-mini
```

`manifest.json` 里有每段 CSV 的 `sha256_16`、来源、许可和帧数，可直接做完整性校验。

## 11. 隐私与伦理

- 两源都是公开研究数据；不含人脸、车牌、姓名、联系方式。
- 不包含用户位置、行程或任何个人数据。
- 只用公开道路轨迹，不涉及测绘资质或数据出境。
- 不得用于商业用途；不得把本数据集的指标包装成安全认证或量产结论。
