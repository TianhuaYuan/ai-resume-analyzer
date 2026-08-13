# AI 求职智能体

基于手写 ReAct Agent 的求职助手 SaaS：上传简历后自然语言提问，Agent 通过工具调用完成简历检索、JD 匹配、模拟面试、职位搜索等求职全场景任务，返回带引用来源的答案。

## 核心能力

### Agent

- **手写 asyncio ReAct 循环**（23 个工具统一注册表）：简历检索 / JD 匹配 / 简历诊断 / 多简历对比 / STAR 改写 / 翻译 / 模拟面试 / 求职信生成 / 实时岗位搜索 / 联网搜索 / 谈薪简报 / 子代理委派 + 简历编辑器 5 个工具
- **四层记忆**：L1 工作记忆（结构化压缩）/ L2 情景（历史问答）/ L3 语义画像 / L4 长期语义记忆（向量库 + 实体增强召回）
- **实体知识图谱**：实体提取、消解、事实校验与三信号融合召回（向量 / 实体 / BM25）
- **Agent 可靠性**：坏 tool_call 错误回灌自愈、死循环检测、审批门控、失败分类定向恢复、断点续跑

### RAG 与问答

- **混合检索**：稠密向量 + BM25 关键词 → RRF 融合 → Cross-Encoder 精排
- **Agentic RAG**：LangGraph 图（改写 → 路由 → 检索 → 重排 → 生成 → 三维评估 → Reflexion 自纠错）
- **防幻觉**：prompt 约束 + 拒答阈值 + 来源段落可溯源
- **SSE 流式**：工具调用链与答案逐 token 推送

### 产品功能

- **简历编辑器**：15 个结构化模块 + 18 套模板 + AI 生成/检查/STAR 改写/翻译/整份重写 + 字段级 diff 审阅 + 多语言版本 + PDF 导出
- **求职工作台**：投递状态机 + 看板统计 + JD 评分卡 + 重复投递检测
- **面试复盘**：模拟面试（多轮问答 + 逐题评分）→ 复盘汇总 → 训练推荐
- **知识资产库**：JD / 面试记录 / 笔记归档检索
- **ATS 审计**：本地规则引擎检查简历可读性
- **管理后台**：意见箱 / 审计日志 / 用量看板 / 监控面板

### 工程化

- FastAPI + SQLAlchemy async + MySQL，RabbitMQ 异步任务，Redis 缓存/配额
- JWT 双 token 鉴权、限流、熔断、模型 fallback、Token 用量统计
- Prometheus + Grafana 监控，结构化日志 + request_id 全链路追踪
- GitHub Actions CI/CD，Docker 五容器编排（MySQL / Redis / RabbitMQ / backend / nginx）
- **测试**：后端 1700+ 用例（单元 / 集成 / Agent / MCP / 前端），前端 140+ 用例

## 技术栈

| 层级 | 技术 |
|------|------|
| Chat 模型 | DeepSeek（OpenAI 兼容） |
| Embedding / Rerank | 阿里百炼 DashScope |
| 后端 | Python / FastAPI / asyncio |
| 数据 | MySQL 8.0 + ChromaDB + Redis + RabbitMQ |
| Agent | 手写 ReAct 循环 + LangGraph（Agentic RAG 子图） |
| 协议 | MCP Server（Streamable HTTP，JWT 认证） |
| 前端 | React 19 + TypeScript + Tailwind CSS 4 |
| 部署 | Docker + nginx + GitHub Actions |

## 快速开始

前置：Python 3.11+、Node.js 18+、MySQL 8.0、DeepSeek 与百炼 API Key。

```bash
# 后端
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate   macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env.dev            # 填入 API Key，APP_ENV=dev 时读取
uvicorn main:app --reload --port 8081

# 前端
cd frontend
npm install
npm run dev                         # → http://localhost:5173
```

配置项见 [backend/.env.example](backend/.env.example)。环境通过 `APP_ENV`（dev / test / staging）选择对应 `.env.*` 文件。

## Docker 部署

```bash
# 生产
docker compose -f docker-compose.prod.yml up -d
# 监控栈（Prometheus + Grafana）
docker compose -f docker-compose.monitoring.yml up -d
```

五容器编排：MySQL 8.0 / Redis / RabbitMQ / backend（uvicorn）/ frontend（nginx SPA + SSE 反代）。生产不暴露后端与数据库端口。

## 测试

```bash
cd backend && python -m pytest tests/ -v    # 后端
cd frontend && npx vitest run               # 前端
```

后端测试用 SQLite 内存库，无需 MySQL；测试中禁用限流；LLM 调用 mock 保证确定性。

## 目录结构

```
backend/
  api/            # 路由（auth/resumes/qa/interview/job_applications/assets/feedback/admin/analytics/websocket）
  core/           # 基础设施（config/database/security/metrics/limiter/redis/rabbitmq）
  models/         # SQLAlchemy ORM
  schemas/        # Pydantic 模型
  services/
    rag/          # 分块/检索/重排/生成管线
    agentic_rag/  # LangGraph Agentic RAG + Reflexion
    react_agent/  # 手写 ReAct Agent + 23 工具 + 四层记忆
    memory/       # 长期记忆 + 实体知识图谱
    resume_builder.py / resume_parser.py / match_jd_service.py / ats_audit_service.py / ...
  mcp_server/     # MCP Server（工具 + 资源 + 认证）
  tests/          # 1700+ 用例
  alembic/        # 数据库迁移
frontend/
  src/
    api/          # API 封装 + SSE 解析
    pages/        # 页面
    components/   # 组件（chat/builder/templates/ui）
    context/      # React Context 状态管理
monitoring/       # Prometheus + Grafana 配置
scripts/          # 运维/性能脚本
```
