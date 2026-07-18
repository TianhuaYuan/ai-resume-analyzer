"""mcp_graph 兼容 shim（阶段11 合并后）。

原 `mcp_graph.py` 的节点/边已并入 `services/agentic_rag.graph`
（见 `create_mcp_agentic_rag_graph`）。本文件保留为薄 re-export shim，
以兼容仍然 `from services.agentic_rag.mcp_graph import ...` 的测试与代码。

⚠️ 移除本 shim 前：把 importer 的 `mcp_graph` 改为 `graph` 即可。
"""
from services.agentic_rag.graph import (
    DIRECT_ANSWER_NODE,
    MCP_GENERATE_NODE,
    MCP_RERANK_NODE,
    MCP_SEARCH_NODE,
    _DIRECT_ANSWER_REPLY,
    _route_after_evaluate,
    _route_after_reflection_mcp as _route_after_reflection,
    _route_after_route_mcp as _route_after_route,
    create_mcp_agentic_rag_graph,
    direct_answer_node,
    output_node,
)
from services.agentic_rag.state import (
    EVALUATE_NODE,
    GENERATE_NODE,
    OUTPUT_NODE,
    RERANK_NODE,
    REWRITE_NODE,
    ROUTE_NODE,
    SEARCH_NODE,
    SELF_REFLECTION_NODE,
)

__all__ = [
    "create_mcp_agentic_rag_graph",
    "direct_answer_node",
    "output_node",
    "DIRECT_ANSWER_NODE",
    "MCP_SEARCH_NODE",
    "MCP_RERANK_NODE",
    "MCP_GENERATE_NODE",
    "SELF_REFLECTION_NODE",
    "EVALUATE_NODE",
    "GENERATE_NODE",
    "OUTPUT_NODE",
    "RERANK_NODE",
    "REWRITE_NODE",
    "ROUTE_NODE",
    "SEARCH_NODE",
    "_route_after_route",
    "_route_after_evaluate",
    "_route_after_reflection",
]
