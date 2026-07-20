"""H5: MCP Graph 跳过 Self-Reflection 节点"""

import inspect
from services.agentic_rag.mcp_graph import _route_after_evaluate as mcp_route
from services.agentic_rag.graph import _route_after_evaluate as std_route


def test_h5_mcp_graph_should_route_to_self_reflection():
    """MCP Graph 的 _route_after_evaluate 应包含 SELF_REFLECTION_NODE 路由"""
    src_mcp = inspect.getsource(mcp_route)
    src_std = inspect.getsource(std_route)

    has_reflection_in_mcp = "SELF_REFLECTION" in src_mcp
    has_reflection_in_std = "SELF_REFLECTION" in src_std

    assert has_reflection_in_std, "标准 Graph 应包含 SELF_REFLECTION 路由（前置条件）"
    assert (
        has_reflection_in_mcp
    ), "MCP Graph 应包含 SELF_REFLECTION 路由，但当前直接跳回 MCP_SEARCH_NODE 跳过了反思步骤"


def test_h5_mcp_route_retry_should_not_skip_reflection():
    """当 should_retry=True 时，MCP 路由不应直接回到 MCP_SEARCH_NODE"""
    src_mcp = inspect.getsource(mcp_route)

    # 不应该出现 "should_retry and search_round <= 2: return MCP_SEARCH_NODE"
    # 而应该是 "should_retry and search_round <= 2: return SELF_REFLECTION_NODE"
    import re

    # 注意：使用非贪婪匹配，定位"重试分支"对应的 return 目标，
    # 避免贪婪匹配一路吃到函数末尾的 return OUTPUT_NODE 而误判。
    retry_pattern = re.search(r"should_retry.*?search_round.*?return\s+(\w+)", src_mcp)
    if retry_pattern:
        target = retry_pattern.group(1)
        assert (
            "SELF_REFLECTION" in target
        ), f"重试时路由目标应为 SELF_REFLECTION_NODE，当前为 {target}"
