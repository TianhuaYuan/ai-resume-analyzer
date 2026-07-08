# services/agentic_rag

LangGraph StateGraph 实现的 Agentic RAG 工作流。两种模式：直连（rag_service.py 直接调用 API）和 MCP（通过 MCP 客户端调用）。各节点函数签名统一为 `async (state: AgenticRAGState) -> dict`。

## State 结构

`state.py` 定义了 25 个字段的 TypedDict。核心字段：

| 字段 | 类型 | 写入节点 | 说明 |
|------|------|----------|------|
| question | str | 入口 | 原始用户问题 |
| rewritten_query | str | rewrite | LLM 指代消解后的查询 |
| route_decision | str | route | "search" / "direct_answer" |
| chunks | list[dict] | search | 检索结果块，每块含 text/section/chunk_index/rerank_score |
| answer | str | generate | LLM 生成的答案文本 |
| eval_score | float | evaluate | 三维度复合评分（0-1） |
| should_retry | bool | evaluate | eval_score < 0.6 时置 True |
| supplement_queries | list[str] | self_reflection | 反思后生成的补充查询 |
| trace | dict | 所有节点 | 全链路耗时 + 元数据 |

## 直连模式（graph.py）

9 个节点 + 4 条条件边：

```
START → rewrite → route ──"direct_answer"──→ direct_answer → output → END
                         └──"search"──→ search → rerank → generate → evaluate
                                                                        │
                                                          ┌─────────────┘
                                                          ▼
                                                   self_reflection → search(再次)
                                                          │
                                                    (最多 2 轮 Reflexion)
```

路由决策：
- `rewrite.py:_is_trivial_greeting()` 先做关键词匹配（你好/Hi/谢谢 等短文本），不消耗 LLM
- `_classify_route()` 调用 LLM 判断复杂问题，temperature=0.0，fallback="search"
- route 产生 "direct_answer" 时，直接返回模板问候语，零 LLM 开销

Reflexion 循环：
- `generate.py:evaluate_node` 调用 LLM-as-Judge，三维度加权（completeness 0.4 + accuracy 0.4 + source_credibility 0.2）
- score < 0.6 触发 `self_reflection_node`，分析缺失信息，生成补充查询
- 最多 2 轮 Reflexion，超限后强制输出
- `reflection.py` 有 LLM JSON 解析失败后的正则回退解析

## MCP 模式（mcp_graph.py）

结构相同，但 search/rerank/generate 三个节点替换为 MCP 调用：

```
mcp_search_node → mcp_rerank_node → mcp_generate_node
```

MCP 节点通过 `mcp_client/` 发 JSON-RPC 2.0 请求到自身 `/mcp` 端点。错误处理：
- MCP 调用失败时降级为默认排序（rerank）或模板回答（generate）
- 无 Reflexion（MCP 模式 evaluate 失败直接重试 search）

## 入口

外部通过 `services/rag_service.py` 的 `run_agentic_rag()` / `run_mcp_agentic_rag()` 调用，非直接调用 graph。
