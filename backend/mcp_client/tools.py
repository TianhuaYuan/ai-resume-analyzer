"""MCP 工具调用封装：mcp_search / mcp_rerank / mcp_generate / mcp_answer（T14）。"""

import json
import logging

from mcp_client.client import MCPClientError, get_mcp_client

logger = logging.getLogger(__name__)


async def mcp_search(
    query: str,
    resume_id: int | None = None,
    top_k: int = 20,
    scope: dict[str, list[int]] | None = None,
    filters: dict | None = None,
) -> list[dict]:
    """调 MCP search_index（T13 泛化）。

    向后兼容：仅传 resume_id 时自动包成 scope={resume: [resume_id]}；
    scope 显式传入时优先使用 scope。
    """
    client = await get_mcp_client()
    await client.connect()

    if scope is None:
        if resume_id is None:
            logger.error("mcp_search: must provide scope or resume_id")
            return []
        scope = {"resume": [resume_id]}

    arguments: dict = {
        "query": query,
        "scope": json.dumps(scope, ensure_ascii=False),
        "top_k": top_k,
    }
    if filters:
        arguments["filters"] = json.dumps(filters, ensure_ascii=False)

    try:
        result = await client.call_tool("search_index", arguments)
    except MCPClientError as e:
        logger.error("MCP search_index failed: %s", e)
        return []

    return _parse_tool_result(result)


async def mcp_answer(
    query: str,
    scope: dict[str, list[int]],
    top_k: int = 5,
) -> dict:
    """调 MCP answer_from_index（T14 原子工具：检索+反思+生成一次完成）。

    降级策略沿用：失败返回拒答话术 + 空 sources。
    """
    client = await get_mcp_client()
    await client.connect()

    try:
        result = await client.call_tool(
            "answer_from_index",
            {
                "query": query,
                "scope": json.dumps(scope, ensure_ascii=False),
                "top_k": top_k,
            },
        )
    except MCPClientError as e:
        logger.error("MCP answer_from_index failed: %s", e)
        return {
            "answer": "服务暂时不可用，请稍后重试。",
            "sources": [],
            "eval_score": 0.0,
            "reflection_round": 0,
        }

    return _parse_tool_result(result)


async def mcp_rerank(
    query: str,
    chunks: list[dict],
    top_k: int = 5,
) -> list[dict]:
    client = await get_mcp_client()
    await client.connect()

    chunks_json = json.dumps(chunks, ensure_ascii=False)

    try:
        result = await client.call_tool(
            "rerank_results",
            {
                "query": query,
                "chunks": chunks_json,
                "top_k": top_k,
            },
        )
    except MCPClientError as e:
        logger.error("MCP rerank_results failed: %s", e)
        return [
            {**c, "rerank_score": c.get("rerank_score", 0.5)}
            for c in chunks[:top_k]
        ]

    return _parse_tool_result(result)


async def mcp_generate(
    question: str,
    chunks: list[dict],
    resume_id: int,
) -> dict:
    client = await get_mcp_client()
    await client.connect()

    context = "\n\n".join(f"[段落 {i + 1}] {c.get('text', '')}" for i, c in enumerate(chunks))

    try:
        result = await client.call_tool(
            "generate_answer",
            {
                "question": question,
                "context": context,
                "resume_id": str(resume_id),
            },
        )
    except MCPClientError as e:
        logger.error("MCP generate_answer failed: %s", e)
        return {
            "answer": "服务暂时不可用，请稍后重试。",
            "sources": [],
            "rejected": True,
        }

    return _parse_tool_result(result)


def _parse_tool_result(result: dict) -> dict | list:
    contents = result.get("content", [])
    if not contents:
        return {}

    for item in contents:
        if item.get("type") == "text":
            text = item.get("text", "")
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return {"raw": text}

    return {}
