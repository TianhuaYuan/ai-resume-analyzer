# Run contract

模型运行器只需输出 JSONL，每行至少包含 `case_id`、`task_success`、`citations`、`refused`、`uncertainty`、`latency_ms`、`input_tokens`、`output_tokens`、`cost_cny`。然后执行：

```powershell
py -3 evals/score_run.py --run artifacts/<run>.jsonl --out artifacts/<run>_scored.json
```

评分器会保留 `human_review_required=true`，不会把 synthetic case 自动升级为人工 gold。`evals/fault_matrix.json` 是故障注入验收清单；每个 fault 必须有原始日志、恢复状态和是否产生重复副作用的证据。
