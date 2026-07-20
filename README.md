# AI 简历分析系统

> 上传一份简历，用自然语言提问——"这个人用了多久 Python？"、"有没有在大厂实习过？"——系统从简历中检索相关段落，生成答案并引用原始来源。

[![CI](https://github.com/user/ai-resume-analyzer/actions/workflows/ci.yml/badge.svg)](https://github.com/user/ai-resume-analyzer/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-green)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-19-61DAFB)](https://react.dev/)

---

## 总览

```mermaid
graph TB
    User((用户))
    subgraph 前端 [React 19 + TypeScript]
        Login[登录/注册]
        Upload[简历上传]
        QA[问答界面<br/>SSE 流式渲染]
    end
    subgraph 后端 [FastAPI]
        Auth[JWT 鉴权]
        ResumeAPI[简历管理]
        QaAPI[问答 API]
        subgraph Agent [Agentic RAG]
            LangGraph[LangGraph<br/>StateGraph]
            MCP[MCP 协议<br/>Tool/Resource]
        end
    end
    subgraph 数据层
        MySQL[(MySQL 8.0<br/>用户/简历/历史)]
        Chroma[(ChromaDB<br/>向量库)]
        LLM[LLM APIs<br/>Chat + Embedding + Rerank]
    end
    subgraph 运维 [Deploy & Monitor]
        Docker[Docker<br/>三容器编排]
        CI_CD[GitHub Actions<br/>CI/CD]
        Prom[Prometheus<br/>Grafana]
    end

    User -->|HTTP/SSE| Login
    User --> Upload
    User --> QA
    Login --> Auth
    Upload --> ResumeAPI
    QA --> QaAPI
    QaAPI --> Agent
    Agent --> Chroma
    Agent --> LLM
    ResumeAPI --> MySQL
    QaAPI --> MySQL
    Docker --> 后端
    Docker --> 前端
    Docker --> MySQL
    CI_CD -.->|自动部署| Docker
    Prom -.->|指标采集| 后端
```

**秋招项目作品**——展示 RAG 全链路深度理解，从传统 RAG 到 LangGraph Agentic RAG + MCP 协议 + Reflexion 自纠正的完整演进。

---

## 核心能力

### AI 能力

| 能力 | 说明 |
|------|------|
| **混合检索** | 稠密向量（ChromaDB 余弦）+ 稀疏关键词（BM25 + jieba）→ RRF 融合 |
| **Rerank 精排** | Cross-Encoder 从 20 条精排到 5 条 |
| **防幻觉三层防御** | Prompt 约束 + Rerank 拒答阈值（score < 0.3）+ 来源可溯源 |
| **Agentic RAG** | LangGraph StateGraph：9 节点 + 3 条件边 + Reflexion 自纠正 |
| **MCP 协议** | 5 个 Tool + 2 个 Resource，JSON-RPC 2.0 over HTTP |
| **SSE 流式** | 逐 token 推送，流失败自动降级同步 |

### 工程能力

| 能力 | 说明 |
|------|------|
| **JWT 鉴权** | 双 token（access 30min + refresh 7天）+ 401 静默刷新 + 5 分钟预警 |
| **异步上传** | BackgroundTasks 后台处理 + 前端轮询（1.5s 间隔） |
| **Docker 部署** | 三容器编排（MySQL + FastAPI + nginx），多阶段构建，healthcheck |
| **CI/CD** | GitHub Actions：CI（lint+test+build）+ CD（build+deploy+auto-rollback） |
| **监控** | Prometheus 四层指标 + Grafana 仪表盘 + 告警规则 |
| **结构化日志** | JSON 格式，request_id 全链路追踪 |
| **限流** | slowapi 路由级限流（默认 60/min，登录 10/min，问答 20/min） |
| **全局异常** | 统一 JSON 错误格式 + request_id 追踪 |

---

## 技术栈

| 层级 | 技术 | 选型理由 |
|------|------|----------|
| Chat 模型 | MiMo `v2.5` | 中文理解与 Agentic 规划能力强，OpenAI 兼容协议 |
| Embedding | 百炼 `text-embedding-v4` | 中文检索效果优，1024 维 |
| Rerank | 百炼 `qwen3-vl-rerank` | 专用 Rerank API，比 Chat 模型更便宜更快 |
| 向量库 | ChromaDB | 轻量级本地持久化，无需 Milvus 集群 |
| Agent 框架 | LangGraph 1.2 | StateGraph + 条件边 + MemorySaver checkpoint |
| 协议 | MCP | AI Agent 标准化工具接口 |
| 后端 | FastAPI + SQLAlchemy async | Python AI 应用标配 |
| 前端 | React 19 + TypeScript + Tailwind CSS 4 | SPA + SSE 流式渲染 |
| 数据库 | MySQL 8.0 | 用户、简历、问答历史 |
| 部署 | Docker + nginx | 多阶段构建 + SPA fallback + SSE 反代 |
| 监控 | Prometheus + Grafana | 四层指标体系 + 可视化仪表盘 |

---

## 架构

### 系统架构

```mermaid
flowchart TB
    subgraph FE [前端 - React 19]
        direction TB
        LP[LoginPage] --> RLP[ResumeListPage]
        RLP --> QP[QAPage<br/>SSE 流式]
    end

    subgraph BE [后端 - FastAPI]
        direction TB
        REST[REST API<br/>/api/v1/*]
        MCP_SRV[MCP Server<br/>/mcp/*]
        subgraph RAG [Agentic RAG]
            DM[直接模式<br/>graph.py]
            MM[MCP 模式<br/>mcp_graph.py]
        end
        CORE[基础设施<br/>鉴权/限流/日志/指标]
    end

    subgraph DS [数据层]
        MySQL[(MySQL 8.0)]
        CHROMA[(ChromaDB)]
        LLM_API[LLM APIs<br/>MiMo + 百炼]
    end

    FE -->|HTTP / SSE| REST
    FE -->|HTTP| MCP_SRV
    REST --> RAG
    MCP_SRV --> MM
    RAG --> CHROMA
    RAG --> LLM_API
    RAG --> MySQL
    CORE --> REST
    CORE --> MCP_SRV
```

### 上传流水线

```mermaid
sequenceDiagram
    participant U as 用户
    participant FE as 前端
    participant BE as 后端
    participant BG as BackgroundTasks
    participant CH as ChromaDB

    U->>FE: 选择简历文件
    FE->>BE: POST /resumes/upload
    BE->>BE: save_upload_file
    BE->>BE: create_resume_quick<br/>(status=processing)
    BE-->>FE: 202 + resume_id
    BE->>BG: process_resume_background
    BG->>BG: parse_resume (PDF/DOCX → text)
    BG->>BG: chunk_by_sections (1200/50)
    BG->>BG: get_embeddings (sha256 缓存)
    BG->>CH: 写入 collection
    BG->>BE: 更新 status=ready

    loop 每 1.5s，最多 30 次
        FE->>BE: GET /resumes/{id}
        BE-->>FE: status=processing 或 ready
    end

    FE-->>U: 显示"已就绪"
```

### Agentic RAG 问答流水线

```mermaid
flowchart LR
    START([用户提问])
    REWRITE[Query Rewrite<br/>指代消解]
    ROUTE{Route}

    START --> REWRITE
    REWRITE --> ROUTE

    ROUTE -->|greeting| DA[Direct Answer<br/>固定模板]
    ROUTE -->|search| SEARCH[Hybrid Search<br/>稠密 + BM25 + RRF]

    SEARCH --> RERANK[Rerank<br/>Cross-Encoder 精排]
    RERANK --> REJECT{Reject Gate}
    REJECT -->|score < 0.3| REJECTED[拒答]
    REJECT -->|score >= 0.3| GENERATE[Generate<br/>LLM 生成]

    GENERATE --> EVALUATE{Evaluate<br/>三维度评分}
    EVALUATE -->|score >= 0.6| OUTPUT[Output<br/>答案 + 来源]
    EVALUATE -->|score < 0.6| REFLECTION{Reflexion<br/>≤ 2 轮}
    REFLECTION -->|重试| SEARCH
    REFLECTION -->|到达上限| OUTPUT

    DA --> OUTPUT
    REJECTED --> OUTPUT
    OUTPUT --> END([返回结果])
```

### Reflexion 自纠正机制

```mermaid
flowchart TD
    EVAL{{Evaluate 节点<br/>三维度评分}}
    EVAL -->|完整性 40%<br/>准确性 40%<br/>来源可信度 20%| SCORE{composite<br/>< 0.6?}
    SCORE -->|否 ✅| OUT[返回结果]
    SCORE -->|是 🔄| ROUND{round ≤ 2?}
    ROUND -->|否| OUT
    ROUND -->|是| REFLECT[Self-Reflection<br/>分析失败原因]
    REFLECT --> IMPROVE[识别缺失信息]
    IMPROVE --> QUERY[生成补充查询]
    QUERY --> SEARCH[重新检索<br/>+ 历史去重]
    SEARCH --> RERANK
    RERANK --> GEN[重新生成]
    GEN --> EVAL
```

---

## 关键决策

### 为什么用 RRF 融合而非仅稠密检索？

稠密向量对同义词和语义相似性敏感，但对精确关键词匹配（如"Python 3.11"）表现不稳定。BM25 正好互补。RRF（k=100）比加权平均更鲁棒，不需要调权重，对分值尺度不敏感。

### Reflexion 上限为什么定 2 轮？

第 1 轮反思补充缺失信息后，检索结果通常已有质变。第 2 轮作为保底，覆盖长尾的复杂多跳问题。第 3 轮开始收益衰减明显（实测 composite_score 提升 < 0.02），但 LLM 调用成本翻倍。

### 为什么用专用 Rerank 而不是 LLM 直接打分？

专用 Cross-Encoder 比 Chat 模型便宜约 10 倍，且返回的 relevance_score 可以直接设拒答阈值。早期试过用 LLM 打分，但延迟高、一致性差，token 消耗大。

### 为什么不用 Milvus/Pinecone？

单机项目，ChromaDB 持久化到本地文件，零运维。10 份简历总共不到 2000 个 chunk，线性扫描也够用。

### SSE 流式失败为什么降级同步？

流式依赖长连接，如果中间代理断开或客户端断连，用户得不到任何响应。降级到同步后至少返回完整答案。实现上捕获流式异常后调用同一个生成函数，不重复执行图。

---

## 快速开始

### 前置条件

- Python 3.11+
- Node.js 18+
- MySQL 8.0（或用 Docker）
- API Key：MiMo（Chat）、百炼（Embedding + Rerank）

### 1. 克隆

```bash
git clone https://github.com/user/ai-resume-analyzer.git
cd ai-resume-analyzer
```

### 2. 后端

```bash
cd backend
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
# source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env   # 填入 API Key
uvicorn main:app --reload --port 8000
```

### 3. 前端

```bash
cd frontend
npm install
npm run dev   # → http://localhost:5173
```

Vite 自动将 `/api/*` 代理到后端 8000 端口。

### 4. 使用

1. 打开 http://localhost:5173
2. 注册 / 登录
3. 上传简历（PDF 或 DOCX）
4. 等待状态变为 "ready"
5. 对简历提问

---

## Docker 部署

### 生产环境

```bash
cp backend/.env.example backend/.env.prod
docker compose -f docker-compose.yml --env-file backend/.env.prod up -d
```

### 开发环境（热重载）

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml \
    --env-file backend/.env.dev up
```

### 部署架构

```mermaid
flowchart LR
    subgraph Docker [三容器编排]
        subgraph MySQL_ [MySQL 8.0]
            MYSQL[(mysql_data<br/>持久化 volume)]
        end
        subgraph Backend_ [FastAPI]
            BE_APP[uvicorn]
            BE_VOL[(uploads_data<br/>chroma_data)]
        end
        subgraph Frontend_ [nginx]
            FE_NGINX[nginx SPA<br/>API 反代<br/>SSE 反代]
        end
    end

    WWW([用户]) -->|80/443| FE_NGINX
    FE_NGINX -->|/api/*| BE_APP
    BE_APP --> MYSQL

    MySQL_ --> MYSQL
    Backend_ --> BE_VOL
```

| 服务 | 容器名 | 端口 | 说明 |
|------|--------|------|------|
| MySQL | resume-mysql | 3306 | 数据库，healthcheck |
| Backend | resume-backend | 8000 | FastAPI，多阶段构建，非 root 用户 |
| Frontend | resume-frontend | 80/443 | nginx，SPA fallback + API 反代 |

### 监控栈（可选）

```bash
docker compose -f docker-compose.yml -f docker-compose.monitor.yml up -d
```

| 服务 | 端口 | 说明 |
|------|------|------|
| Prometheus | 9090 | 指标采集（10s 间隔） |
| Grafana | 3000 | 仪表盘（HTTP/RAG/LLM/系统概览） |

---

## CI/CD

```mermaid
flowchart LR
    PUSH([Push main]) --> CI
    PUSH2([Push develop]) --> CI
    PR([PR main]) --> CI

    subgraph CI [CI Pipeline]
        LINT[pre-commit<br/>Black + Ruff + isort]
        TEST[Backend Test<br/>pytest 400+]
        BUILD[Frontend Build<br/>npm ci + build]
    end

    CI -->|main| CD_PRD
    CI -->|develop| CD_STG

    subgraph CD_PRD [CD - Production]
        PREP_P[Prepare<br/>环境判断]
        BUILD_P[Docker Buildx<br/>Build + Push]
        DEPLOY_P[SSH Deploy<br/>Pull + Health Check<br/>Auto Rollback]
        VERIFY_P[Verify<br/>HTTP + 容器状态]
    end

    subgraph CD_STG [CD - Staging]
        PREP_S[Prepare]
        BUILD_S[Docker Buildx]
        DEPLOY_S[SSH Deploy]
        VERIFY_S[Verify]
    end
```

| Job | 步骤 |
|-----|------|
| **prepare** | 环境判断（push develop→staging, push main→production） |
| **test** | 后端 pytest + 前端 lint+build（可跳过） |
| **build-and-push** | Docker Buildx 构建 + 推送阿里云镜像 |
| **deploy** | SSH 部署 → 拉取镜像 → healthcheck → auto-rollback |
| **notify** | 部署结果通知 |

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
| MCP 测试 | ~96 | Server/Client/节点/图/集成/端到端 |
| Agentic RAG 测试 | ~50 | Rewrite/Search/Generate/Reflexion |

**总计：400+ 测试，覆盖全部核心路径**

### 测试基础设施

- SQLite 内存数据库（无需 MySQL）
- `pytest-asyncio` 异步支持
- 测试中禁用限流
- Mock LLM 响应确保确定性

---

## RAG 参数调优

6 阶段实验框架，确定最优配置：

```mermaid
flowchart LR
    subgraph 调优过程 [6 阶段实验]
        P1[Phase 1<br/>chunk_size × overlap<br/>16 组] --> P2[Phase 2<br/>rrf_k × top_k<br/>6 组]
        P2 --> P3[Phase 3<br/>rerank top_k<br/>6 组]
        P3 --> P4[Phase 4<br/>reject_threshold<br/>6 组]
        P4 --> P5[Phase 5<br/>Top-3 组合验证<br/>6 组]
        P5 --> P6[Phase 6<br/>temperature<br/>4 组]
    end
    P6 --> OPT[最优配置<br/>composite +5.9%]
```

| 参数 | 原始值 | 最优值 | 变化 |
|------|--------|--------|------|
| chunk_size | 500 | **1200** | +140% |
| overlap | 50 | 50 | 不变 |
| rrf_k | 60 | **100** | +67% |
| rerank_final_top_k | 8 | **5** | -37.5% |
| reject_threshold | 0.5 | **0.3** | -40% |
| generate_temperature | 0.3 | 0.3 | 不变 |

**结果**：composite_score 提升 **+5.9%**（0.5146 → 0.5448）

```bash
cd backend
python -m rag_tuning.evaluate --baseline           # 基线
python -m rag_tuning.evaluate --phase 1            # chunk_size × overlap
python -m rag_tuning.evaluate --single chunk_size=800,overlap=100
```

完整调优结果：[backend/rag_tuning_results/](backend/rag_tuning_results/)

---

## 环境变量

```bash
# ── Chat 模型 (MiMo) ──
CHAT_API_KEY=sk-xxx
CHAT_BASE_URL=https://api.xiaomimimo.com/v1
CHAT_MODEL=mimo-v2.5

# ── Embedding 模型 (百炼) ──
EMBEDDING_API_KEY=sk-xxx
EMBEDDING_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
EMBEDDING_MODEL=text-embedding-v4

# ── Rerank 模型 (百炼) ──
RERANK_API_KEY=sk-xxx
RERANK_BASE_URL=https://<endpoint>.cn-beijing.maas.aliyuncs.com/...
RERANK_MODEL=qwen3-vl-rerank

# ── 数据库 ──
DATABASE_URL=mysql+aiomysql://root:password@localhost:3306/resume_ai

# ── JWT ──
JWT_SECRET_KEY=<python -c "import secrets; print(secrets.token_hex(32))">

# ── CORS ──
CORS_ORIGINS=http://localhost:5173,http://localhost

# ── 限流 ──
RATE_LIMIT_DEFAULT=60/minute
RATE_LIMIT_LOGIN=10/minute
RATE_LIMIT_REGISTER=5/minute
RATE_LIMIT_ASK=20/minute
```

完整模板见 [backend/.env.example](backend/.env.example)。

---

## 项目结构

```
ai-resume-analyzer/
├── backend/
│   ├── api/                    # 路由层（auth / resumes / qa / v1）
│   ├── core/                   # 基础设施（config / database / security / metrics）
│   ├── models/                 # SQLAlchemy ORM（user / resume / qa_history）
│   ├── schemas/                # Pydantic 请求/响应模型
│   ├── services/
│   │   ├── auth_service.py     # 注册 + 登录 + JWT
│   │   ├── resume_service.py   # 简历快速创建 + 后台处理
│   │   ├── rag_service.py      # 混合检索 + rerank + 生成
│   │   ├── qa_service.py       # 问答历史 CRUD
│   │   └── agentic_rag/        # ★ LangGraph Agentic RAG
│   │       ├── state.py        #   18 字段 TypedDict
│   │       ├── rewrite.py      #   查询改写 + 路由
│   │       ├── search.py       #   检索 + rerank
│   │       ├── generate.py     #   生成 + 三维度评估
│   │       ├── reflection.py   #   Reflexion 自纠正
│   │       ├── graph.py        #   直接模式 StateGraph
│   │       ├── mcp_nodes.py    #   MCP 模式节点
│   │       └── mcp_graph.py    #   MCP 模式 StateGraph
│   ├── mcp_server/             # MCP Server（5 Tool + 2 Resource）
│   ├── mcp_client/             # MCP Client（JSON-RPC 2.0）
│   ├── tests/                  # 400+ 测试
│   ├── alembic/                # 数据库迁移
│   └── rag_tuning/             # RAG 参数调优实验框架
│
├── frontend/                   # React 19 + TypeScript + Tailwind
│   └── src/
│       ├── api/                # API 封装 + JWT 管理
│       ├── context/            # AuthContext 状态管理
│       ├── components/         # Navbar / ErrorBoundary / ConfirmDialog
│       └── pages/              # LoginPage / ResumeListPage / QAPage
│
├── deploy/                     # 部署配置（docker-compose / deploy.sh）
├── monitoring/                 # Prometheus + Grafana
├── docker-compose.yml          # 生产编排
├── docker-compose.dev.yml      # 开发 override
├── docker-compose.monitor.yml  # 监控栈
└── .github/workflows/          # CI + CD 流水线
```

---

## API 文档

### 基础路径

```
生产环境：http://localhost/api/v1/
开发环境：http://localhost:8000/api/v1/
```

### 鉴权

除 `register` 和 `login` 外，所有接口需要 JWT Bearer token：

```
Authorization: Bearer <access_token>
```

### 接口列表

#### Auth

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/auth/register` | 注册 |
| POST | `/api/v1/auth/login` | 登录 |
| POST | `/api/v1/auth/refresh` | 刷新 token |

#### Resumes

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/resumes/upload` | 上传（202 异步） |
| GET | `/api/v1/resumes/` | 列表 |
| GET | `/api/v1/resumes/{id}` | 详情 + 状态 |
| DELETE | `/api/v1/resumes/{id}` | 删除 |

#### QA

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/qa/ask` | 提问（同步） |
| POST | `/api/v1/qa/ask/stream` | 提问（SSE 流式） |
| GET | `/api/v1/qa/history/{resume_id}` | 问答历史（分页 + 关键词搜索） |
| DELETE | `/api/v1/qa/history/{resume_id}` | 清空历史 |
| DELETE | `/api/v1/qa/{qa_id}` | 删除单条 |

#### MCP

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/mcp/` | JSON-RPC 2.0 端点 |

#### Health

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 健康检查（MySQL + ChromaDB 连通性） |
| GET | `/?verbose=true` | 健康检查 + 磁盘空间 |

---

## 开发指南

### 代码规范

- **后端**：Black + Ruff + isort（pre-commit 强制执行）
- **前端**：Oxlint（`npm run lint`）

### Pre-commit

```bash
pip install pre-commit
pre-commit install
```

### 本地开发

```bash
# 终端 1：后端
cd backend && .venv\Scripts\activate && uvicorn main:app --reload --port 8000

# 终端 2：前端
cd frontend && npm run dev

# 终端 3：测试
cd backend && python -m pytest tests/ -v
```
