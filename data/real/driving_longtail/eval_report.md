# driveloop 真实数据评测

- clips: 30（正例 21 / 负例 9）
- TTC 3–4s warning: 0
- 负例误报 clip: 0

| 类型 | 标签 | 支持数 | TP | FP | FN | Precision | Recall | F1 |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| cut_in | 旁车切入 | 16 | 16 | 0 | 0 | 1.00 | 1.00 | 1.00 |
| near_miss | 近碰撞（低 TTC） | 8 | 8 | 1 | 0 | 0.89 | 1.00 | 0.94 |
| vru_sudden | 行人/两轮车突入 | 3 | 3 | 0 | 0 | 1.00 | 1.00 | 1.00 |

微平均：precision 0.96 / recall 1.00 / F1 0.98。

严格 cut-in 子集（只算 NGSIM 同向切入）：support 10 / TP 10 / FP 6 / FN 0，precision 0.62 / recall 1.00 / F1 0.77。
> 16 个 `cut_in` 标签里只有 10 个是严格同向切入；另外 6 个是 Argoverse 的路径侵入 proxy。

> 标注为 silver label：轨迹参考规则 + 人工抽检，不是逐帧人工金标。
> `hard_brake`、`takeover`、`low_visibility`、`construction` 在这个真实子集里没有样本，
> 仍由合成 demo 覆盖，不能把本表当成八类完整评测。
