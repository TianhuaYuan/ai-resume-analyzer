# Resume Artifact Agent v2 架构契约

> 实施快照（2026-08-26）：Phase 0 契约、Evidence 规范化、Run/Event 生命周期、ToolResult 结构化边界及 Builder Proposal/CAS 写入链路已落地并有定向回归；Phase 5 路由统一与 Phase 7 旧侧信道清理仍属于后续迁移，不应在简历中表述为“全部完成”。

状态：Phase 0 / Architecture Contract
适用范围：简历问答、简历分析与改写、职位匹配、面试准备
契约版本：`agent-v2/0.1`

本文是迁移约束，不是现状说明书。后续实现可以替换内部技术，但不得绕过本文的路由边界、核心不变量和统一概念。`backend/tests/contracts/test_agent_v2_architecture_contract.py` 提供最小可执行护栏。

## 1. 当前调用图

当前系统已有三套运行时，入口与协议尚未统一：

```mermaid
flowchart TD
    UI[Frontend chat / builder] --> API[backend/api/qa.py]
    API --> ASK[POST /qa/ask]
    API --> STREAM[POST /qa/ask/stream]
    API --> AGENT[POST /qa/ask/agent]

    ASK -->|only| AR_JSON[agentic_rag.runner for JSON]
    AR_JSON --> JSON[AnswerResponse JSON]
    STREAM -->|mode=stream| DR[rag.pipeline.ask_question_stream]
    STREAM -->|mode=agentic only| AR_STREAM[agentic_rag.runner for stream]
    AR_STREAM --> SSEA[/ask/stream agentic SSE: status/token/done]
    AGENT --> RS[react_agent.streaming]
    RS --> RL[react_agent.loop]

    AR_JSON --> RW[LangGraph rewrite]
    AR_STREAM --> RW
    RW --> ROUTE[route]
    ROUTE -->|direct_answer| DIRECT[direct_answer]
    DIRECT --> OUTPUT[output]
    ROUTE -->|search| SEARCH[search]
    SEARCH --> HSC[hybrid_search_corpus]
    HSC --> VS[(Chroma + BM25)]
    SEARCH --> RERANK[rerank]
    RERANK --> GEN[generate/evaluate/reflect]
    GEN --> OUTPUT
    DR --> RET[rewrite/retrieve/rerank/generate]
    RL --> REG[TOOL_REGISTRY]
    REG --> RT[resume/RAG/builder/web/memory tools]

    DR --> SSE1[/ask/stream mode=stream SSE: status/token/reset/done]
    RS --> SSE2[versioned agent SSE events]
    API --> DB[(QAHistory)]
    RT --> DB
    RET --> VS
```

`/qa/ask` 等待 Agentic RAG 完成后返回普通 `AnswerResponse` JSON，不是 SSE。只有 `/qa/ask/stream` 将 Direct RAG 或 `mode=agentic` 结果投影为 SSE；`/qa/ask/agent` 使用独立、带版本 envelope 的 ReAct SSE。

已确认的边界债务：

- API 直接选择具体运行时，缺少单一 use-case router。
- Direct RAG、Agentic RAG、ReAct 有不同返回形状和 SSE 事件族。
- 工具主要返回 `str`，引用通过 `tool.sources` 侧信道携带；错误、来源、降级信息没有统一 `ToolResult`。
- Agentic RAG 使用 `AgenticRAGState`，ReAct 使用消息列表、checkpoint 与 trace；没有统一 `Run`。
- 写工具可被审批门拦截，但“模型提出变更”和“应用变更”仍需明确分离为 `Proposal` 与 commit/apply。

## 2. 目标六层架构

依赖只允许自上而下。下层不得 import API、路由器或具体 UI/SSE 结构。

| 层 | 名称 | 责任 | 禁止承担 |
|---|---|---|---|
| L1 | Interface & Transport | FastAPI DTO、鉴权、限流、把 transport-neutral `Event` 投影为 HTTP/SSE、断连取消 | 定义 Event 语义、选择工具、拼 prompt、执行业务写入 |
| L2 | Use Case & Router | 将用户意图映射为单一路由，创建 `Run`，执行预算与策略 | 直接访问 Chroma、拼 provider payload |
| L3 | Runtime & Contracts | 定义 transport-neutral `Event` contract；执行 Direct Service、Direct RAG、Agentic RAG、ReAct；只通过端口调用能力 | 依赖 FastAPI/StreamingResponse、持有数据库模型、输出 SSE 字符串 |
| L4 | Capability & Tool | 稳定能力接口、工具注册、参数校验、授权、幂等与 `ToolResult` | 决定全局路由、直接向客户端发事件 |
| L5 | Artifact, Context & Evidence | Resume Artifact 聚合、版本、作用域、上下文装配、记忆、`Evidence`/`Proposal` | 调用具体 LLM provider、依赖 FastAPI |
| L6 | Infrastructure & Observability | DB/vector/LLM/provider adapter、队列、缓存、trace、metrics、event sink | 包含产品意图或简历业务决策 |

