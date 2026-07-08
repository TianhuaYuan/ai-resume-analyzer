"""MCP Tool: rerank_results — LLM Cross-Encoder 精排。"""
import json
import logging

from mcp.types import TextContent

from mcp_server.server import mcp

logger = logging.getLogger(__name__)

_RERANK_TOP_K = 5


@mcp.tool()
async def rerank_results(
    query: str,
    chunks: str,
    top_k: int = 5,
) -> list[TextContent]:
    """对搜索结果进行 LLM Cross-Encoder 精排。

    Args:
        query: 搜索查询文本
        chunks: 候选文档块列表（JSON 字符串），每块至少包含 "text" 字段
        top_k: 返回结果数量，默认 5
    """
    from core.retry import with_retry
    from services.rag_service import llm_generate

    try:
        chunk_list = json.loads(chunks) if isinstance(chunks, str) else chunks
    except json.JSONDecodeError:
        return [TextContent(type="text", text='{"error": "Invalid chunks JSON format"}')]

    if not chunk_list:
        return [TextContent(type="text", text='{"results": [], "message": "No chunks to rerank"}')]

    top_k = max(1, min(top_k, 20))

    if len(chunk_list) <= top_k:
        results = [
            {
                "text": c.get("text", ""),
                "rerank_score": 1.0,
                "section": c.get("section", ""),
                "chunk_index": c.get("chunk_index", i),
            }
            for i, c in enumerate(chunk_list)
        ]
        return [TextContent(type="text", text=json.dumps(results, ensure_ascii=False))]

    docs_text = "\n\n".join(
        f"[文档 {i + 1}] 分类：{c.get('section', '未知')}\n{c.get('text', '')[:400]}"
        for i, c in enumerate(chunk_list)
    )

    system = (
        "你是一个文档相关性评估专家。根据查询对候选文档进行相关性打分。\n"
        "请按相关性从高到低排列文档编号，并给出 0-1 的相关性分数。\n"
        "请严格按以下 JSON 格式返回（不要包含其他文字）：\n"
        '{"results": [{"index": 0, "relevance_score": 0.95}, ...]}'
    )
    user = (
        f"查询：{query}\n\n"
        f"候选文档：\n{docs_text}\n\n"
        f"请对以上 {len(chunk_list)} 个文档进行相关性打分，返回 top {top_k} 个最相关的文档。"
    )

    try:
        raw = await with_retry(
            llm_generate,
            system,
            user,
            temperature=0.0,
            max_tokens=500,
            fallback="",
        )

        if not raw:
            raise ValueError("LLM returned empty response")

        data = json.loads(raw.strip())
        score_results = data.get("results", [])

        score_map = {}
        for item in score_results:
            idx = item.get("index", -1)
            score = item.get("relevance_score", 0.0)
            if 0 <= idx < len(chunk_list):
                score_map[idx] = max(0.0, min(1.0, float(score)))

        for i, c in enumerate(chunk_list):
            c["rerank_score"] = score_map.get(i, 0.0)

        chunk_list.sort(key=lambda c: c.get("rerank_score", 0), reverse=True)

        results = [
            {
                "text": c.get("text", ""),
                "rerank_score": round(c.get("rerank_score", 0.0), 4),
                "section": c.get("section", ""),
                "chunk_index": c.get("chunk_index", i),
            }
            for i, c in enumerate(chunk_list[:top_k])
        ]

        return [TextContent(type="text", text=json.dumps(results, ensure_ascii=False))]

    except Exception as e:
        logger.warning("rerank_results LLM failed: %s, falling back to original order", e)
        for i, c in enumerate(chunk_list):
            c["rerank_score"] = max(0.0, 1.0 - i * 0.1)

        results = [
            {
                "text": c.get("text", ""),
                "rerank_score": round(c.get("rerank_score", 0.0), 4),
                "section": c.get("section", ""),
                "chunk_index": c.get("chunk_index", i),
            }
            for i, c in enumerate(chunk_list[:top_k])
        ]

        return [TextContent(type="text", text=json.dumps(results, ensure_ascii=False))]
