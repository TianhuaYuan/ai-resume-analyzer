# monitoring

Prometheus + Grafana 监控栈，用于开发环境本地观测，生产部署前需调整采集目标。

## 结构

```
monitoring/
├── prometheus.yml          # 采集配置，15s 间隔，10s 超时
├── alert_rules.yml         # 告警规则（HTTP/RAG/LLM/系统四组）
└── grafana/
    ├── dashboards/
    │   └── overview.json   # 预置仪表盘
    └── provisioning/       # 启动时自动注册
        ├── datasources/prometheus.yml
        └── dashboards/default.yml
```

## 暴露的 metrics

`backend/core/metrics.py` 在 `/metrics` 端点暴露四层指标：

| 指标前缀 | 内容 | 重要告警 |
|----------|------|----------|
| app_http_* | 请求数/耗时/并发/活跃连接 | 5xx > 10%, P95 > 5s, 请求量骤降 |
| app_rag_* | 各步骤耗时/错误/检索结果数/重试次数 | 步骤 P95 > 10s, 重试率 > 0.5/s, 空结果率 > 30% |
| app_llm_* | 调用次数/耗时/token 消耗/错误 | 错误率 > 20%, P95 > 30s |
| app_process_* | RSS 内存/CPU/线程数 | RSS > 1.5GB, 线程 > 200 |

指标名通过 `prometheus_client` 注册，端点归一化（`/resumes/{uuid}` -> `/resumes/{id}`）。

## 启动

```bash
docker compose -f docker-compose.monitor.yml up -d
# Prometheus: http://localhost:9090
# Grafana:    http://localhost:3000 (admin/admin)
```

采集源默认指向 `host.docker.internal:8000`（开发环境）。生产部署时取消 `prometheus.yml` 中 `targets: ["backend:8000"]` 的注释并删除 dev 配置。

## 告警规则

`alert_rules.yml` 定义了 9 条规则，按严重程度分：
- critical: HighErrorRate, LLMHighErrorRate（需要立即处理）
- warning: 其余 7 条（延迟/重试率/内存/线程）

当前 alertmanager 配置被注释，实际告警通知需要配置 `alerting.alertmanagers` 指向运行的 alertmanager 实例。
