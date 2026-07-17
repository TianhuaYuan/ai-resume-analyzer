# backend/core

基础设施层，12 个文件，所有业务模块的公共依赖。FastAPI 应用在 `main.py` 中按以下顺序组装：

```
setup_logging → RequestIDMiddleware → MetricsMiddleware → register_exception_handlers → CORSMiddleware
```

## 文件职责

| 文件 | 作用 | 被谁用 |
|------|------|--------|
| config.py | Pydantic Settings，从 `.env` 读取所有配置，extra="forbid" 防止拼错 | 全局 |
| database.py | SQLAlchemy async engine（pool_size=10, pool_recycle=3600），`get_db` 作为 FastAPI 依赖 | api/ 路由, services/ |
| security.py | bcrypt 哈希 + JWT（access 30min / refresh 7 天），用 PyJWT（阶段11 由 python-jose 迁移） | api/auth.py, mcp_server/ |
| cache.py | Embedding 向量内存缓存，sha256 → vector，LRU 5000 条，按 resume_id 批量淘汰 | services/rag_service.py |
| retry.py | `with_retry(fn, max_retries=3, base_delay=1.0, fallback=None)`，编程错误(TypeError/ValueError 等)直接抛，不重试 | services/ 各模块 |
| trace.py | `StepTimer`，`await timer.run("search", hybrid_search(...))` 收集每一步耗时 | services/agentic_rag/ |
| rag_params.py | `RagParams` dataclass，13 个可调参数 + `validate()` 冲突检测 + 各阶段实验网格 | rag_tuning/ |
| limiter.py | slowapi Limiter 实例，默认 60/min，路由装饰器覆盖特定值 | api/ 路由 |
| exceptions.py | `AppException(status_code, detail, error_code)` + 3 个异常处理器，统一 JSON 格式带 request_id | api/, services/ |
| logging_config.py | JSON 格式化日志，PII 脱敏（邮箱/手机/身份证/Token），采样率 `LOG_SAMPLE_RATE` | main.py 最先导入 |
| request_id.py | `RequestIDMiddleware`，X-Request-ID 头传递 + contextvars 跨协程追踪 | main.py 中间件 |
| metrics.py | Prometheus 4 层指标（HTTP/RAG/LLM/系统），`/metrics` 端点，端点归一化（/resumes/{id} 规约为 /resumes/{id}） | main.py, services/ |

## 约定

- 新增环境变量：在 config.py 的 Settings 类加字段，`.env.example` 同步更新
- 自定义业务异常：继承 AppException，在 api 层抛出，全局处理器自动捕获
- 全链路追踪：每个请求自动分配 request_id，响应头返回 X-Request-ID，JSON 日志包含 trace_id/span_id
- Prometheus 指标：`metrics.py` 中 `track_llm_call` 装饰器 + `timer_context` 上下文管理器供 service 层使用

## 实验框架集成

`rag_params.py` 是连接生产代码和调优实验的桥梁。生产环境用默认参数，实验时通过 `dataclasses.replace(params, chunk_size=1200)` 覆盖。