所有 runtime 共用 L2 的 `Run` 生命周期、L3 的 transport-neutral `Event` contract 与 L5 的证据语义。差异只在控制流，不在数据含义。

Event 依赖规则：canonical Event contract 归 L3，不归 L1。L2 依赖 L3 contract 记录 `route_selected` 等生命周期事实；L3 把 L4 返回的 `ToolResult` 转换为事件；L4 不依赖 Event 或 transport。L1 只消费 L3 Event，并做 HTTP JSON 或 SSE wire projection，可以增加传输头/帧但不能发明、删改业务事件语义。L3 不得 import FastAPI、`StreamingResponse` 或 SSE serializer，runtime 通过 transport-neutral event sink/yield port 输出 Event 对象。

## 3. 路由矩阵

L2 必须先选一种模式；运行中不得静默升级到成本更高或权限更大的模式。需要升级时，结束当前 `Run` 或记录显式 route transition。

| Route | 适用任务 | Retrieval | Planner / Reflection | Tools | 写入策略 | 典型例子 |
|---|---|---:|---:|---:|---|---|
| Direct Service | 输入完整、规则确定、单一业务能力 | 否 | 否 | 否 | service 自身事务；AI 不参与决策 | 读取简历、导出、确定性 ATS 规则 |
| Direct RAG | 单轮、单 scope、一次检索足够回答 | 一次受限检索 | 否 | 否 | 只读 | “这份简历有哪些 Python 项目？” |
| Agentic RAG | 需要改写 query、多轮补检、重排、评估或反思 | 自适应但仅检索域 | 有限图内决策 | 仅检索能力，不开放任意工具 | 只读 | 跨简历/JD 的证据综合与缺口分析 |
| ReAct | 目标开放、步骤未知、需要组合多个能力 | 可选 | 多轮 plan-act-observe | 白名单工具 | 只产出 `Proposal`；审批后由独立 apply 命令写入 | 生成定制简历方案并准备面试材料 |

路由优先级：能用 Direct Service 不用 LLM；能用 Direct RAG 不用 Agentic RAG；能用有限图完成不用 ReAct。复杂度由任务所需能力决定，不由 endpoint 名称或前端开关决定。

## 4. 核心不变量

1. **Artifact 是事实源**：简历、JD、面试记录均以带版本的 artifact 为权威；向量索引、prompt、memory 都是派生物。
2. **证据可追溯**：面向用户的事实性判断必须引用 `Evidence`，其 provenance 可定位到 asset/version/locator；模型生成文本不能自证。
3. **租户与 scope 隔离**：每次检索、工具调用、proposal apply 都绑定 `user_id` 与显式 artifact scope，不能依赖 prompt 中的 ID。
4. **一次请求一个 Run**：HTTP 与 SSE 只是投影；持久化、trace、usage、事件必须共享同一 `run_id`/`turn_id`。
5. **事件单调有序**：同一 Run 内 `sequence` 严格递增；恰好一个 terminal event；terminal 后不得再发业务事件。
6. **工具边界封闭**：工具参数 closed-world 校验；结果统一为 `ToolResult`；异常不得伪装为成功字符串。
7. **读写分离**：推理和检索只读。模型建议修改时只能创建 `Proposal`；验证、授权、审批、幂等 apply 是独立步骤。
8. **不静默降级**：fallback、部分检索失败、证据不足必须进入 `Run.degraded`、事件与最终响应。
9. **预算可执行**：每个 Run 有时间、轮数、token、工具次数预算；子调用消耗父预算，不能另开“隐形账本”。
10. **可取消、可审计**：客户端断连向 runtime 传播取消；已发生副作用必须留审计记录，未完成占位记录不得伪装成功。
11. **协议与 provider 解耦**：OpenAI/DeepSeek/LangGraph/Chroma 类型不得越过 adapter 泄漏到 L1-L5 公共契约。
12. **兼容迁移**：旧 endpoint 在迁移完成前保持行为；新旧路径通过 adapter 汇入统一概念，不做一次性重写。

## 5. 统一概念

以下名称与语义是规范性的；Python/Pydantic/DB 具体形态由后续 Phase 决定。

### Evidence

可验证事实的最小载体。

必需字段：`evidence_id`、`source_kind`、`asset_id`、`asset_version`、`locator`、`excerpt`、`provenance`。可选字段：`score`、`metadata`。`locator` 可表达 section/chunk/字符区间/字段路径；任何裁剪都不得丢失 provenance。

### Run

一次用户意图执行的聚合根。

必需字段：`run_id`、`turn_id`、`user_id`、`route`、`status`、`scope`、`budget`、`started_at`。结束时必须有 `finished_at`、`degraded`、`usage` 与 terminal outcome。

