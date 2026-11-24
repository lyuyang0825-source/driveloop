# 真实数据目录

- `driving_longtail/`：**最终交付集**，30 段统一 CSV + labels + manifest + data card，用于 README 的评测。
- `argoverse/`：Argoverse 2 源转换结果（30 段），保留用于追溯；其中 14 个 `cut_in` 是路径侵入 proxy，不进入最终严格 cut-in 指标。
- `ngsim/`：NGSIM US-101 源转换结果（14 段），最终集的 cut-in 与高速负例来自这里。

最终评测只看 `driving_longtail/`。原始 parquet/txt 不入库，转换脚本见 `scripts/build_*.py`。
