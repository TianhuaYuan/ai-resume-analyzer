# RAG 参数调优实验框架

## 📁 目录结构

```
rag_tuning/
├── README.md                      ← 本文件
├── evaluation.md                  ← 📚 评估体系总览（面试要点）
├── evaluate.py                    ← ✅ 评估框架核心
├── golden_set.json                ← ✅ 测试数据（真实简历 QA）
├── run_concurrent.py              ← ✅ 主力并发实验框架
├── run_phase1_single.py           ← Phase1 单组测试
├── run_phase5_concurrent.py       ← Phase5 并发版
├── run_phase5_robust.py           ← Phase5 鲁棒版
└── uploads/                       ← 测试简历文件
    ├── resume_pm.txt
    ├── resume_frontend.txt
    ├── resume_python.txt
    ├── resume_ai.txt
    ├── resume_data.txt
    ├── resume_design.txt
    ├── resume_architect.txt
    ├── resume_accounting.txt
    ├── resume_sales.txt
    └── resume_sre.txt
```

## 🔧 核心文件

### evaluate.py（评估框架）
- **功能**：RAG 参数调优的评估框架
- **提供**：
  - `load_golden_set()` - 加载测试数据
  - `evaluate_one()` - 评估单条 QA
  - `aggregate_metrics()` - 聚合指标
  - `save_results()` / `save_details()` - 保存结果
  - `rebuild_all_indices()` - 重建索引
- **被谁调用**：所有 `run_*.py` 脚本

### golden_set.json（测试数据）
- **内容**：真实简历的 QA 对（1082行）
- **格式**：
  ```json
  {
    "qa_id": "pm_001",
    "resume_file": "resume_pm.txt",
    "question": "用户的学历是什么？",
    "gold_answer": "XX大学软件工程本科",
    "answer_type": "exact_match",
    "should_answer": true,
    "acceptable_keywords": ["XX大学", "本科", "软件工程"]
  }
  ```

## 🚀 使用方法

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
```

### 单组参数测试
```bash
python rag_tuning/run_phase1_single.py --index 5
python rag_tuning/run_phase1_single.py --all
```

### Phase5 专项
```bash
python rag_tuning/run_phase5_concurrent.py   # 并发版
python rag_tuning/run_phase5_robust.py       # 鲁棒版
```

## 📊 实验流程

1. **Phase 1**：chunk_size × overlap（分块策略）
2. **Phase 2**：检索参数扫描（rrf_k, hybrid_top_k, rerank_truncation）
3. **Phase 3**：精排压缩比（rerank_input_top_k × rerank_final_top_k）
4. **Phase 4**：拒答阈值（reject_threshold）
5. **Phase 5**：Top-3 全量验证（确认最优配置稳定性）
6. **Phase 6**：temperature（生成温度）

## 🎯 最优配置

最终结论在 `rag_tuning_results/optimal_config.json`，关键参数：
- chunk_size: 1200
- rrf_k: 100
- rerank_final_top_k: 5
- reject_threshold: 0.3
- temperature: 0.3

## 📈 性能提升

- Baseline composite: 0.5146
- Optimal composite: 0.5448
- **提升: +5.9%**

## 🔗 依赖关系

```
rag_tuning/run_concurrent.py
    ↓ import
rag_tuning/evaluate.py
    ↓ load_golden_set()
rag_tuning/golden_set.json
```
