# services/agentic_rag

LangGraph StateGraph 实现的 Agentic RAG 工作流。标准模式：graph.py 直连检索/生成节点（search/rerank/generate 直连 API）。MCP 调用走 `mcp_server/tools/answer.py` 原子工具（原 mcp_graph/mcp_nodes 已在 T14 退役删除）。各节点函数签名统一为 `async (state: AgenticRAGState) -> dict`。

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

## 入口

外部经 `services/agentic_rag/runner.py` 的 `run_answer_from_index` 调用（聚合检索+反思+生成）；
直接运行图用 `graph.create_agentic_rag_graph()`。
