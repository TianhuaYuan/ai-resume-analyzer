# AI 简历分析

上传一份简历，用自然语言提问——"这人 Python 写了多久？""有没有大厂实习？"——系统从简历中检索相关段落，生成回答并附上原文出处。

## 解决了什么问题

HR 筛简历时面对几十份 PDF，想快速定位关键信息——"谁做过微服务项目？谁在创业公司待过？"——传统做法是全文搜索关键词，但"分布式系统"搜不到"Kafka + Zookeeper"，"管理经验"也搜不到"带过 3 个人"。

RAG（检索增强生成）的思路是：将简历分成段落，转为向量存入向量库，提问时用语义匹配而非关键词匹配。用户问"管理经验"，系统能命中"带领一个 5 人小组"——即使原文未出现"管理"二字。

## 技术栈

| 层级 | 选型 | 为什么选它 |
|------|------|-----------|
| Chat | DeepSeek V4 | 性价比最高的国产大模型，OpenAI 兼容协议 |
| Embedding | 百炼 text-embedding-v4 | 中文检索效果比 OpenAI 的好，1024 维 |
| Rerank | 百炼 gte-rerank | 专有 API，比通用 Chat 做精排便宜且快 |
| 向量库 | ChromaDB | 轻量，本地跑，不需要搭 Milvus 集群 |
| 后端 | FastAPI + SQLAlchemy async | Python 生态里做 AI 应用的首选 |
| 前端 | React 19 + TypeScript + Tailwind | 单页应用，文件上传 + SSE 流式渲染 |
| 数据库 | MySQL 8.0 | 通用关系型，存用户、简历元数据、问答历史 |

## 架构

```
浏览器 (localhost:5173)
    │
    ▼
Vite 开发服务器
    │
    │ /api/* 代理到后端
    ▼
FastAPI (localhost:8000)
    ├─ 鉴权 (JWT access + refresh token)
    ├─ 简历 CRUD (PDF/DOCX 解析 → 异步处理 → 前端轮询)
    └─ 问答 (Query 改写 → 混合检索 → Rerank → 防幻觉 → SSE 流式)
        │
        ├── MySQL (用户 / 简历元数据 / 问答历史)
        ├── ChromaDB (向量存储，每份简历一个 collection)
        └── LLM API (DeepSeek Chat + 百炼 Embedding + 百炼 Rerank)
```

## RAG 问答流程

一个提问经过 5 个步骤返回结果：

1. **Query 改写** — "他什么时候毕业的？"→ 补全为"这个人的毕业时间是什么时候？"。用 DeepSeek 做指代消解，失败就用原问题兜底。
2. **混合检索** — 同时跑两条路：Dense 向量检索（语义相似）+ BM25 关键词检索（精确匹配）。结果用 RRF 算法融合，粗排取前 20 条。
3. **Rerank 精排** — 粗排的 20 条用 LLM Cross-Encoder 重新打分，压到 5 条。每个段落和问题的相关性从 0~1 打分，JSON 解析做了三层防御。
4. **拒答判断** — 5 条里最相关的那个如果得分不到 0.3，说明简历里确实没有——直接返回"未找到相关信息"。
5. **生成回答** — 把精选段落拼成 prompt，加系统指令约束"只能根据提供的简历内容回答"，发给 DeepSeek 生成。支持两种模式：
   - 同步：等完整答案，3 次指数退避重试（1s → 2s → 4s）→ 失败给降级话术
   - 流式：SSE 逐 token 推送，前端打字机效果渲染，流中断自动降级到同步

每步均有全链路耗时 trace，便于定位性能瓶颈。

## 防幻觉策略

RAG 应用的核心挑战是 LLM 可能编造简历中不存在的信息。从三个层面约束：

- **Prompt 层**：System Prompt 明确约束"你只能根据以下简历内容回答，不要编造信息"
- **Rerank 层**：相关性分数低于 0.3 直接拒答，不让 LLM 猜
- **溯源层**：每个回答附带来源段落，用户可以原文对照

## 快速启动

### 环境要求

- Python 3.11+
- Node.js 18+
- MySQL 8.0

### 后端

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate       # Windows；Mac/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env         # 填入 API Key
uvicorn main:app --reload --port 8000
```

### 前端

```bash
cd frontend
npm install
npm run dev                  # Vite 启动，http://localhost:5173
```

Vite 自动把 `/api/*` 代理到后端 8000 端口，不用配 CORS。

### 环境变量

```bash
# Chat 模型（DeepSeek）
CHAT_API_KEY=sk-xxx
CHAT_BASE_URL=https://api.deepseek.com/v1
CHAT_MODEL=deepseek-v4-pro

# Embedding 模型（百炼）
EMBEDDING_API_KEY=sk-xxx
EMBEDDING_MODEL=text-embedding-v4

# Rerank 模型（百炼）
RERANK_API_KEY=sk-xxx

# 数据库
DATABASE_URL=mysql+aiomysql://root:password@localhost:3306/resume_db

# JWT
JWT_SECRET_KEY=              # python -c "import secrets; print(secrets.token_hex(32))"

# CORS
CORS_ORIGINS=http://localhost:5173,http://localhost
```

## 项目结构

```
backend/
├── api/          # 路由：auth, resumes, qa
├── core/         # 配置、数据库连接池、JWT、embedding 缓存、重试器、全链路 trace
├── models/       # SQLAlchemy: User, Resume, QAHistory
├── schemas/      # Pydantic 请求/响应校验
├── services/     # 业务逻辑：RAG 流水线全在这
├── utils/        # PDF/DOCX 解析
└── main.py       # FastAPI 入口

frontend/
└── src/
    ├── api/      # fetch 封装（JWT 自动携带 + 401 静默刷新）
    ├── context/  # AuthContext（React Context 管理登录状态）
    ├── components/  # Navbar
    └── pages/    # LoginPage, ResumeListPage, QAPage（流式问答 + 打字机渲染）
```

## 工程实现要点

**后端韧性**

- 所有 LLM 调用带指数退避重试（1s → 2s → 4s），三次失败后使用降级话术，保证接口不出 500
- Embedding 走 sha256 内存缓存，相同文本不重复调用 API
- Rerank 的 JSON 解析做三层防御：标准 JSON → 正则提取 → 默认值兜底，确保格式崩了也不会中断流水线
- 流式生成中断时自动降级为非流式同步调用

**AI 工程**

- 分块策略：先按简历节段标题切分（教育背景/工作经历/项目经验），超长节段再按 `\n\n` → `\n` → `。` 优先级递归细分
- 混合检索：Dense 向量 + BM25 关键词，RRF 融合（k=60）
- 评估体系：50 条 Golden Set 标注数据集 + 4 组 Baseline 对照实验，量化检索和生成质量

**数据层**

- MySQL + SQLAlchemy async + Alembic 迁移
- ChromaDB 本地持久化，每份简历独立 collection
- JWT 双 token 机制（access 30min + refresh 7 天），401 自动静默刷新

**前端**

- React 19 + TypeScript，SSE ReadableStream 逐 token 解析，打字机效果渲染
- 文件上传异步处理 + 前端轮询状态（1.5s 间隔）
