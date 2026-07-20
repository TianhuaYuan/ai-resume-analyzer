"""MCP Tool: generate_answer — 基于检索上下文生成答案。"""

import json
import logging

import httpx
from mcp.types import TextContent

from mcp_server.server import get_current_user_id, mcp

logger = logging.getLogger(__name__)

_GENERATE_TEMPERATURE = 0.3
# 远端 LLM 调用的总超时上限（对齐阶段1：30s 总时限 / 10s 连接）
MCP_HTTP_TIMEOUT = httpx.Timeout(30, connect=10)


@mcp.tool()
async def generate_answer(
    question: str,
    context: str,
    resume_id: str,
) -> list[TextContent]:
    """基于检索到的简历上下文生成回答。

    Args:
        question: 用户问题
        context: 检索到的上下文文本
        resume_id: 简历 ID（字符串数字）
    """
    # SEC-002：MCP 工具必须校验用户身份，缺失上下文时拒绝而非静默放行。
    try:
        _user_id = get_current_user_id()
    except LookupError:
        return [
            TextContent(
                type="text",
                text=json.dumps(
                    {"error": "authentication required: missing user context"},
                    ensure_ascii=False,
                ),
            )
        ]

    import asyncio

    from core.retry import with_retry
    from services.rag.pipeline import build_prompt, llm_generate, reject_if_low_score

    if not question.strip():
        return [TextContent(type="text", text='{"error": "question cannot be empty"}')]

    if not context.strip():
        return [
            TextContent(
                type="text",
                text=json.dumps(
                    {
                        "answer": "抱歉，简历中未提及该信息。",
                        "sources": [],
                        "rejected": True,
                    },
                    ensure_ascii=False,
                ),
            )
        ]

    chunks = _parse_context_to_chunks(context)

    if reject_if_low_score(chunks):
        return [
            TextContent(
                type="text",
                text=json.dumps(
                    {
                        "answer": "抱歉，简历中未提及该信息。",
                        "sources": [],
                        "rejected": True,
                    },
                    ensure_ascii=False,
                ),
            )
        ]

    context_texts = [c.get("text", "") for c in chunks]
    prompt = build_prompt(context_texts, question)

    try:
        answer = await asyncio.wait_for(
            with_retry(
                llm_generate,
                prompt["system"],
                prompt["user"],
                temperature=_GENERATE_TEMPERATURE,
                fallback="服务暂时不可用，请稍后重试。",
            ),
            timeout=MCP_HTTP_TIMEOUT.read,
        )

        sources = [
            {
                "chunk_index": c.get("chunk_index", i),
                "text": c.get("text", ""),
                "section": c.get("section", "未知"),
                "rerank_score": c.get("rerank_score", 0.0),
            }
            for i, c in enumerate(chunks)
        ]

        return [
            TextContent(
                type="text",
                text=json.dumps(
                    {
                        "answer": answer,
                        "sources": sources,
                        "rejected": False,
                        "chunk_count": len(chunks),
                    },
                    ensure_ascii=False,
                ),
            )
        ]

    except Exception:
        logger.exception("generate_answer failed for resume %s", resume_id)
        return [
            TextContent(
                type="text",
                text=json.dumps(
                    {
                        "answer": "服务暂时不可用，请稍后重试。",
                        "sources": [],
                        "rejected": True,
                    },
                    ensure_ascii=False,
                ),
            )
        ]


def _parse_context_to_chunks(context: str) -> list[dict]:
    import re

    pattern = r"\[段落 \d+\]\n?"
    parts = re.split(pattern, context)
    parts = [p.strip() for p in parts if p.strip()]

    if len(parts) > 1:
        return [
            {
                "text": p,
                "chunk_index": i,
                "section": "检索结果",
            }
            for i, p in enumerate(parts)
        ]

    return [
        {
            "text": context.strip(),
            "chunk_index": 0,
            "section": "检索结果",
        }
    ]
