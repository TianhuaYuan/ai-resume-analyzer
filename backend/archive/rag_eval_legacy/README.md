# RAG 初始评估体系（已过时）

## 📊 概述

基于虚构简历（陈明）的初始 RAG 评估体系，用于建立基线和识别坏案例。

**注意**：此评估体系基于虚构数据，已过时。

## 📁 目录结构

```
rag_eval_legacy/
├── README.md                      ← 本文件
├── __init__.py                    ← 包标识
├── evaluate.py                    ← 评估脚本（可复用）
├── run_baseline.py                ← 基线脚本
├── visualize.py                   ← 可视化脚本
├── badcase_ledger.md              ← 坏案例记录（有价值的参考）
│
└── archive/                       ← 旧数据（基于虚构简历）
    ├── golden_set.json            ← 陈明简历的 QA 数据
    ├── baseline_results.json      ← 基线结果
    └── baseline_charts.png        ← 基线图表
```

## 🔧 评估脚本

### evaluate.py
- 支持全链路评估（retrieval + generation）
- 支持仅检索评估（retrieval only）
- 计算 Recall@K / MRR / Precision@K / 拒答准确率

### run_baseline.py
- 跑一次基线评估
- 生成 baseline_results.json

### visualize.py
- 生成评估结果可视化图表

## 🚀 使用方法

```bash
cd backend

# 全链路评估
python -m rag_eval_legacy.evaluate --mode full

# 仅检索评估
python -m rag_eval_legacy.evaluate --mode retrieval

# 指定简历 ID
python -m rag_eval_legacy.evaluate --resume-id 1

# 跑基线
python -m rag_eval_legacy.run_baseline
```

## ⚠️ 注意事项

1. **数据已过时**：`archive/golden_set.json` 基于虚构简历（陈明），不适用于当前项目
2. **脚本可复用**：`evaluate.py`、`run_baseline.py`、`visualize.py` 的评估逻辑可复用
3. **坏案例记录**：`badcase_ledger.md` 记录了有价值的坏案例分析，可参考
