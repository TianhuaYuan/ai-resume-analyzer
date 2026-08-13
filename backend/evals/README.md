# AI Resume Analyzer Evaluation Suite

评测套件只接受脱敏、版本化数据。它不访问生产用户数据，不把 LLM 自评当成唯一真值。

## 数据集结构

每个样本使用 `manifest.jsonl` 一行 JSON：

```json
{"id":"resume-001","kind":"resume_parse","input":"files/resume-001.pdf","expected":"labels/resume-001.json","tags":["pdf","cn","multicolumn"]}
```

支持样本类型：

- `resume_parse`：原文文件 + 结构化字段标注 + 可选行号范围。
- `rag_qa`：问题 + 允许引用的 chunk + 期望关键事实 + 是否应拒答。
- `jd_match`：JD + 简历版本 + 人工标注的匹配差距与优先级。
- `tool_call`：消息 + 允许工具 + 期望参数/拒绝原因。
- `stream_recovery`：事件序列，用于乱序、重复、断线和重答。

## 评测结果结构

每次运行写入 `results/<run-id>.json`，必须包含：

- git commit、数据集 hash、模型/provider、场景参数、随机种子。
- 总体指标和按 tag 分组指标。
- 失败样本 ID、输入摘要、错误类别、可复现命令。
- Token、费用、P50/P95 延迟和重试次数。

## 数据准入

1. 去除姓名、电话、邮箱、公司敏感信息或使用合成实体替换。
2. 标注者确认字段事实、引用范围和拒答标签。
3. 运行前校验 JSON schema、重复 ID、文件存在性和 hash。
4. 任何指标写入 `docs/baseline/quality-baseline.md` 前必须能用同一命令重跑。

## 推荐目录

```text
backend/evals/
  datasets/
    manifest.jsonl
    files/
    labels/
  results/
  validate_dataset.py
  run_eval.py
```

当前仓库只提交 schema、校验器和示例，不提交真实个人简历。
