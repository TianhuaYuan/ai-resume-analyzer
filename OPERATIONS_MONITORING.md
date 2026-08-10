# PDF 导出与监控部署

## WeasyPrint（中文 PDF）

后端镜像已同时安装 `weasyprint` Python 包和 Cairo/Pango/GDK-Pixbuf 运行库，并预装 Noto CJK 字体。重新构建 `backend` 镜像后，`GET /api/v1/resumes/{id}/export?format=pdf` 会直接生成中文 PDF。

裸机运行后端时至少安装：`libpango-1.0-0 libpangoft2-1.0-0 libcairo2 libgdk-pixbuf-2.0-0 libffi8 shared-mime-info fontconfig fonts-noto-cjk`，并执行 `fc-cache -f`。

## Prometheus + Grafana

生产/预发布后端启用了 `/metrics` Bearer token 校验。设置同一个 `METRICS_TOKEN` 和 `GRAFANA_ADMIN_PASSWORD` 后启动：

```powershell
docker compose -f docker-compose.prod.yml up -d
docker compose -f docker-compose.monitoring.yml up -d
```

监控 compose 使用固定的 `resume-network`，因此先启动业务 compose。Grafana 和 Prometheus 默认只绑定 `127.0.0.1`（分别为 `http://localhost:3000`、`http://localhost:9090`），避免直接暴露到公网；需要由反向代理或内网访问时，显式设置 `GRAFANA_BIND=0.0.0.0` 或 `PROMETHEUS_BIND=0.0.0.0`。

Prometheus 容器启动时以 `0600` 权限将 `METRICS_TOKEN` 写入受管卷，再用 `bearer_token_file` 抓取后端 `/metrics`。Grafana 数据源与 Overview dashboard 由 provisioning 自动注册，数据源 UID 固定为 `prometheus`。

本地开发若后端未设置 `METRICS_TOKEN`，留空即可；生产/预发布不要留空，否则后端配置校验会拒绝启动。
