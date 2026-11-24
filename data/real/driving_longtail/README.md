# driveloop real dataset（30 段）

真实驾驶轨迹的小型验证集：**10 段 NGSIM 同向 cut-in + 4 段高速负例 + 8 段 Argoverse 城市 near-miss + 3 段 VRU + 5 段城市负例**。

- 30 段 × 50 帧 × 10Hz，约 2.5MB；
- 21 段正例 / 9 段负例；
- 标签 16 个 `cut_in`（10 严格同向 + 6 路径侵入 proxy）、8 个 `near_miss`、3 个 `vru_sudden`；
- 评测：micro P 0.96 / R 1.00 / F1 0.98；严格 cut-in 子集 P 0.62 / R 1.00 / F1 0.77。

## 文件

```
driving_longtail/
├── clips/           # 30 个 CSV，50 帧/段
├── labels.jsonl     # 30 条 silver label
├── manifest.json    # 来源、许可、sha256_16、帧数
├── selection.json   # 片段清单
├── eval_report.json # 逐 clip 预测与指标
├── eval_report.md   # 指标表
├── DATA_CARD.md     # 数据卡：选择规则、字段映射、限制、许可
└── LICENSE          # 数据许可见下方摘要
```

## 快速看

```bash
python3 scripts/eval_real_dataset.py \
  --data-dir data/real/driving_longtail \
  --out data/real/driving_longtail/eval_report.json \
  --dataset-name driveloop-real-longtail-mini
```

预览图：`docs/assets/real_dataset_preview.png`（cut-in / near-miss / VRU / 负例四联图）。

## 许可

- NGSIM：CC BY-SA 3.0；
- Argoverse 2：CC BY-NC-SA 4.0；
- 本目录派生 CSV 按 **CC BY-NC-SA 4.0** 分发，**禁止商业使用**，再分发需署名并以相同方式共享。
- 原始 NGSIM txt / Argoverse parquet 不入库。

完整说明见 [DATA_CARD.md](DATA_CARD.md)。
