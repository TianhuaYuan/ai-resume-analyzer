# mcp_server

MCP (Model Context Protocol) Server 实现，底层用 FastMCP 库，挂载到 FastAPI `/mcp` 路径。协议：JSON-RPC 2.0 over Streamable HTTP。

## 架构

```
transport/http.py  →  FastMCP.streamable_http_app() 生成 ASGI 子应用
                         →  create_auth_middleware() 包一层 JWT 校验
                            →  _MCPRootASGI 将 "/" 重写为 "/mcp"
                               →  mount 到 FastAPI 的 /mcp
```

## Tools（5 个）

定义在 `tools/`，通过 `@mcp.tool()` 注册。

| Tool | 文件 | 参数 | 说明 |
|------|------|------|------|
| search_knowledge_base | tools/search.py | query, resume_id, top_k(默认5,最大20) | 混合检索 + Rerank 精排，校验 resume 所有权和 ready 状态 |
| analyze_resume | tools/analyze.py | resume_id, analysis_type(summary/skills/experience) | LLM 分析简历，三种预设 Prompt |
| rerank_results | tools/rerank.py | query, chunks(JSON字符串), top_k | LLM Cross-Encoder 精排，输入不足 top_k 时直接返回 |
| generate_answer | tools/generate.py | question, context, resume_id | 基于上下文生成回答，含拒答逻辑 |
| rewrite_query | tools/rewrite.py | question, context(可选) | 调用 rag_service.rewrite_query 做指代消解 |

## Resources（2 个）

| Resource | URI | 说明 |
|----------|-----|------|
| resume_list | resume://list | 当前用户所有简历列表 |
| qa_history | qa_history://{resume_id} | 指定简历的问答历史（最近 50 条） |

## 认证

`server.py:create_auth_middleware()` 拦截 `/mcp` 路径，要求 Bearer access token（JWT sub 解析为 user_id）。`get_current_user_id()` 通过 contextvars 传递，各 tool 内直接用。

## 添加 Tool

1. 在 `tools/` 下新建文件，用 `@mcp.tool()` 装饰异步函数
2. 函数签名中的类型注解自动生成 JSON-RPC schema
3. 验证 resume 所有权：`get_current_user_id()` + 查 Resume 表
4. 异常统一 try/except 返回 `{"error": msg}` 不要抛

## 传输层

`transport/http.py`：
- `init_mcp_server()` -- 在 FastAPI lifespan 中调用，注册所有 handlers
- `get_mcp_app()` -- 惰性创建 ASGI 子应用，带认证中间件和路径重写
- `shutdown_mcp_server()` -- lifespan 关闭时清理 session