状态机：`created -> running`；需要审批时 `running -> awaiting_approval`。`awaiting_approval` 是非终态：批准后 `awaiting_approval -> running`，拒绝后进入 `cancelled`（用户拒绝/撤销）或 `failed`（策略拒绝/审批异常）。`succeeded | failed | cancelled` 是且仅是 terminal 状态。terminal 状态不可再迁移，只有进入 terminal 时才能设置 `finished_at` 并发出唯一 terminal event。

### Event

Run 的实时、可持久化观察结果。它是 L3 的 transport-neutral runtime contract，不是 L1/SSE contract。

统一 transport-neutral envelope：`protocol_version`、`event_id`、`event_type`、`run_id`、`turn_id`、`sequence`、`occurred_at`、`payload`。核心事件族：`run_started`、`route_selected`、`retrieval_started`、`evidence_added`、`tool_started`、`tool_finished`、`proposal_created`、`approval_required`、`answer_delta`、`run_completed`、`run_failed`、`run_cancelled`。L1 仅将该对象序列化为普通 JSON 或 `data: ...\n\n` SSE frame；wire framing 不是 Event contract 的组成部分。

### ToolResult

所有能力/工具调用的唯一返回边界。

必需字段：`call_id`、`tool_name`、`status`、`output`、`evidence`、`error`、`usage`、`started_at`、`finished_at`。`status` 为 `succeeded | failed | rejected | cancelled`。成功不得携带 error；失败不得用自然语言 success output 掩盖。`evidence` 不再使用实例属性侧信道。

### Proposal

模型建议对 Artifact 进行的、尚未生效的变更集。

必需字段：`proposal_id`、`run_id`、`target_asset_id`、`base_version`、`operations`、`rationale`、`evidence`、`risk`、`status`。状态为 `draft | awaiting_approval | approved | rejected | applied | stale`。apply 必须校验 `base_version`、权限、审批与幂等键；版本冲突转 `stale`，禁止覆盖最新内容。

概念关系：`Run` 产生有序 `Event`；retrieval/tool 贡献 `Evidence`；工具执行返回 `ToolResult`；任何写意图先形成 `Proposal`，批准后由独立应用服务生成新 Artifact version。

## 6. Phase 1-7 迁移顺序

迁移采用 strangler 方式。每阶段先加契约与 adapter，再切流量，最后删旧路径。

1. **Phase 1 — Contract types**：新增 Evidence/Run/Event/ToolResult/Proposal 模型与序列化测试；不改路由行为。
2. **Phase 2 — Evidence normalization**：统一 Direct RAG 与 Agentic RAG source/chunk 输出，保留旧响应 adapter。
3. **Phase 3 — Run and Event backbone**：创建 Run lifecycle 与 event sink；把两套 SSE 映射到统一 envelope。
4. **Phase 4 — Capability ports**：把检索、分析、builder、memory 能力收口为 L4 ports；registry 返回 `ToolResult`。
5. **Phase 5 — Router convergence**：引入 L2 router，四种模式共享策略、预算与授权；旧 endpoint 仅做兼容 adapter。
6. **Phase 6 — Proposal write path**：所有 AI 写工具改为 proposal-first；独立 approval/apply、版本冲突与审计。
7. **Phase 7 — Cutover and cleanup**：影子对比、评估、逐步切流；达到退出指标后移除旧 state/event/result 侧信道。

每阶段退出条件：契约测试通过；旧 API 回归通过；无跨层逆向 import；失败/取消/降级路径有测试；指标可按 route 与 run_id 聚合。

## 7. 明确非目标

- Phase 0 不修改任何生产逻辑、endpoint、数据库 schema、prompt、tool registry 或 SSE payload。
- 不在本轮重写 LangGraph、ReAct loop、RAG pipeline 或前端 chat。
- 不承诺 autonomous job application、自动投递、自动联系招聘方或绕过用户审批。
- 不把 memory 当事实源，不让向量库取代 Artifact 版本存储。
- 不要求所有任务都 Agent 化；Direct Service 是长期保留的一等路径。
- 不绑定单一 LLM、embedding、vector store、workflow framework 或 MCP 实现。
- 不在架构迁移中顺带改变简历评分规则、产品 UI、计费或配额政策。

## 8. Phase 0 验收

- 文档包含当前调用图、六层目标架构、四路由矩阵、核心不变量、五个统一概念、Phase 1-7 顺序与非目标。
- 契约测试仅读取本文，不导入生产模块；它验证必需章节、路由、概念与迁移顺序存在。
- 后续 Phase 若改变规范，必须先更新本文和契约测试，并记录兼容/迁移影响。

### Git 可复现说明

仓库当前 `.gitignore` 忽略 `docs/`。Phase 0 不修改用户的 `.gitignore`；提交本契约时需显式执行 `git add -f docs/architecture/agent-v2.md`，否则全新 checkout 无法复现本文。该操作只应由获授权的主流程在 commit 前执行。
