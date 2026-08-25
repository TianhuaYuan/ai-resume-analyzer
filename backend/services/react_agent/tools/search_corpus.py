"""search_corpus — 公共语料检索工具（v2 阶段 2 B3）。

在三个全局公共语料集合中检索求职相关知识：
- interview_hub  公司面经（字节/华为/美团/百度…）
- interview_qa   算法/后端/大模型面试题库
- resume_samples 简历范文（各岗位写法参考）

与 search_assets（per-user 资产库）互补：本工具检索的是所有用户共享的
离线知识底座（导入自第三方数据集，asset 以 user_id=0 写入），零 API 成本、
响应稳定、结果可溯源（asset_id/version → 原文件）。面经问答/真题检索/范文
参考走这里；最新实时信息走 web_search / search_jobs_live。
"""

import logging
from typing import Literal

from pydantic import BaseModel, Field

from services.rag.corpus_retrieval import search_public_corpus
from services.react_agent.tools.base import Tool
from services.rag.evidence import adapt_evidence_list

logger = logging.getLogger(__name__)

# kind 与 clients.CORPUS_KINDS / corpus_retrieval.CorpusKind 对齐
CorpusKind = Literal["interview_hub", "interview_qa", "resume_samples"]

_KIND_LABELS: dict[str, str] = {
    "interview_hub": "公司面经库",
    "interview_qa": "面试题库",
    "resume_samples": "简历范文库",
}


class SearchCorpusArgs(BaseModel):
    kind: CorpusKind = Field(
        ...,
        description="语料类型：interview_hub=公司面经库 / interview_qa=面试题库 / resume_samples=简历范文库",
    )
    query: str = Field(
        ..., description="检索关键词，如：字节 后端 面经、TCP 三次握手、后端开发 简历写法"
    )
    top_k: int = Field(5, ge=1, le=10, description="返回条数，默认 5，范围 1-10")


class SearchCorpusTool(Tool):
    """检索离线知识库中的面经 / 面试真题 / 简历范文（公共集合，全局共享）。"""

    name = "search_corpus"
    description = (
        "检索离线知识库中的面经 / 面试真题 / 简历范文（公共集合，全局共享），"
        "返回原文段落。面经问答、真题检索、简历写法参考走这里；"
        "需要最新实时资讯时用 web_search（联网），需要岗位时用 search_jobs_live。"
    )
    args_model = SearchCorpusArgs
    category = "qa"

    async def _execute(self, **kwargs) -> str:
        kind = kwargs["kind"]
        query = (kwargs.get("query") or "").strip()
        top_k = min(kwargs.get("top_k", 5) or 5, 10)

        try:
            chunks = await search_public_corpus(kind, query, top_k=top_k)
        except Exception as e:  # 公共集合检索异常不阻断 agent（降级提示）
            logger.warning("search_corpus 检索异常 kind=%s: %s", kind, e)
            return "⚠️ 知识库检索暂时失败，请稍后重试。"

        label = _KIND_LABELS.get(kind, kind)
        if not chunks:
            return (
                f"⚠️ 在「{label}」中未找到「{query}」相关内容，"
                "可更换关键词或换个语料库（如面试题库）再试。"
            )

        # 侧信道：结构化来源供 agent_done.sources 聚合（对齐 web_search 用法）
        self.sources = adapt_evidence_list(chunks, preserve_extra=True)

        lines = [f"在「{label}」中检索到 {len(chunks)} 条相关内容："]
        for i, c in enumerate(chunks, 1):
            section = c.get("section", "正文")
            score = c.get("score", 0)
            text = c.get("text", "")
            lines.append(f"\n{i}. [{section}] (相关度: {score:.2f})\n{text}\n")
        lines.append(
            f"\n注：以上为离线知识库内容，来源可溯源（asset_id={chunks[0].get('asset_id')} 等）。"
        )
        return "\n".join(lines)
