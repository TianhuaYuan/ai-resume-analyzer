# 可复现评测资产

本目录提供不依赖在线模型的评测数据与校验入口。数据不包含真实简历或招聘信息中的姓名、联系方式等 PII；`provenance` 只记录来源文件路径和脱敏说明。

## 生成与校验

```powershell
py -3 evals/generate_dataset.py
py -3 evals/validate_dataset.py
```

生成结果为 `evals/datasets/cases.jsonl`，固定 `seed=20260830`，共 96 条：48 standard、24 boundary、24 adversarial；其中 16 条 deep_research。脚本只使用本地公开输入文件的类别信息，不调用模型，不伪造用户反馈或线上指标。

## 口径

每条 case 都带有 `expected`, `scorer`, `risk`, `license` 与 `provenance` 字段。正式模型结果必须另存为 run artifact，不得覆盖 gold 数据；没有人工复核的字段应标记为 `unreviewed`。
