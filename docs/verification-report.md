# 整改验收记录

## 已通过的自动化验证

- 后端：`cd backend && python -m pytest tests/ -q --tb=short`，修复 MinerU 连接池生命周期后退出码为 `0`；全量输出无失败项，包含 1 个跳过项。
- 前端：`npm test -- --run` 为 17 个测试文件、281 个测试通过。
- 前端质量门禁：`npm run lint`、`npm run build` 通过（仅已有 lint warning）。
- Python：`python -m compileall -q backend` 通过。
- Compose 静态配置：monitoring、staging 配置均通过 `docker compose ... config`。
- 代码卫生：`git diff --check` 通过，提交后工作区干净。

## 运行时验收边界

当前机器的 Docker Desktop 客户端进程存在，但 Linux engine 的 named pipe 未提供；等待 120 秒后仍无法连接。因此 Grafana/Prometheus 实时 targets、staging 容器启动和容器内 WeasyPrint 尚未做运行时验收。

当前 Windows Python 已安装 `weasyprint==67.0`，但 smoke test 因缺少 `libgobject-2.0-0` 失败。请按 [OPERATIONS_MONITORING.md](../OPERATIONS_MONITORING.md) 安装 MSYS2 GTK 原生库，或直接在 backend Docker 镜像中验证。

真实 thinking off/on 反解析效果评测还需要可用的 LLM API 凭据；代码侧已锁定场景矩阵、请求体和成本统计策略。

## 重跑命令

```powershell
cd backend
python -m pytest tests/ -q --tb=short
cd ..\frontend
npm test -- --run
npm run lint
npm run build
cd ..
docker compose -f docker-compose.staging.yml config
docker compose -f docker-compose.monitoring.yml config
```
