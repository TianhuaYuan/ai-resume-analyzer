# deploy

生产部署脚本和配置。与根目录的 `docker-compose.yml`（单机开发用）不同，这个目录面向 CD 和服务器部署。

## 文件

| 文件 | 用途 |
|------|------|
| deploy.sh | 部署脚本：拉镜像 + 启动 + 健康检查 + 回滚 |
| docker-compose.prod.yml | 生产 compose（三服务：MySQL + backend + frontend） |
| .env.prod.example | 生产环境变量模板 |

## deploy.sh 用法

```bash
# 部署指定 commit tag 的镜像
./deploy.sh abc123def456

# 回滚到上一个版本
./deploy.sh --rollback

# 回滚到指定版本
./deploy.sh --rollback abc123def456

# 查看当前容器状态
./deploy.sh --status

# 清理 dangling 镜像
./deploy.sh --cleanup

# 模拟执行，不实际操作
./deploy.sh abc123def456 --dry-run
```

## 工作流

```
preflight（检查 docker/docker compose/文件是否存在）
  → load_env（加载 .env）
    → pull_images（拉两镜像）
      → start_services（docker compose up -d）
        → wait_healthy（最多等 120s，检查容器 healthcheck）
          → 成功：写入 .rollback-info，清理，显示状态
          → 失败：自动回滚到 .rollback-info 记录的前一版本
```

## 环境变量

需要 `.env` 文件在项目根目录（`deploy/` 父目录），包含 `MYSQL_ROOT_PASSWORD`、`JWT_SECRET_KEY`、各 API Key 等。从 `.env.prod.example` 复制后填写。

## 镜像

脚本从 `${DOCKER_REGISTRY}/${DOCKER_REPO}-backend:${tag}` 和 `${DOCKER_REPO}-frontend:${tag}` 拉取。默认 registry 为 docker.io。

## nginx

生产环境通过 frontend 容器的 nginx 反代 `/api/` 到 backend 容器。SSE 端点 `/api/v1/qa/ask/stream` 需要 nginx 关闭 buffering（已在 nginx.conf 配置）。

## 回滚

每个成功部署会记录 `.rollback-info`：

```
ROLLBACK_TAG=<当前部署的 tag>
OLD_BACKEND=<之前的 backend 镜像>
OLD_FRONTEND=<之前的 frontend 镜像>
TIMESTAMP=<部署时间>
```

健康检查失败时会自动读取此文件回滚。手动回滚用 `--rollback`。
