# AI 简历分析系统

> 上传一份简历，用自然语言提问——"这个人用了多久 Python？"、"有没有在大厂实习过？"——系统从简历中检索相关段落，生成答案并引用原始来源。

[![CI](https://github.com/user/ai-resume-analyzer/actions/workflows/ci.yml/badge.svg)](https://github.com/user/ai-resume-analyzer/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)

---

## 项目定位

**秋招项目作品**——展示对 RAG 全链路的深度理解，从传统 RAG 到 LangGraph Agentic RAG + MCP 协议 + Reflexion 自纠正的完整演进。

核心价值点：
- **Agentic RAG**：不是简单的检索+生成，而是带路由、评估、反思的智能体工作流
- **MCP 协议集成**：标准化 AI Agent 工具接口，业界前沿方向
- **工程化落地**：Docker 部署、CI/CD 流水线、监控告警、结构化日志、限流、错误追踪

---

## 核心能力

### AI 能力

| 能力 | 说明 |
|------|------|
| **混合检索** | 稠密向量（ChromaDB 余弦）+ 稀疏关键词（BM25 + jieba）→ RRF 融合 |
| **Rerank 精排** | Cross-Encoder（百炼 qwen3-vl-rerank）从 20 条精排到 5 条 |
| **防幻觉三层防御** | Prompt 约束 + Rerank 拒答阈值（score < 0.3）+ 来源可溯源 |
| **Agentic RAG** | LangGraph StateGraph：9 节点 + 3 条件边 + Reflexion 自纠正循环 |
| **MCP 协议** | 5 个 Tool + 2 个 Resource，JSON-RPC 2.0 over HTTP |
| **SSE 流式** | 逐 token 推送，流失败自动降级同步 |

### 工程能力

| 能力 | 说明 |
|------|------|
| **异步上传** | BackgroundTasks 后台处理 + 前端轮询（1.5s 间隔） |
| **JWT 鉴权** | 双 token（access 30min + refresh 7天）+ 401 静默刷新 |
| **Docker 部署** | 三容器编排（MySQL + FastAPI + nginx），多阶段构建 |
| **CI/CD** | GitHub Actions：CI（lint+test+build）+ CD（build+deploy+rollback） |
| **监控告警** | Prometheus 采集 + Grafana 仪表盘 + 告警规则 |
| **结构化日志** | JSON 格式，request_id 全链路追踪 |
| **限流** | slowapi 路由级限流（默认 60/min，登录 10/min，问答 20/min） |
| **全局异常处理** | 统一 JSON 错误格式 + request_id 追踪 |

---

## 技术栈

| 层级 | 技术 | 选型理由 |
|------|------|----------|
| Chat 模型 | Xiaomi MiMo `mimo-v2.5` | 小米自研推理模型，中文理解与 Agentic 规划能力强，OpenAI 兼容协议 |
| Embedding | 百炼 text-embedding-v4 | 中文检索效果优，1024 维 |
| Rerank | 百炼 qwen3-vl-rerank | 专用 Rerank API，比 Chat-based 更便宜更快 |
| 向量库 | ChromaDB | 轻量级，本地持久化，无需 Milvus 集群 |
| Agent 框架 | LangGraph 1.2 | StateGraph + 条件边 + checkpoint |
| 协议 | MCP (Model Context Protocol) | AI Agent 标准化工具接口 |
| 后端 | FastAPI + SQLAlchemy async | Python AI 应用标配 |
| 前端 | React 19 + TypeScript + Tailwind CSS 4 | SPA + SSE 流式渲染 |
| 数据库 | MySQL 8.0 | 用户、简历、问答历史 |
| 部署 | Docker + nginx | 多阶段构建 + SPA fallback + SSE 反代 |
| 监控 | Prometheus + Grafana | 指标采集 + 可视化仪表盘 |

---

## 架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                         前端                                     │
│              React 19 + TypeScript + Vite 8                     │
│                                                                  │
│   LoginPage ──> ResumeListPage ──> QAPage (SSE 流式)             │
│   (JWT 鉴权)    (上传/轮询/删除)    (逐字渲染)                    │
└────────────────────────────┬────────────────────────────────────┘
                             │ HTTP / SSE
┌────────────────────────────▼────────────────────────────────────┐
│                         后端                                     │
│                     FastAPI v0.2.0                               │
│                                                                  │
│  ┌──────────────────────┐  ┌──────────────────────────────────┐ │
│  │  REST API (/api/v1/*)│  │  MCP Server (/mcp)              │ │
│  │  - auth (注册/登录/   │  │  - search_knowledge_base        │ │
│  │    刷新 token)       │  │  - rerank_results               │ │
│  │  - resumes (上传/    │  │  - generate_answer              │ │
│  │    列表/删除)        │  │  - analyze_resume               │ │
│  │  - qa (同步 + SSE)   │  │  - rewrite_query                │ │
│  └──────────┬───────────┘  └──────────────┬───────────────────┘ │
│             │                              │                     │
│  ┌──────────▼──────────────────────────────▼───────────────────┐ │
│  │              Agentic RAG (LangGraph StateGraph)             │ │
│  │                                                              │ │
│  │  START ─> rewrite ─> route ─>┐                              │ │
│  │                               ├─ "search" ─> search         │ │
│  │                               │             > rerank        │ │
│  │                               │             > generate      │ │
│  │                               │             > evaluate ─┐   │ │
│  │                               │                  retry? ─┤   │ │
│  │                               │            self_reflect <┘   │ │
│  │                               │                  retry? ─┘   │ │
│  │                               └─ "direct" ─> direct_answer   │ │
│  │                                                    > output  │ │
│  │                                                       > END  │ │
│  └──────────────────────────────────────────────────────────────┘ │
│             │                              │                     │
│  ┌──────────▼──────────────────────────────▼───────────────────┐ │
│  │                      数据层                                  │ │
│  │  MySQL 8.0         ChromaDB          LLM APIs               │ │
│  │  (用户/简历/问答    (每份简历独立      (DeepSeek Chat +       │ │
│  │   历史)             collection)       百炼 Embedding +       │ │
│  │                                        百炼 Rerank)          │ │
│  └──────────────────────────────────────────────────────────────┘ │
│             │                              │                     │
│  ┌──────────▼──────────────────────────────▼───────────────────┐ │
│  │                    监控层                                    │ │
│  │  Prometheus           Grafana                               │ │
│  │  (指标采集 10s)       (仪表盘 + 告警)                        │ │
│  └──────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

### RAG 流水线

```
用户问题
    │
    ▼
[1] Query Rewrite ──────── LLM 指代消解（"他" → "候选人"）
    │                       失败时回退到原始问题
    ▼
[2] Route Decision ─────── 问候？→ direct_answer（零 LLM 开销）
    │                       专业问题？→ search
    ▼
[3] Hybrid Search ──────── 稠密（ChromaDB 余弦）+ 稀疏（BM25 + jieba）
    │                       RRF 融合（k=100）→ top 20 候选
    ▼
[4] Rerank ─────────────── Cross-Encoder 逐条打分
    │                       top 20 → top 5
    ▼
[5] Reject Gate ────────── 最高 rerank_score < 0.3 → "未找到相关信息"
    │                       （防止幻觉）
    ▼
[6] Generate ───────────── DeepSeek Chat 生成答案（带来源约束）
    │                       同步：3 次指数退避重试
    │                       SSE：逐 token 推送，失败降级同步
    ▼
[7] Evaluate ───────────── LLM-as-Judge 评估质量（三维度打分）
    │                       score < 0.6 → Reflexion 自纠正
    ▼
[8] Self-Reflection ────── 分析失败原因 → 识别缺失信息
    │                       生成补充查询 → 重新检索（最多 2 轮）
    ▼
[9] Output ─────────────── 最终答案 + 来源 + trace
```

---

## 关键决策

### 为什么用 RRF 融合而非仅稠密检索？

稠密向量对同义词和语义相似性敏感，但对精确关键词匹配（如"Python 3.11"）表现不稳定。BM25 正好互补。RRF（k=100）比加权平均更鲁棒，不需要调权重，对分值尺度不敏感。

### Reflexion 上限为什么定 2 轮？

第 1 轮反思补充缺失信息后，检索结果通常已有质变。第 2 轮作为保底，覆盖长尾的复杂多跳问题。第 3 轮开始收益衰减明显（实测 composite_score 提升 < 0.02），但 LLM 调用成本翻倍。

### 为什么用百炼 Rerank 而不是 LLM 直接打分？

专用 Cross-Encoder 比 Chat 模型便宜约 10 倍，且返回的 relevance_score 可以直接设拒答阈值。早期试过用 LLM 打分（eval 节点也是 LLM-as-Judge），但延迟高、一致性差，token 消耗大。

### 为什么不用 Milvus/Pinecone？

单机项目，ChromaDB 持久化到本地文件，零运维。10 份简历总共不到 2000 个 chunk，线性扫描也够用。如果数据量到百万级再考虑 Milvus。

### SSE 流式失败为什么降级同步？

流式依赖长连接，如果中间代理断开或客户端断连，用户得不到任何响应。降级到同步后至少返回完整答案。实现上在 `qa.py` 中捕获流式异常后调用同一个 `run_agentic_rag` 函数，不重复执行图。

---

## 快速开始

### 前置条件

- Python 3.11+
- Node.js 18+
- MySQL 8.0（或用 Docker）
- API Key：DeepSeek（Chat）、百炼（Embedding + Rerank）

### 1. 克隆项目

```bash
git clone https://github.com/user/ai-resume-analyzer.git
cd ai-resume-analyzer
```

### 2. 后端

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux

pip install -r requirements.txt
cp .env.example .env            # 填入 API Key
uvicorn main:app --reload --port 8000
```

### 3. 前端

```bash
cd frontend
npm install
npm run dev                     # Vite dev server → http://localhost:5173
```

Vite 自动将 `/api/*` 代理到后端 8000 端口。

### 4. 使用

1. 打开 http://localhost:5173
2. 注册 / 登录
3. 上传简历（PDF 或 DOCX）
4. 等待处理状态变为 "ready"
5. 对简历提问

---

## Docker 部署

### 生产环境

```bash
# 准备环境变量
cp backend/.env.example backend/.env.prod    # 填入生产环境值

# 启动所有服务
docker compose -f docker-compose.yml --env-file backend/.env.prod up -d

# 检查状态
docker compose ps
```

### 开发环境（热重载）

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml \
    --env-file backend/.env.dev up
```

### 服务列表

| 服务 | 容器名 | 端口 | 说明 |
|------|--------|------|------|
| MySQL | resume-mysql | 3306 | 数据库，带 healthcheck |
| Backend | resume-backend | 8000 | FastAPI，多阶段构建，非 root 用户 |
| Frontend | resume-frontend | 80/443 | nginx，SPA fallback + API 反代 |

生产部署流程和脚本详见 `deploy/README.md`。

### 监控栈（可选）

```bash
# 叠加启动监控服务
docker compose -f docker-compose.yml -f docker-compose.monitor.yml up -d
```

| 服务 | 端口 | 说明 |
|------|------|------|
| Prometheus | 9090 | 指标采集（10s 间隔） |
| Grafana | 3000 | 仪表盘（HTTP/RAG/LLM/系统） |

详细配置见 `monitoring/README.md`。

---

## 环境变量

```bash
# ── Chat 模型 (Xiaomi MiMo) ──
CHAT_API_KEY=sk-xxx
CHAT_BASE_URL=https://api.xiaomimimo.com/v1
CHAT_MODEL=mimo-v2.5

# ── Embedding 模型 (百炼) ──
EMBEDDING_API_KEY=sk-xxx
EMBEDDING_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
EMBEDDING_MODEL=text-embedding-v4

# ── Rerank 模型 (百炼) ──
RERANK_API_KEY=sk-xxx
RERANK_BASE_URL=https://<your-endpoint>.cn-beijing.maas.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank
RERANK_MODEL=qwen3-vl-rerank

# ── 数据库 ──
DATABASE_URL=mysql+aiomysql://root:password@localhost:3306/resume_ai

# ── JWT ──
JWT_SECRET_KEY=<生成: python -c "import secrets; print(secrets.token_hex(32))">

# ── CORS ──
CORS_ORIGINS=http://localhost:5173,http://localhost

# ── 限流 ──
RATE_LIMIT_DEFAULT=60/minute
RATE_LIMIT_LOGIN=10/minute
RATE_LIMIT_REGISTER=5/minute
RATE_LIMIT_ASK=20/minute

# ── MCP (可选) ──
MCP_SERVER_URL=http://127.0.0.1:8000/mcp
MCP_TOKEN=

# ── 日志 ──
LOG_LEVEL=INFO
```

完整模板见 `backend/.env.example`。

---

## 项目结构

```
ai-resume-analyzer/
├── backend/
│   ├── api/                    # 路由处理
│   │   ├── auth.py             # 注册 / 登录 / 刷新
│   │   ├── resumes.py          # 上传（202 异步）/ 列表 / 详情 / 删除
│   │   ├── qa.py               # 同步问答 / SSE 流式 / 历史
│   │   ├── deps.py             # get_current_user 依赖
│   │   └── v1/router.py        # v1 路由汇总 + 旧路由重定向
│   ├── core/                   # 基础设施（详见 README）
│   │   ├── config.py           # Pydantic Settings（读取所有环境变量）
│   │   ├── database.py         # SQLAlchemy async engine + session
│   │   ├── security.py         # bcrypt + JWT 编解码
│   │   ├── cache.py            # Embedding 内存缓存（sha256 → vector）
│   │   ├── retry.py            # 指数退避重试（1s → 2s → 4s）
│   │   ├── trace.py            # StepTimer 全链路 trace
│   │   ├── rag_params.py       # RAG 参数配置 + 实验阶段网格
│   │   ├── limiter.py          # slowapi 限流器
│   │   ├── exceptions.py       # AppException + 全局异常处理器
│   │   ├── logging_config.py   # 结构化 JSON 日志
│   │   └── request_id.py       # X-Request-ID 中间件
│   ├── models/                 # SQLAlchemy ORM
│   │   ├── user.py             # users 表
│   │   ├── resume.py           # resumes 表（status: processing/ready/failed）
│   │   └── qa_history.py       # qa_history 表
│   ├── schemas/                # Pydantic 请求/响应模型
│   ├── services/               # 业务逻辑
│   │   ├── auth_service.py     # 注册 + 登录 + token 刷新
│   │   ├── resume_service.py   # 快速创建 + 后台处理
│   │   ├── rag_service.py      # 混合检索 + rerank + 生成 + 流式
│   │   ├── qa_service.py       # 问答历史 CRUD
│   │   └── agentic_rag/        # LangGraph Agentic RAG 模块（详见 README）
│   │       ├── state.py        # AgenticRAGState TypedDict（18 字段）
│   │       ├── rewrite.py      # 查询改写 + 路由节点
│   │       ├── search.py       # 检索 + rerank 节点
│   │       ├── generate.py     # 生成 + 评估节点
│   │       ├── reflection.py   # Self-Reflection 节点（Reflexion 核心）
│   │       ├── graph.py        # StateGraph 组装（直接模式）
│   │       ├── mcp_nodes.py    # MCP 模式节点
│   │       └── mcp_graph.py    # MCP 模式 StateGraph 组装
│   ├── mcp_server/             # MCP Server 实现（详见 README）
│   │   ├── server.py           # FastMCP 实例 + JWT 中间件
│   │   ├── tools/              # 5 个 MCP 工具
│   │   ├── resources/          # 2 个 MCP 资源
│   │   └── transport/http.py   # Streamable HTTP + ASGI 路径重写
│   ├── mcp_client/             # MCP Client 实现
│   │   ├── client.py           # JSON-RPC 2.0 over HTTP
│   │   └── tools.py            # mcp_search / mcp_rerank / mcp_generate
│   ├── utils/file_parser.py    # PDF (pypdf) + DOCX (python-docx) 解析
│   ├── tests/                  # 326 个测试（单元 + 集成 + 端到端）
│   ├── alembic/                # 数据库迁移
│   ├── rag_tuning/             # RAG 参数调优实验框架
│   └── main.py                 # FastAPI 入口
│
├── frontend/                  # React 19 + TypeScript + Tailwind（详见 README）
│   └── src/
│       ├── api/                # fetch 封装（JWT + 401 静默刷新）
│       │   ├── client.ts       # GET/POST/DELETE + 自动携带 auth header
│       │   ├── auth.ts         # login / register / logout
│       │   ├── resumes.ts      # listResumes / uploadResume / getResume
│       │   └── qa.ts           # askQuestion / askQuestionStream (SSE)
│       ├── context/AuthContext.tsx  # JWT 解码 + 登录状态管理
│       ├── components/
│       │   ├── Navbar.tsx      # 顶栏：项目名 + 用户名 + 退出
│       │   └── ErrorBoundary.tsx  # React 错误边界 + 重试
│       ├── pages/
│       │   ├── LoginPage.tsx       # 登录/注册双 Tab
│       │   ├── ResumeListPage.tsx  # 上传 + 轮询 + 列表 + 删除
│       │   └── QAPage.tsx          # SSE 流式问答 + 来源展开
│       └── App.tsx             # 路由 + AuthProvider
│
├── archive/                    # 归档目录
│   └── rag_eval_legacy/        # 已过时的评估体系（基于虚构简历）
│
├── deploy/                     # 部署配置（详见 README）
│   ├── docker-compose.prod.yml # 生产部署（预构建镜像）
│   ├── deploy.sh               # 部署脚本 + 健康检查 + 回滚
│   └── .env.prod.example       # 生产环境变量模板
│
├── monitoring/                 # 监控配置（详见 README）
│   ├── prometheus.yml          # Prometheus 采集配置
│   ├── alert_rules.yml         # 告警规则
│   └── grafana/                # Grafana 仪表盘 + provisioning
│
├── docker-compose.yml          # 生产环境：MySQL + FastAPI + nginx
├── docker-compose.dev.yml      # 开发环境 override
├── docker-compose.monitor.yml  # 监控栈：Prometheus + Grafana
├── .github/workflows/ci.yml    # CI 流水线
├── .github/workflows/cd.yml    # CD 流水线（自动部署）
└── .pre-commit-config.yaml     # pre-commit hooks
```

---

## API 文档

### 基础路径

```
生产环境：http://localhost/api/v1/
开发环境：http://localhost:8000/api/v1/
```

### 鉴权

除 `/api/v1/auth/register` 和 `/api/v1/auth/login` 外，所有接口需要 JWT Bearer token：

```
Authorization: Bearer <access_token>
```

### 接口列表

#### Auth

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/auth/register` | 注册新用户 |
| POST | `/api/v1/auth/login` | 登录，返回 access + refresh token |
| POST | `/api/v1/auth/refresh` | 刷新 access token |

#### Resumes

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/resumes/upload` | 上传简历（202 异步处理） |
| GET | `/api/v1/resumes/` | 列出所有简历 |
| GET | `/api/v1/resumes/{id}` | 获取简历详情 + 状态 |
| DELETE | `/api/v1/resumes/{id}` | 删除简历 |

#### QA

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/qa/ask` | 提问（同步响应） |
| POST | `/api/v1/qa/ask/stream` | 提问（SSE 流式） |
| GET | `/api/v1/qa/history/{resume_id}` | 获取问答历史（分页） |

#### MCP

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/mcp/` | MCP JSON-RPC 2.0 端点 |

MCP Server 的 Tool/Resource 列表和添加方式详见 `mcp_server/README.md`。

#### Health

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 健康检查（MySQL + ChromaDB 连通性） |
| GET | `/?verbose=true` | 健康检查 + 磁盘空间 |

---

## 开发指南

### 代码规范

- **后端**：Black + Ruff + isort（pre-commit 强制执行）
- **前端**：Oxlint（`npm run lint` 强制执行）

### Pre-commit Hooks

```bash
pip install pre-commit
pre-commit install
```

`git commit` 时自动执行：
- trailing-whitespace 清理
- Black 格式化
- Ruff lint 检查
- isort import 排序

### 本地开发

```bash
# 终端 1：后端
cd backend && .venv\Scripts\activate && uvicorn main:app --reload --port 8000

# 终端 2：前端
cd frontend && npm run dev

# 终端 3：测试
cd backend && python -m pytest tests/ -v
```

前端构建配置（nginx、Docker、Oxlint）详见 `frontend/README.md`。
后端基础设施约定（配置、异常、trace、指标）详见 `core/README.md`。

---

## 测试

### 运行全部测试

```bash
cd backend
python -m pytest tests/ -v
```

### 测试分类

| 分类 | 数量 | 说明 |
|------|------|------|
| 单元测试 | ~100 | 纯逻辑函数（分块、RRF、路由） |
| 集成测试 | ~150 | API 接口 + SQLite 内存库 |
| MCP 测试 | ~96 | Server 工具/资源 + Client + 节点 + 图 + 集成 + 端到端 |
| Agentic RAG 测试 | ~50 | Rewrite/Search/Generate/Graph + Reflexion |

**总计：326 个测试，覆盖全部核心路径**

### 测试基础设施

- SQLite 内存数据库（无需 MySQL）
- `pytest-asyncio` 支持异步测试
- 测试中禁用限流
- Mock LLM 响应确保确定性

---

## CI/CD

### CI 流水线（`.github/workflows/ci.yml`）

| Job | 步骤 | 说明 |
|-----|------|------|
| lint | pre-commit | Black + Ruff + isort + trailing-whitespace |
| backend-test | pip install + pytest | SQLite 内存库跑全部测试 |
| frontend-build | npm ci + lint + build | Oxlint + TypeScript + Vite 构建 |

触发条件：push `main`/`develop` + PR `main`。

### CD 流水线（`.github/workflows/cd.yml`）

| Job | 步骤 | 说明 |
|-----|------|------|
| prepare | 环境判断 | push develop→staging, push main→production |
| test | 后端 + 前端测试 | 可跳过 |
| build-and-push | Docker Buildx | 构建 + 推送镜像 |
| deploy | SSH 部署 | 拉取镜像 + 健康检查 + 自动回滚 |
| notify | 通知 | 部署结果通知（预留） |

触发条件：push `main`（production）/ push `develop`（staging）/ 手动触发。

---

## RAG 参数调优

6 阶段实验框架，确定最优配置：

| 参数 | 原始值 | 最优值 | 变化 |
|------|--------|--------|------|
| chunk_size | 500 | 1200 | +140% |
| overlap | 50 | 50 | 不变 |
| rrf_k | 60 | 100 | +67% |
| rerank_final_top_k | 8 | 5 | -37.5% |
| reject_threshold | 0.5 | 0.3 | -40% |
| generate_temperature | 0.3 | 0.3 | 不变 |

**结果**：composite_score 提升 +5.9%（0.5146 → 0.5448）

```bash
cd backend
python -m rag_tuning.evaluate --baseline           # 基线
python -m rag_tuning.evaluate --phase 1            # chunk_size × overlap
python -m rag_tuning.evaluate --single chunk_size=800,overlap=100  # 单组测试
```

完整调优结果：[backend/rag_tuning_results/](backend/rag_tuning_results/)

---

