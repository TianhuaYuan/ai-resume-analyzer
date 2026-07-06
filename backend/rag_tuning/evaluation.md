# RAG 评估与实验体系

## 📊 体系概览

本项目有两套评估体系，分别用于不同目的：

| 体系 | 目录 | 测试数据 | 状态 | 用途 |
|------|------|----------|------|------|
| **初始评估** | `rag_eval_legacy/` | 陈明（虚构） | ⚠️ 已过时 | 建立基线、识别坏案例 |
| **调优实验** | `rag_tuning_results/` + `rag_tuning/` | 袁天华（真实） | ✅ 当前使用 | RAG 参数调优 |

## 🎯 最终结论

**最优配置在 `rag_tuning_results/optimal_config.json`**，关键参数：

| 参数 | 原值 | 最优值 | 变化 | 阶段 |
|------|------|--------|------|------|
| chunk_size | 500 | 1200 | +140% | Phase1 |
| rrf_k | 60 | 100 | +67% | Phase2 |
| rerank_final_top_k | 8 | 5 | -37.5% | Phase3 |
| reject_threshold | 0.5 | 0.3 | -40% | Phase4 |
| temperature | 0.3 | 0.3 | 不变 | Phase5-6 |

**性能提升**：+5.9%（0.5146 → 0.5448）

## 📁 目录结构

```
backend/
├── evaluation.md                      ← 本文件
├── rag_params.py                      ← 参数配置
│
├── rag_tuning/                        ← 实验框架
│   ├── README.md
│   ├── evaluate.py                    ← ✅ 评估框架核心
│   ├── golden_set.json                ← ✅ 测试数据（袁天华简历）
│   ├── run_concurrent.py              ← ✅ 主力并发框架
│   ├── run_phase1_single.py           ← Phase1 单组测试
│   ├── run_phase5_concurrent.py       ← Phase5 并发版
│   └── run_phase5_robust.py           ← Phase5 鲁棒版
│
├── rag_tuning_results/                ← 实验结果
│   ├── README.md
│   ├── optimal_config.json            ← ✅ 最优配置（最终结论）
│   ├── _model_metadata.json           ← 模型元数据
│   ├── summary/                       ← 各阶段汇总
│   │   ├── baseline.json
│   │   ├── phase1.json ~ phase6.json
│   └── archive/                       ← 详细结果（归档）
│       ├── phase1_cs*_details.json
│       ├── phase2_*.json
│       └── phase5/
│
└── rag_eval_legacy/                   ← 初始评估（已过时）
    ├── README.md
    ├── evaluate.py                    ← 评估脚本（可复用）
    ├── run_baseline.py                ← 基线脚本
    ├── visualize.py                   ← 可视化
    ├── badcase_ledger.md              ← 坏案例记录
    └── archive/                       ← 旧数据
        ├── golden_set.json            ← 陈明简历（虚构）
        ├── baseline_results.json
        └── baseline_charts.png
```

## 🚀 快速使用

### 跑完整实验
```bash
cd backend

# Phase 1-6
python rag_tuning/run_concurrent.py --phase 1
python rag_tuning/run_concurrent.py --phase 2
python rag_tuning/run_concurrent.py --phase 3
python rag_tuning/run_concurrent.py --phase 4
python rag_tuning/run_concurrent.py --phase 5
python rag_tuning/run_concurrent.py --phase 6

# 单组参数测试
python rag_tuning/evaluate.py --single chunk_size=1200,overlap=50
```

### 查看结果
```bash
# 最优配置
cat rag_tuning_results/optimal_config.json

# 各阶段汇总
cat rag_tuning_results/summary/phase1.json
```

## 📈 实验阶段详解

### Phase 1: 分块策略
- **测试内容**：chunk_size × overlap
- **测试范围**：4×4 = 16组
- **结论**：chunk_size=1200, overlap=50

### Phase 2: 检索参数
- **测试内容**：rrf_k, hybrid_top_k, rerank_truncation
- **结论**：rrf_k=100, hybrid_top_k=20, truncation=400

### Phase 3: 精排压缩比
- **测试内容**：rerank_input_top_k × rerank_final_top_k
- **结论**：input=20, final=5

### Phase 4: 拒答阈值
- **测试内容**：reject_threshold
- **结论**：threshold=0.3

### Phase 5: 全量验证
- **测试内容**：3×3 重复验证最优配置
- **结论**：最优配置稳定

### Phase 6: 温度
- **测试内容**：temperature
- **结论**：temp=0.1 单独最优，多参数下 0.3 更好

## 🎓 面试要点

### 1. 实验设计
- 6阶段渐进式调优，从粗到细
- 每阶段控制变量，科学严谨
- 3×3 重复验证确保稳定性

### 2. 关键发现
- chunk_size 从 500→1200：更大的上下文窗口提升语义理解
- rrf_k 从 60→100：更宽的召回提升覆盖率
- rerank 从 8→5：更精的筛选提升准确率
- threshold 从 0.5→0.3：降低拒答率，平衡准确率

### 3. 工程实践
- 并发实验框架，10倍加速
- 断点续跑，防止意外中断
- 全链路 trace，便于定位瓶颈

## 📚 相关文档

- `rag_tuning_results/README.md` - 实验结果详解
- `rag_tuning/README.md` - 运行脚本说明
- `rag_eval_legacy/README.md` - 初始评估说明
