"""工具注册表 — unified 21 工具（v2 合并 qa + builder，M2 加 search_jobs_live，A1 加 web_search，I3 加 negotiation_brief）。

创建骨架 + 注册表；T12/T13/T28 填充 _execute 实现。
v2 统一 Agent 编辑器：合并 qa(16) + builder(5) → unified(21)。
M1 移除 recommend_jobs（静态爬虫岗位管线）；M2 以 search_jobs_live（实时搜索）替代。
v2 A1 新增 web_search（博查联网搜索：面经/薪资/公司评价/招聘资讯）。
阶段4 I3 新增 negotiation_brief（谈薪简报）。

分类：
  qa (16):      search_resume / jd_match / diagnose_resume / compare_resumes
                rewrite_star / translate / interview_coach / search_jobs_live
                web_search / negotiation_brief 等
  builder (5):  generate_module / check_module / modify_module
                rewrite_resume / ask_info
  unified (21): qa + builder 全部工具（/ask/agent 统一使用）
"""

import asyncio
import hashlib
import json as _json
import json as _json_std
import logging
import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import AsyncSessionLocal
from core.config import settings
from services.analyze_service import analyze_resume
from services.match_jd_service import match_jd
from services.rag.asset_source import ASSET_TYPE_RESUME
from services.rag.clients import knowledge_collection_name
from services.rag.ensure_indexed import ensure_indexed
from services.rag.evidence import adapt_evidence_list
from services.rag.pipeline import (
    LLMToolResponse,
    ToolCall,
    llm_generate,
    llm_generate_with_tools,
    llm_generate_with_tools_stream,
)
from services.rag.retrieval import hybrid_search, hybrid_search_corpus, rerank
from services.react_agent.tools.base import Tool, ToolFailed, ToolRetryError, format_validation_error
from services.react_agent.tools.negotiation_brief import NegotiationBriefTool
from services.react_agent.tools.search_corpus import SearchCorpusTool
from services.react_agent.tools.search_jobs_live import SearchJobsLiveTool
from services.react_agent.tools.spawn import SpawnTool  # 子代理委派
from services.react_agent.tools.web_search import WebSearchTool
from services.resume_builder import get_resume_with_modules
from services.resume_service import compare_resumes
from utils.privacy import sanitize_resume_module_for_ai

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# QA 工具参数模型 (7)
# ═══════════════════════════════════════════════════════════


class SearchResumeArgs(BaseModel):
    resume_id: int = Field(..., description="简历 ID")
    query: str = Field(..., description="检索查询词")


class JDMatchArgs(BaseModel):
    resume_id: int = Field(..., description="简历 ID")
    jd_text: str = Field(..., description="JD 原文")


class DiagnoseResumeArgs(BaseModel):
    resume_id: int = Field(..., description="简历 ID")


class CompareResumesArgs(BaseModel):
    resume_ids: list[int] = Field(..., min_length=2, max_length=6, description="要对比的简历 ID 列表（当前基准简历 + 1-5 个对比简历）")


class RewriteStarArgs(BaseModel):
    resume_id: int = Field(..., description="简历 ID")
    target_position: str | None = Field(None, description="目标岗位（可选，用于定向优化）")


class TranslateArgs(BaseModel):
    resume_id: int = Field(..., description="简历 ID")
    target_lang: str = Field(..., description="目标语言（如 en/ja）")


class InterviewCoachArgs(BaseModel):
    resume_id: int | None = Field(
        None, description="简历 ID（新开模拟面试时必传；继续已有面试时可不传）"
    )
    target_position: str | None = Field(
        None, description="目标岗位（新开模拟面试时必传；继续已有面试时可不传）"
    )
    answer: str | None = Field(
        None,
        description="用户对当前问题的回答。面试进行中用户回答后，必须把回答原文传到这里以推进面试",
    )
    action: str = Field(
        "next",
        description=(
            "操作：next=记录回答并出下一题/追问（默认）；skip=跳过当前题不出评分；"
            "end=结束面试并自动评分；start=强制重新开始一场新的模拟面试"
        ),
    )


# ═══════════════════════════════════════════════════════════
# Builder 工具参数模型 (5)
# ═══════════════════════════════════════════════════════════


class GenerateModuleArgs(BaseModel):
    resume_id: int = Field(..., description="简历 ID")
    module_type: str = Field(..., description="模块类型（如 basic_info/education/work_experience）")
    prompt: str = Field("", description="用户补充说明")
    few_shot: str | None = Field(None, description="参考范文文本（few-shot，仅作结构与表述参照）")


class CheckModuleArgs(BaseModel):
    resume_id: int = Field(..., description="简历 ID")
    module_type: str = Field(..., description="模块类型")


class ModifyModuleArgs(BaseModel):
    resume_id: int = Field(..., description="简历 ID")
    module_type: str = Field(..., description="模块类型")
    instruction: str = Field(..., description="修改指令")


class RewriteResumeArgs(BaseModel):
    resume_id: int = Field(..., description="简历 ID")
    mode: str = Field(
        "generate", description="模式：generate（空简历生成）或 optimize（现有内容优化）"
    )
    target_position: str | None = Field(None, description="目标岗位")
    few_shot: str | None = Field(None, description="参考范文文本（few-shot，仅作结构与措辞参照）")


class AskInfoArgs(BaseModel):
    resume_id: int = Field(..., description="简历 ID")
    question: str = Field(..., description="追问问题")


# ═══════════════════════════════════════════════════════════
# QA 工具骨架 (7) — T12/T13 填充 _execute
# ═══════════════════════════════════════════════════════════


class SearchResumeTool(Tool):
    name = "search_resume"
    description = "在简历中检索与查询相关的段落，返回 top5 结构化结果（文本+分节+评分）"
    args_model = SearchResumeArgs
    category = "qa"

    async def _execute(self, **kwargs) -> str:
        resume_id = kwargs.get("resume_id")
        query = kwargs.get("query")

        # #4: 草稿/未就绪简历检索会失败，前置给出明确提示
        resume = await self._get_resume(resume_id)
        if resume is None:
            return "⚠️ 简历不存在或无权访问，请确认当前选中的简历。"
        if resume.status == "draft":
            return "⚠️ 这份简历还是草稿（未完成），请先在编辑器中填写内容并「保存并完成」后再检索。"
        if resume.status != "ready":
            return f"⚠️ 简历当前状态为 {resume.status}，暂不可检索。"

        # 懒索引：首次检索 / 内容变更后触发重建
        await ensure_indexed(
            self.db,
            user_id=self.user_id,
            asset_id=resume_id,
            asset_type=ASSET_TYPE_RESUME,
            collection=knowledge_collection_name(self.user_id),
        )

        chunks = await hybrid_search(self.user_id, resume_id, query, top_k=20)
        if not chunks:
            return "未找到相关内容。"

        reranked = await rerank(query, chunks, top_k=5)
        if not reranked:
            return "未找到相关内容。"

        # 填充结构化来源（ : 用于 agent_done.sources 聚合去重）
        self.sources = adapt_evidence_list(reranked, preserve_extra=True)

        lines = [f"找到 {len(reranked)} 条相关结果：\n"]
        for i, chunk in enumerate(reranked, 1):
            section = chunk.get("section", "未知")
            text = chunk.get("text", "")
            score = chunk.get("rerank_score", chunk.get("score", 0))
            lines.append(f"{i}. [{section}] (评分: {score:.2f})\n{text}\n")

        return "\n".join(lines)


class GetResumeContentArgs(BaseModel):
    resume_id: int = Field(..., description="简历 ID")


class GetResumeContentTool(Tool):
    """T12：整文直读实时源（D3 工作区解耦）。

    事实性/定向问题优先用本工具（读 live parsed_text/模块），比检索更准、永远新鲜。
    """

    name = "get_resume_content"
    description = "读取简历当前完整内容（实时源，含草稿编辑态）。事实性/定向问题优先用本工具，检索只在模糊/跨模块问题时用。"
    args_model = GetResumeContentArgs
    category = "qa"

    async def _execute(self, **kwargs) -> str:
        resume_id = kwargs["resume_id"]
        resume = await self._get_resume(resume_id)
        if resume is None:
            return "⚠️ 简历不存在或无权访问。"

        # 优先读实时模块（resume_modules 表 = 最新编辑态）。
        # 修复：之前优先 parsed_text —— 草稿编辑后（未 complete）parsed_text 是旧快照，
        # 工具读到过期内容（「检索的简历不是最新的」根因）。modules 为空才落 parsed_text。
        from services.resume_builder import get_resume_with_modules

        _, modules = await get_resume_with_modules(self.db, self.user_id, resume_id)
        if modules:
            lines = []
            for m in modules:
                if not m.content:
                    continue
                sanitized = (
                    sanitize_resume_module_for_ai(m.module_type, m.content)
                    if isinstance(m.content, dict)
                    else m.content
                )
                lines.append(
                    f"【{m.module_type}】{_json.dumps(sanitized, ensure_ascii=False)}"
                )
            body = "\n".join(lines)
            if body:
                truncated = body[:16000]
                suffix = "\n…（内容较长已截断）" if len(body) > 16000 else ""
                return (
                    f"简历《{resume.filename}》内容（实时模块视图，含草稿编辑态）：\n"
                    f"{truncated}{suffix}"
                )

        text = (resume.parsed_text or "").strip()
        if text:
            return f"简历《{resume.filename}》内容（约 {len(text)} 字）：\n{text[:16000]}"
        return "⚠️ 简历内容为空。"


class SearchAssetsArgs(BaseModel):
    query: str = Field(..., description="检索查询词")
    asset_type: str = Field("resume", description="资产类型（resume/jd/interview/note）")
    asset_ids: list[int] | None = Field(
        None,
        description="要检索的资产 ID 列表；不传则跨该用户全部知识库检索（含归档的 JD/面试记录/笔记）",
    )


class SearchAssetsTool(Tool):
    """T12：知识资产库检索。"""

    name = "search_assets"
    description = "在知识资产库（可跨多份简历/JD/面试记录）中检索与查询语义相关的段落，返回 top5 结构化结果（含来源资产与版本）。"
    args_model = SearchAssetsArgs
    category = "qa"

    async def _execute(self, **kwargs) -> str:
        query = kwargs["query"]
        asset_type = kwargs["asset_type"]
        asset_ids = kwargs.get("asset_ids") or []
        # 未指定资产 ID → 全库检索该用户全部知识资产（含归档内容）；
        # 指定则按 (asset_type, asset_ids) 范围过滤
        scope = {asset_type: asset_ids} if asset_ids else {}
        chunks = await hybrid_search_corpus(self.user_id, scope, query, top_k=20)
        if not chunks:
            return "未找到相关内容。"

        reranked = await rerank(query, chunks, top_k=5)
        if not reranked:
            return "未找到相关内容。"

        self.sources = adapt_evidence_list(reranked, preserve_extra=True)

        lines = [f"找到 {len(reranked)} 条相关结果：\n"]
        for i, c in enumerate(reranked, 1):
            asset = c.get("asset_id", "?")
            ver = c.get("version", "?")
            score = c.get("rerank_score", c.get("score", 0))
            lines.append(
                f"{i}. [资产{asset}:v{ver}] ({c.get('section', '未知')}) (评分: {score:.2f})\n{c.get('text', '')}\n"
            )
        return "\n".join(lines)


class AnswerFromIndexArgs(BaseModel):
    question: str = Field(..., description="问题")
    resume_id: int = Field(..., description="当前简历 ID")


class AnswerFromIndexTool(Tool):
    """T12：agentic RAG 深度检索回答。"""

    name = "answer_from_index"
    description = "对知识资产库进行深度检索回答（agentic RAG：改写→检索→重排→生成→反思）。适合复杂/跨模块/需要依据的问题。"
    args_model = AnswerFromIndexArgs
    category = "qa"

    async def _execute(self, **kwargs) -> str:
        question = kwargs["question"]
        resume_id = kwargs["resume_id"]

        from services.agentic_rag.runner import run_answer_from_index

        result = await run_answer_from_index(
            user_id=self.user_id,
            scope={ASSET_TYPE_RESUME: [resume_id]},
            question=question,
        )
        answer = result["answer"]
        if not answer:
            return "未能生成答案，请重试。"
        self.sources = adapt_evidence_list(result["sources"], preserve_extra=True)
        return answer


class SaveMemoryArgs(BaseModel):
    snippet: str = Field(..., description="要记住的原子事实（一条独立、可检索的记忆）")
    memory_type: str = Field(
        "episodic", description="类型：episodic（原始情节）/ semantic（提炼后的语义事实）"
    )
    importance: float = Field(0.5, description="重要度 0-1")


class SaveMemoryTool(Tool):
    """T15：把用户事实/偏好/决策沉淀为长期记忆（L4）。"""

    name = "save_memory"
    description = "把一条用户事实/偏好/决策沉淀为长期记忆（L4 语义记忆），跨会话可召回。用户在对话中透露的重要偏好/目标/决定时使用。"
    args_model = SaveMemoryArgs
    category = "qa"

    async def _execute(self, **kwargs) -> str:
        snippet = kwargs["snippet"]
        memory_type = kwargs["memory_type"]
        importance = kwargs["importance"]

        from services.memory.memory_store import save_memory

        mid = await save_memory(
            user_id=self.user_id,
            snippet=snippet,
            memory_type=memory_type,
            importance=importance,
        )
        return f"✅ 已记住：{snippet[:80]}{'…' if len(snippet) > 80 else ''}（记忆 {mid[:8]}）"


class RecallMemoryArgs(BaseModel):
    query: str = Field(..., description="要召回的语义查询")
    top_k: int = Field(3, ge=1, le=10, description="返回条数")


class RecallMemoryTool(Tool):
    """T15：语义召回用户长期记忆（L4），用于跨会话一致性与偏好参考。"""

    name = "recall_memory"
    description = (
        "按语义召回用户的长期记忆片段（L4），用于跨会话一致性、参考用户偏好/目标/历史决策。"
    )
    args_model = RecallMemoryArgs
    category = "qa"

    async def _execute(self, **kwargs) -> str:
        query = kwargs["query"]
        top_k = kwargs["top_k"]

        from services.memory.memory_store import recall_memory

        items = await recall_memory(user_id=self.user_id, query=query, top_k=top_k)
        if not items:
            return "没有相关记忆。"

        lines = [f"找到 {len(items)} 条相关记忆：\n"]
        for i, item in enumerate(items, 1):
            lines.append(f"{i}. [{item['score']:.2f}] {item['text']}\n")
        return "\n".join(lines)


class JDMatchTool(Tool):
    name = "jd_match"
    description = "将简历与 JD（岗位描述）匹配，分析匹配度和差距（jd_analyze 已并入）"
    args_model = JDMatchArgs
    category = "qa"

    async def _execute(self, **kwargs) -> str:
        resume_id = kwargs.get("resume_id")
        jd_text = kwargs.get("jd_text")

        # #4: 草稿/未就绪简历匹配会失败，前置给出明确提示
        resume = await self._get_resume(resume_id)
        if resume is None:
            return "⚠️ 简历不存在或无权访问，请确认当前选中的简历。"
        if resume.status == "draft":
            return "⚠️ 这份简历还是草稿（未完成），请先在编辑器中填写内容并「保存并完成」后再匹配。"
        if resume.status != "ready":
            return f"⚠️ 简历当前状态为 {resume.status}，暂不可匹配。"

        try:
            result = await match_jd(
                db=self.db,
                user_id=self.user_id,
                resume_id=resume_id,
                jd_text=jd_text,
            )
            analysis = result.get("analysis", "分析结果为空")
            # P1-C: 追加结构化 JSON 块供前端提取渲染 JDMatchReport 卡片
            # LLM 读 analysis 正常总结；前端从 event.detail 提取 <match_result> 块
            scores = result.get("scores") or {}
            structured = {
                "analysis": analysis,
                "scores": scores,
                # E3: 四维 JD fit（technical/experience/behavioral/career）
                "dims": result.get("dims", {}),
                "matched_keywords": result.get("matched_keywords", []),
                "missing_keywords": result.get("missing_keywords", []),
                "gaps": result.get("gaps", []),
            }

            # I1: 6-block 求职评估报告（LLM 生成 + 模板兜底）+ 落库
            # 仅当结构化匹配成功（有 scores）才生成；best-effort：失败不阻断匹配主流程
            report_block = ""
            if result.get("scores"):
                try:
                    from services.match_jd_service import build_6_block_report, save_jd_report

                    report = await build_6_block_report(
                        parsed_text=resume.parsed_text or "",
                        jd_text=jd_text,
                        fit=structured,
                        user_id=self.user_id,
                    )
                    structured["report"] = report
                    if self.db is not None:
                        await save_jd_report(
                            db=self.db,
                            user_id=self.user_id,
                            resume_id=resume_id,
                            jd_text=jd_text,
                            report=report,
                            overall=scores.get("overall", 0),
                            band=scores.get("band", "needsWork"),
                        )
                    report_block = (
                        "\n\n<jd_report>"
                        + _json_std.dumps(report, ensure_ascii=False)
                        + "</jd_report>"
                    )
                except Exception as e:
                    logger.warning("JDMatchTool 6-block 报告生成失败（忽略）: %s", e)

            structured_block = (
                "\n\n<match_result>"
                + _json_std.dumps(structured, ensure_ascii=False)
                + "</match_result>"
            )
            matched = structured["matched_keywords"]
            missing = structured["missing_keywords"]
            gaps = structured["gaps"]
            overall = scores.get("overall")
            answer_lines = ["## JD 匹配结果"]
            if isinstance(overall, (int, float)):
                answer_lines.extend(
                    [
                        f"**文本匹配参考分：{overall:g}/100**",
                        "该分数只反映当前简历文字与 JD 的覆盖度，不代表 ATS 通过率或录用概率。",
                    ]
                )
            answer_lines.append("\n### 匹配项（按当前文本证据）")
            answer_lines.extend(
                [f"- {item}" for item in matched]
                or ["- 暂未找到可定位到简历原文的匹配项。"]
            )
            answer_lines.append("\n### 证据不足或缺失")
            answer_lines.extend(
                [f"- {item}" for item in missing]
                or ["- 当前结构化分析未发现明确缺失项；技能深度仍需用项目细节或面试回答验证。"]
            )
            if gaps:
                answer_lines.append("\n### 下一步建议")
                answer_lines.extend(f"- {item}" for item in gaps)
            answer_lines.append(
                "\n> 说明：技能列表只能证明接触或了解；只有项目、实习或可复现实验中的具体做法，才算深度证据。"
            )
            direct_answer = "\n".join(answer_lines)
            return "[[DIRECT_ANSWER]]\n" + direct_answer + structured_block + report_block
        except HTTPException as e:
            return f"⚠️ {e.detail}"
        except Exception as e:
            return f"⚠️ JD 匹配分析失败: {e}"


class DiagnoseResumeTool(Tool):
    name = "diagnose_resume"
    description = "诊断简历的完整性和质量，给出改进建议"
    args_model = DiagnoseResumeArgs
    category = "qa"

    async def _execute(self, **kwargs) -> str:
        resume_id = kwargs.get("resume_id")

        # #4: 草稿/未就绪简历诊断会失败，前置给出明确提示
        resume = await self._get_resume(resume_id)
        if resume is None:
            return "⚠️ 简历不存在或无权访问，请确认当前选中的简历。"
        if resume.status == "draft":
            return "⚠️ 这份简历还是草稿（未完成），请先在编辑器中填写内容并「保存并完成」后再诊断。"
        if resume.status != "ready":
            return f"⚠️ 简历当前状态为 {resume.status}，暂不可诊断。"

        sections: list[str] = []

        async def _run_analysis(analysis_type: str):
            # 两个分析都是只读且彼此独立。使用独立 session 并行执行，避免在同一个
            # AsyncSession 上并发查询，也把首轮诊断等待时间从两次 LLM 串行降为一次。
            async with AsyncSessionLocal() as analysis_db:
                return await analyze_resume(
                    db=analysis_db,
                    user_id=self.user_id,
                    resume_id=resume_id,
                    analysis_type=analysis_type,
                )

        analysis_types = ("experience", "score")
        results = await asyncio.gather(
            *(_run_analysis(analysis_type) for analysis_type in analysis_types),
            return_exceptions=True,
        )
        for analysis_type, result in zip(analysis_types, results):
            try:
                if isinstance(result, Exception):
                    raise result
                analysis = result.get("analysis", "")
                label = "经历分析" if analysis_type == "experience" else "评分"
                sections.append(f"## {label}\n{analysis}")
            except HTTPException as e:
                if "不存在" in str(e.detail):
                    return "⚠️ 简历不存在或无权访问。"
                sections.append(f"## {analysis_type}\n分析失败: {e.detail}")
            except Exception as e:
                sections.append(f"## {analysis_type}\n分析失败: {e}")

        if not sections:
            return "⚠️ 诊断失败，请稍后重试。"

        # E1 可溯源：填充诊断所依据的简历原文段落（供前端诊断卡片来源区展示）
        # 用覆盖主要分节的关键词检索，best-effort（失败不影响诊断结果）
        try:
            await ensure_indexed(
                self.db,
                user_id=self.user_id,
                asset_id=resume_id,
                asset_type=ASSET_TYPE_RESUME,
                collection=knowledge_collection_name(self.user_id),
            )
            chunks = await hybrid_search(
                self.user_id,
                resume_id,
                "项目经历 技能 量化成果 工作经历 教育背景 专业能力",
                top_k=20,
            )
            if chunks:
                reranked = await rerank("简历完整性与质量诊断依据", chunks, top_k=5)
                self.sources = adapt_evidence_list(reranked, preserve_extra=True)
        except Exception:
            # sources 是增强信息，填充失败不阻断诊断
            pass

        return "\n\n".join(sections)


class CompareResumesTool(Tool):
    name = "compare_resumes"
    description = "对比多份简历的优劣，给出综合裁决"
    args_model = CompareResumesArgs
    category = "qa"

    # 综合裁决 system prompt：要求模型横向对比（而非逐份复述），输出裁决
    _COMPARE_SYSTEM = (
        "你是一名资深的招聘专家和简历评审顾问。用户给了多份简历的提取摘要，"
        "需要你真正地横向对比它们，而不是重复罗列每份简历的内容。请输出：\n"
        "1. 各简历核心优势与短板（每份一句话）\n"
        "2. 横向对比：按技能 / 项目 / 经验 / 评分维度，谁强谁弱\n"
        "3. 综合裁决：给出竞争力排名与推荐理由\n"
        "要求：中文、结构化 markdown、精炼（总字数 ≤ 600 字），不要逐字复述简历内容。"
    )

    async def _build_verdict(self, resumes, dimensions, id_to_name) -> str:
        """把多份简历的关键内容拼进一次 LLM 调用，让模型综合裁决（打破逐份隔离）。

        原 compare_resumes 只并列各简历独立分析，模型从没见过全部简历做比较；
        这里追加一次综合对比调用，失败时降级保留维度明细（不阻断对比）。
        """
        try:
            sections = []
            for r in resumes:
                rid = str(r["id"])
                lines = [f"### {r['filename']}"]
                for dim in ("summary", "skills", "experience", "score", "projects"):
                    val = dimensions.get(dim, {}).get(rid)
                    if val is None:
                        continue
                    if dim == "score" and isinstance(val, dict):
                        val = _json_std.dumps(val, ensure_ascii=False)
                    elif isinstance(val, list):
                        val = "、".join(str(x) for x in val)
                    lines.append(f"- {dim}: {str(val)[:600]}")
                sections.append("\n".join(lines))

            user = (
                "以下是待对比的简历摘要（来自同一个人的多份简历，或不同候选人的简历）：\n\n"
                + "\n\n".join(sections)
                + "\n\n请给出横向对比与综合裁决。"
            )
            verdict = await llm_generate(
                system=self._COMPARE_SYSTEM,
                user=user,
                temperature=0.2,
                user_id=self.user_id,
            )
            return (verdict or "").strip()
        except Exception as e:
            logger.warning("综合裁决生成失败（忽略，保留维度明细）: %s", e)
            return ""

    async def _execute(self, **kwargs) -> str:
        resume_ids = kwargs.get("resume_ids")

        try:
            result = await compare_resumes(
                db=self.db,
                user_id=self.user_id,
                resume_ids=resume_ids,
                dimensions=["summary", "skills", "experience", "score", "projects"],
            )
        except HTTPException as e:
            return f"⚠️ {e.detail}"
        except Exception as e:
            return f"⚠️ 对比分析失败: {e}"

        resumes = result.get("resumes", [])
        dimensions = result.get("dimensions", {})
        id_to_name = {r["id"]: r["filename"] for r in resumes}

        # 综合裁决：一次 LLM 横向对比（真正"对比"，而非并列展示）
        verdict = await self._build_verdict(resumes, dimensions, id_to_name)

        lines = [f"对比 {len(resumes)} 份简历："]
        for r in resumes:
            lines.append(f"  - {r['filename']}")
        if verdict:
            lines.append("\n## 综合裁决\n" + verdict)

        for dim, values in dimensions.items():
            lines.append(f"\n## {dim}")
            for rid, val in values.items():
                name = id_to_name.get(int(rid), f"简历{rid}")
                lines.append(f"  - {name}: {val}")

        return "\n".join(lines)


class RewriteStarTool(Tool):
    name = "rewrite_star"
    description = "用 STAR 法则改写简历中的经历描述，使其更专业有力（整份重写为模块草稿）"
    args_model = RewriteStarArgs
    category = "qa"

    async def _execute(self, **kwargs) -> str:
        resume_id = kwargs.get("resume_id")
        target_position = kwargs.get("target_position")

        # 改写写的是模块草稿（正是 draft 简历被编辑的目标），不校验 status
        resume, input_context, required_module_types = await _read_modules_context(
            self.db, self.user_id, resume_id
        )
        if resume is None:
            return "⚠️ 简历不存在或无权访问。"
        if not input_context:
            return "⚠️ 简历为空，无法改写。请先在「编辑」页填写内容。"

        position_hint = f"，目标岗位：{target_position}" if target_position else ""
        system = (
            "你是专业简历优化专家，擅长使用 STAR 法则"
            "（Situation 情境、Task 任务、Action 行动、Result 结果）"
            f"改写简历中的经历描述，使其更专业有力{position_hint}。\n"
            "必须通过调用 submit_rewritten_resume 工具提交：modules 参数为【完整】模块数组，"
            "覆盖输入中的所有模块（不增不减 module_type），每个元素含 module_type、content、sort_order、source。\n"
            "对每个模块的 source 标注内容来源：直接来自简历事实标 fact，AI 推断/补充标 inferred，"
            "混合标 mixed。不得把推断内容标为 fact。\n"
            "对 work_experience/project_experience/club_activities 等经历类模块 entries 的 description 用 STAR 结构重写；"
            "其余模块（basic_info/skills/language 等）保持内容不变。保持事实不变，不要编造。"
        )
        user_msg = (
            f"目标岗位: {target_position or '未指定'}\n"
            f"当前简历模块:\n{input_context}\n\n"
            f"请对经历类描述做 STAR 改写，并通过 submit_rewritten_resume 提交完整 modules 数组。"
        )
        return await _submit_modules_via_llm(
            self.user_id,
            resume_id,
            system,
            user_msg,
            fail_prefix="STAR 改写失败",
            emit=self.emit,
            usage_target=self.last_usage,
            tool_name="rewrite_star",
            required_module_types=required_module_types,
            expected_module_revision=resume.module_revision,
        )


class TranslateTool(Tool):
    name = "translate"
    description = "将简历翻译为指定语言（整份重写为模块草稿）"
    args_model = TranslateArgs
    category = "qa"

    async def _execute(self, **kwargs) -> str:
        resume_id = kwargs.get("resume_id")
        target_lang = kwargs.get("target_lang")

        resume, input_context, required_module_types = await _read_modules_context(
            self.db, self.user_id, resume_id
        )
        if resume is None:
            return "⚠️ 简历不存在或无权访问。"
        if not input_context:
            return "⚠️ 简历为空，无法翻译。请先在「编辑」页填写内容。"

        _LANG_MAP = {
            "en": "English",
            "ja": "日本語",
            "ko": "한국어",
            "fr": "Français",
            "de": "Deutsch",
        }
        lang_name = _LANG_MAP.get(target_lang, target_lang)

        system = (
            f"你是专业翻译，请将简历模块内容翻译为 {lang_name}（{target_lang}）。保持专业术语准确。\n"
            "必须通过 submit_rewritten_resume 工具提交：modules 参数为【完整】模块数组，"
            "module_type、sort_order 与输入一一对应，content 结构完全一致（只翻译字符串值，"
            "不增删字段、不增删 entries/categories）。\n"
            "注意字段长度上限：basic_info.summary≤500、work_experience.description≤2000、"
            "publications.title≤300 等，翻译后不得超过原上限。"
        )
        user_msg = (
            f"目标语言: {lang_name}（{target_lang}）\n"
            f"当前简历模块:\n{input_context}\n\n"
            f"请将全部模块内容翻译为 {lang_name} 并通过 submit_rewritten_resume 提交完整 modules 数组。"
        )
        return await _submit_modules_via_llm(
            self.user_id,
            resume_id,
            system,
            user_msg,
            max_tokens=8000,
            fail_prefix="翻译失败",
            emit=self.emit,
            usage_target=self.last_usage,
            tool_name="translate",
            rationale=f"翻译为 {lang_name}",
            required_module_types=required_module_types,
            expected_module_revision=resume.module_revision,
        )


class InterviewCoachTool(Tool):
    """多轮模拟面试（H1-H3，阶段 5）。

    单次工具调用推进一问：状态落 interview_simulations 表（按 user_id+resume_id
    解析进行中的面试），每次调用记录回答 + 出下一题/追问；完成时自动逐题评分
    并写入 InterviewSession（公司=模拟面试）流入复盘闭环。与 Agent loop 一问一答
    多次调用交互，_execute 始终返回字符串（兼容既有 loop）。
    """

    name = "interview_coach"
    description = (
        "多轮模拟面试教练。首次调用开始一场模拟面试并出第 1 题；"
        "面试进行中，用户每回答一题，必须再次调用本工具并把用户回答原文作为 answer 传入，"
        "工具会记录回答并推进到下一题/追问；用户想跳过当前题传 action=skip；"
        "用户想结束面试传 action=end（自动逐题评分并出评分卡）。"
    )
    args_model = InterviewCoachArgs
    category = "qa"

    async def _execute(self, **kwargs) -> str:
        from services import interview_coach as ic

        resume_id = kwargs.get("resume_id")
        target_position = kwargs.get("target_position") or ""
        answer = kwargs.get("answer") or ""
        action = kwargs.get("action") or "next"

        # 1. 解析进行中的模拟面试
        sim = await ic.get_active_simulation(self.db, self.user_id, resume_id)

        # 2. 强制新开：终结旧的一场（标记 completed，不评分）
        if action == "start" and sim is not None:
            sim.status = "completed"
            await self.db.commit()

        # 3. 无进行中的面试（或强制新开）→ 创建并出第 1 题
        if sim is None or action == "start":
            if not resume_id or not target_position:
                return "⚠️ 开始模拟面试需要 resume_id 和 target_position（如目标岗位：前端工程师）。"
            resume = await self._get_resume(resume_id)
            if resume is None:
                return "⚠️ 简历不存在或无权访问。"
            resume_text = resume.parsed_text or ""
            if not resume_text:
                try:
                    from services.resume_builder import get_resume_with_modules

                    _, modules = await get_resume_with_modules(self.db, self.user_id, resume_id)
                    resume_text = "\n".join(
                        f"【{m.module_type}】{m.content}" for m in modules if m.content
                    )
                except Exception:  # noqa: BLE001 - 文本兜底失败不阻断
                    resume_text = ""
            sim = await ic.start_simulation(
                self.db, self.user_id, resume_id, target_position, resume_text
            )
            return ic.format_question(sim, is_first=True)

        # 4. 结束并评分
        if action == "end":
            scorecard, _session = await ic.finalize_simulation(self.db, self.user_id, sim)
            return ic.format_scorecard_result(scorecard, sim)

        # 5. 记录回答并推进（answer 非空时）
        if answer and answer.strip():
            ic.record_answer(sim, answer.strip())
            ic.advance(sim)
            if ic.is_complete(sim):
                # 刚答完最后一题 → 结束评分
                scorecard, _session = await ic.finalize_simulation(self.db, self.user_id, sim)
                return ic.format_scorecard_result(scorecard, sim)
            await self.db.commit()
            return ic.format_question(sim)

        # 6. 跳过当前题（含未答的追问，直接到下一题）
        if action == "skip":
            ic.skip_question(sim)
            if ic.is_complete(sim):
                scorecard, _session = await ic.finalize_simulation(self.db, self.user_id, sim)
                return ic.format_scorecard_result(scorecard, sim)
            await self.db.commit()
            return ic.format_question(sim)

        # 7. 无回答 → 重问当前题（不推进）
        return ic.format_question(sim)


class CoverLetterArgs(BaseModel):
    resume_id: int = Field(..., description="简历 ID")
    jd_text: str | None = Field(None, description="目标岗位 JD 原文（可选，用于关键词贴合）")
    mode: str = Field("letter", description="生成类型：letter（求职信）/ greeting（打招呼语）")


class CoverLetterTool(Tool):
    """G 功能空白：针对岗位一键生成求职信/打招呼语。

 的文本生成模式（llm_generate 出自由文本），
    never-exceed 约束对齐 RewriteStarTool：「只基于简历实际经历，不编造」。
    """

    name = "cover_letter"
    description = (
        "针对目标岗位一键生成求职信（letter）或打招呼语（greeting），"
        "只基于简历真实经历，不编造任何学历/公司/项目/技能"
    )
    args_model = CoverLetterArgs
    category = "qa"

    async def _execute(self, **kwargs) -> str:
        resume_id = kwargs["resume_id"]
        jd_text = kwargs.get("jd_text") or ""
        mode = kwargs.get("mode", "letter")

        resume, input_context, _required_module_types = await _read_modules_context(
            self.db, self.user_id, resume_id
        )
        if resume is None:
            return "⚠️ 简历不存在或无权访问。"
        if not input_context:
            return "⚠️ 简历为空，无法生成。请先在「编辑」页填写内容。"

        jd_part = f"目标岗位 JD：\n{jd_text or '（未提供，根据简历推断意向岗位）'}\n\n"
        if mode == "greeting":
            system = (
                "你是求职投递助手。基于候选人的简历，为 HR 写一段 50-80 字的打招呼语"
                "（用于招聘平台私信/投递附言）。突出与目标岗位最匹配的 1-2 个亮点，"
                "语气礼貌、简洁、真诚。\n"
                "只使用简历中已有的真实经历与技能，不得编造学历、公司、项目、技能、获奖。"
            )
        else:
            system = (
                "你是求职信撰写专家。根据候选人的简历与目标岗位 JD，写一封 200-300 字的中文求职信。\n"
                "要求：\n"
                "1. 只使用简历中已有的真实经历、技能与成果，不得编造学历、公司、项目、技能、奖项；\n"
                "2. 针对 JD 中的关键词突出匹配点（提炼简历中相关的真实经历作支撑）；\n"
                "3. 结构：简短自我介绍 → 匹配点论证 → 表达意愿，语气专业真诚。"
            )
        user = f"{jd_part}简历内容：\n{input_context}"
        return await llm_generate(system=system, user=user, user_id=self.user_id)


# ═══════════════════════════════════════════════════════════
# Builder 工具实现 (5) — T28
# 设计：短事务独立 commit（避免长事务锁行）；编辑锁已由前端 /lock 端点
# + edit_lock.py 独立承载（此处工具内部不再用锁，注释不再提）
# ═══════════════════════════════════════════════════════════


# ── Builder 工具公共辅助 ──


# builder 工具内部 function calling 使用的模型：judge=DeepSeek v4 flash。
# 注意：本代码库中 CHAT_MODEL 从未被传过 tools，function calling 支持未验证；
# DeepSeek 是唯一被实战验证能出 tool_calls 的模型。如需切回 CHAT_MODEL 设 None 即可。
_BUILDER_GEN_MODEL = "judge"


async def _stream_tool_llm(
    *,
    messages: list[dict],
    tools: list[dict] | None,
    tool_name: str,
    emit,
    temperature: float = 0.1,
    max_tokens: int | None = None,
    model: str | None = None,
    user_id: int | None = None,
    usage_target: dict | None = None,
) -> LLMToolResponse:
    """工具内部 LLM 流式生成（编辑器工具内部死等 → 边出边看）。

    - ``emit is None`` → 非流式 ``llm_generate_with_tools``（行为不变，兼容无事件上下文/测试）
    - ``emit`` 存在 → ``llm_generate_with_tools_stream``，token/reasoning 实时推
      ``{"type": "tool_stream", "tool_name", "kind", "content"}`` 事件，
      从 ``done`` 事件聚合 tool_calls，返回 LLMToolResponse（调用方沿用 ``_extract_tool_args``）
    """
    if emit is None:
        if tools is None:
            # Text-only tools should use the cheaper non-tool request path.
            # Besides avoiding an unnecessary function schema, this keeps
            # direct/read-only calls independent from tool-call parsing.
            text = await llm_generate(
                system=messages[0].get("content", "") if messages else "",
                user=messages[1].get("content", "") if len(messages) > 1 else "",
                temperature=temperature,
                max_tokens=max_tokens,
                model=model,
                user_id=user_id,
                scenario="field_rewrite",
            )
            return LLMToolResponse(content=text, usage=getattr(usage_target, "copy", lambda: {})() if usage_target else {})
        return await llm_generate_with_tools(
            messages=messages,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
            model=model,
            user_id=user_id,
        )

    content_parts: list[str] = []
    tool_calls: list[ToolCall] = []
    tool_usage: dict = {"prompt_tokens": 0, "completion_tokens": 0}
    async for ev in llm_generate_with_tools_stream(
        messages=messages,
        tools=tools,
        temperature=temperature,
        max_tokens=max_tokens,
        model=model,
        user_id=user_id,
    ):
        et = ev.get("type")
        if et == "reasoning":
            await emit(
                {
                    "type": "tool_stream",
                    "tool_name": tool_name,
                    "kind": "reasoning",
                    "content": ev.get("content", ""),
                }
            )
        elif et == "token":
            content_parts.append(ev.get("content", ""))
            await emit(
                {
                    "type": "tool_stream",
                    "tool_name": tool_name,
                    "kind": "token",
                    "content": ev.get("content", ""),
                }
            )
        elif et == "usage":
            tool_usage["prompt_tokens"] = ev.get("prompt_tokens", 0)
            tool_usage["completion_tokens"] = ev.get("completion_tokens", 0)
            if usage_target is not None:
                usage_target["prompt_tokens"] = tool_usage["prompt_tokens"]
                usage_target["completion_tokens"] = tool_usage["completion_tokens"]
        elif et == "done":
            tool_calls = ev.get("tool_calls", []) or []

    return LLMToolResponse(
        content="".join(content_parts),
        tool_calls=tool_calls,
        usage=tool_usage,
    )


def _make_function_schema(name: str, description: str, parameters: dict) -> dict:
    """构造 OpenAI function calling schema（临时工具，不注册 TOOL_REGISTRY）。

    与 Tool.to_openai_schema()（base.py）同形状，但绑定调用期的 name/description/parameters，
    而非类属性。只服务 builder 工具内部的 LLM 调用。
    """
    return {
        "type": "function",
        "function": {"name": name, "description": description, "parameters": parameters},
    }


def _extract_tool_args(response: LLMToolResponse, expected_name: str) -> dict:
    """从 llm_generate_with_tools 响应提取指定工具的参数 dict。

    覆盖三类失败：无 tool_calls / 工具名不符 / arguments 非合法 JSON。

    Returns:
        解析后的参数 dict（保证 dict）

    Raises:
        ValueError: 三类失败之一，错误串含修复指引，供外层 LLM 自愈
    """
    if not response.tool_calls:
        raise ToolRetryError("AI 未通过工具提交内容，请重新调用工具提交。")
    tc = response.tool_calls[0]
    if tc.name != expected_name:
        raise ToolRetryError(
            f"AI 调用了非预期工具 {tc.name}（期望 {expected_name}），请重新调用工具提交。"
        )
    try:
        args = _json.loads(tc.arguments) if tc.arguments else {}
    except (_json.JSONDecodeError, TypeError) as e:
        raise ToolRetryError("工具参数 JSON 解析失败，请重新调用工具提交纯 JSON。") from e
    if not isinstance(args, dict):
        raise ToolRetryError("工具参数应为 JSON 对象，请重新调用工具提交。")
    return args


class _RewrittenModule(BaseModel):
    """重写后单个模块条目。content 用宽松 dict，由 validate_module_content 严格校验兜底。"""

    module_type: str = Field(
        ...,
        description="模块类型（15 个固定枚举之一：basic_info/education/work_experience/"
        "project_experience/skills/language/honors/certificates/interests/"
        "club_activities/publications/recommendation/social_links/other/custom）",
    )
    content: dict = Field(
        ...,
        description="模块内容 JSON 对象。字段结构随 module_type 变化（basic_info 平铺对象；"
        "education/work_experience 等为 {entries:[...]}；skills 为 {categories:[...]}）。"
        "给出完整内容，不要留空占位。",
    )
    sort_order: int = Field(..., ge=0, description="模块在简历中的排序位置（从 0 开始）")
    source: Literal["fact", "inferred", "mixed", "unknown"] = Field(
        "unknown",
        description="G 可信度控制：内容来源。fact=简历已有事实；inferred=AI 推断/补充（需用户核对）；"
        "mixed=混合；unknown=模型未标注，不能视为事实",
    )


class _RewriteResumeOutput(BaseModel):
    """rewrite_resume 的 submit_rewritten_resume 工具参数。"""

    modules: list[_RewrittenModule] = Field(
        ...,
        description="重写后的模块数组（generate 模式至少包含 basic_info/education/work_experience/skills 四个核心模块）",
    )


def _coerce_modules(raw) -> list | None:
    """宽容解析 LLM 返回的 modules 参数（多种错误形状 → 标准 list）。

    小模型（轻量档 judge）输出整份 modules 数组时常见的错误形状：
    1. dict 且含 "modules" key（套娃）→ 递归取内层
    2. dict 按 module_type 作 key、value 为 content
       （如 {"work_experience": {...}}）→ 转 [{module_type, content, sort_order}]
    3. str 内含 JSON → 解析后递归
    4. list → 标准形状，原样返回

    Returns:
        标准化 list；无法识别返回 None（由调用方抛 ToolRetryError 回灌 LLM 修正）。
    """
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        # 套娃：{"modules": [...]} 或 {"modules": {...}}
        inner = raw.get("modules")
        if inner is not None:
            return _coerce_modules(inner)
        # module_type 作 key：{module_type: content} / {module_type: [entries]}
        items: list[dict] = []
        for key, value in raw.items():
            if not isinstance(key, str) or not key:
                return None
            if isinstance(value, dict):
                items.append(
                    {"module_type": key, "content": value, "sort_order": len(items)}
                )
            elif isinstance(value, list):
                items.append(
                    {
                        "module_type": key,
                        "content": {"entries": value},
                        "sort_order": len(items),
                    }
                )
            else:
                return None
        return items
    if isinstance(raw, str):
        try:
            return _coerce_modules(_json.loads(raw))
        except (_json.JSONDecodeError, TypeError):
            return None
    return None


def _restore_sensitive_placeholders(
    modules: list[dict], original_modules: list[dict]
) -> list[dict]:
    """落库前把脱敏占位符还原为原始快照中的真实值。

    改写/翻译/整份重写路径先用 ``sanitize_resume_module_for_ai`` 脱敏
    （basic_info 的 name→[姓名]、phone→[手机号]、email→[邮箱]）再喂 LLM，
    LLM 按「保持结构」原样回传占位符。此处用改写前快照的 basic_info 真实值
    做占位符替换，避免 ``[姓名]`` 等字面量写入简历模块造成数据损坏。
    仅当 before 快照存在对应真实值时才还原；否则保留原样。
    """
    original_basic: dict = {}
    for m in original_modules or []:
        if m.get("module_type") == "basic_info" and isinstance(m.get("content"), dict):
            original_basic = m["content"]
            break
    if not original_basic:
        return modules
    mapping = {
        "[姓名]": str(original_basic.get("name") or "").strip(),
        "[手机号]": str(original_basic.get("phone") or "").strip(),
        "[邮箱]": str(original_basic.get("email") or "").strip(),
    }
    mapping = {k: v for k, v in mapping.items() if v}
    if not mapping:
        return modules

    def _walk(value):
        if isinstance(value, str):
            for placeholder, real in mapping.items():
                value = value.replace(placeholder, real)
            return value
        if isinstance(value, list):
            return [_walk(item) for item in value]
        if isinstance(value, dict):
            return {k: _walk(v) for k, v in value.items()}
        return value

    return [{**m, "content": _walk(m.get("content"))} for m in modules]


async def _read_modules_context(db, user_id: int, resume_id: int):
    """读简历 + 模块上下文。返回 (resume, input_context, module_types)。

    模块化简历走模块 JSON；上传型简历（无模块）用 parsed_text 兜底。
    简历不存在/无权访问时返回 (None, "", set())。
    """
    try:
        resume, modules = await get_resume_with_modules(db, user_id, resume_id)
    except HTTPException:
        return None, "", set()
    if resume is None:
        return None, "", set()
    if modules:
        # 每模块截断 300 → 2000：原 300 只够 work_experience 等长模块第一个 entry 的
        # 一小部分，LLM 看到的是残缺内容（「工作经历无法正确识别」根因之一）。
        parts = [
            f"- {m.module_type}: {_json.dumps(sanitize_resume_module_for_ai(m.module_type, m.content) if isinstance(m.content, dict) else m.content, ensure_ascii=False)[:2000]}"
            for m in modules
        ]
        return resume, "\n".join(parts), {module.module_type for module in modules}
    if resume.parsed_text:
        return resume, f"（无模块，原始文本）\n{resume.parsed_text[:16000]}", set()
    return resume, "", set()


async def _await_proposal_approval(
    *,
    proposal,
    user_id: int,
    tool_name: str,
    emit,
    rationale: str,
) -> dict:
    """Pause a write proposal for the same approval channel used by tools.

    The event exposes only a redacted summary/hash; executable module payloads
    remain server-side in AgentProposal.
    """
    if getattr(settings, "AGENT_PROPOSAL_AUTO_APPLY", False):
        from services.react_agent.proposal_commit import ProposalCommitService

        service = ProposalCommitService()
        await service.decide(proposal_id=proposal.proposal_id, user_id=user_id, approved=True)
        return await service.apply(
            proposal_id=proposal.proposal_id,
            user_id=user_id,
            idempotency_key=proposal.idempotency_key,
        )
    if emit is None:
        raise ToolFailed("写入 Proposal 需要可交互的审批通道")

    from services.react_agent.loop import (
        drop_approval,
        register_approval,
        register_approval_remote,
        wait_for_approval,
    )

    approval_id = uuid.uuid4().hex
    register_approval(approval_id, user_id)
    summary = f"{tool_name} 将应用一组简历修改（proposal={proposal.proposal_id[:12]}）"
    await register_approval_remote(
        approval_id,
        user_id=user_id,
        tool_name=tool_name,
        summary=summary,
        severity="warning",
    )
    try:
        await emit(
            {
                "type": "approval_request",
                "approval_id": approval_id,
                "proposal_id": proposal.proposal_id,
                "proposal_hash": proposal.content_hash,
                "tool_name": tool_name,
                "summary": summary,
                "rationale": rationale[:500],
                "severity": "warning",
            }
        )
        decision = await wait_for_approval(approval_id)
    finally:
        drop_approval(approval_id)
    from services.react_agent.proposal_commit import ProposalCommitService

    service = ProposalCommitService()
    approved = decision in {"approved", "allow_always"}
    await service.decide(proposal_id=proposal.proposal_id, user_id=user_id, approved=approved)
    if not approved:
        raise ToolFailed("用户拒绝应用该简历修改 Proposal")
    return await service.apply(
        proposal_id=proposal.proposal_id,
        user_id=user_id,
        idempotency_key=proposal.idempotency_key,
    )


async def _submit_modules_via_llm(
    user_id: int,
    resume_id: int,
    system_prompt: str,
    user_msg: str,
    *,
    tool_desc: str = "提交整份重写后的简历模块数组。modules 每项为 {module_type, content, sort_order}。",
    max_tokens: int = 8000,
    fail_prefix: str = "AI 重写失败",
    emit=None,
    usage_target: dict | None = None,
    complete: bool = False,
    tool_name: str = "",
    rationale: str | None = None,
    required_module_types: set[str] | None = None,
    expected_module_revision: int | None = None,
) -> str:
    """让 LLM 通过 function calling 提交完整 modules 数组 → 逐模块校验 → 短事务全量替换。

    改写/翻译/重写类工具共用。整份重写保证：_replace_all_modules_short_txn 删旧插新原子全量替换，
    且不新建 Resume（多轮对话累积到同一份草稿）。

    E2：传入 tool_name 时，在落库处附加字段级 PendingChange 记录（改动的审阅队列）。
    快照与落库均为 best-effort，失败不阻断改写主流程。

    emit：工具内部 LLM 流式 token 回调（无则退化为非流式）。
    """
    # E2: 改写前快照（作为 diff 的 before 基准）
    before_modules: list[dict] = []
    if tool_name:
        from services.pending_changes import snapshot_modules

        before_modules = await snapshot_modules(user_id, resume_id)

    tool_schema = _make_function_schema(
        name="submit_rewritten_resume",
        description=tool_desc,
        parameters=_RewriteResumeOutput.model_json_schema(),
    )
    try:
        response = await _stream_tool_llm(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_msg},
            ],
            tools=[tool_schema],
            tool_name="submit_modules",
            emit=emit,
            temperature=0.1,
            max_tokens=max_tokens,
            model=_BUILDER_GEN_MODEL,
            user_id=user_id,
            usage_target=usage_target,
        )
        args = _extract_tool_args(response, "submit_rewritten_resume")
    except ToolRetryError:
        # A3 回灌自愈：参数/JSON 解析失败抛给 loop 回灌 LLM 修正重试，不吞成普通文本
        raise
    except Exception as e:
        return f"⚠️ {fail_prefix}：{e}"

    raw_modules = _coerce_modules(args.get("modules"))
    if raw_modules is None:
        # 宽容解析（dict/str/套娃→list）仍失败才回灌 LLM 修正重试
        raise ToolRetryError("AI 重写结果格式错误：modules 应为数组。")

    from schemas.resume_module import validate_module_content, ModuleType
    from pydantic import ValidationError

    validated_modules: list[dict] = []
    errors: list[str] = []
    for idx, raw in enumerate(raw_modules):
        if not isinstance(raw, dict):
            errors.append(f"模块 {idx}: 不是对象")
            continue
        mt_str = raw.get("module_type", "")
        content = raw.get("content", {})
        sort_order = raw.get("sort_order", idx)
        source = raw.get("source", "unknown")
        if source not in ("fact", "inferred", "mixed", "unknown"):
            errors.append(f"模块 {idx} ({mt_str}): source 非法: {source!r}")
            continue
        try:
            mt = ModuleType(mt_str)
            validate_module_content(mt, content)
            validated_modules.append(
                {
                    "module_type": mt_str,
                    "content": content,
                    "sort_order": sort_order
                    if isinstance(sort_order, int) and sort_order >= 0
                    else idx,
                    "source": source,
                }
            )
        except (ValueError, ValidationError) as e:
            errors.append(f"模块 {idx} ({mt_str}): {e}")

    if not validated_modules:
        errors.append("modules 不能为空")

    candidate_types = [module["module_type"] for module in validated_modules]
    duplicate_types = sorted(
        module_type for module_type in set(candidate_types) if candidate_types.count(module_type) > 1
    )
    if duplicate_types:
        errors.append("module_type 重复: " + ", ".join(duplicate_types))

    expected_types = set(required_module_types or ())
    expected_types.update(module["module_type"] for module in before_modules)
    if expected_types:
        missing_types = sorted(expected_types - set(candidate_types))
        if missing_types:
            errors.append("缺少现有模块: " + ", ".join(missing_types))

    if errors:
        # 全量替换只能整批通过；禁止跳过坏模块后损坏现有简历结构。
        raise ToolRetryError("重写结果校验失败，未写入任何模块:\n" + "\n".join(errors))

    # G 脱敏还原：AI 改写/翻译输入经 sanitize_resume_module_for_ai 脱敏
    # （name→[姓名] 等），LLM 原样回传占位符。落库前用 before 快照还原真实值，
    # 避免占位符写入简历模块造成数据损坏。
    if before_modules:
        validated_modules = _restore_sensitive_placeholders(validated_modules, before_modules)

    # The SSE runtime has already passed the outer tool approval gate.  Use a
    # Proposal-Commit transaction for real Agent writes so the mutation is
    # still represented by an auditable proposal and revision CAS.  Legacy
    # direct tool calls (including migration/tests) retain the old adapter.
    proposal_enabled = bool(
        emit is not None
        and getattr(settings, "AGENT_PROPOSAL_COMMIT_ENABLED", True)
        and tool_name
    )
    if proposal_enabled:
        from services.react_agent.proposal_commit import ProposalCommitService

        proposal_service = ProposalCommitService()
        idempotency_key = uuid.uuid4().hex
        proposal = await proposal_service.create(
            user_id=user_id,
            resume_id=resume_id,
            call_id=f"{tool_name}:{uuid.uuid4().hex}",
            operations=validated_modules,
            rationale=rationale or tool_name,
            evidence=[],
            idempotency_key=idempotency_key,
        )
        await _await_proposal_approval(
            proposal=proposal,
            user_id=user_id,
            tool_name=tool_name,
            emit=emit,
            rationale=rationale or tool_name,
        )
        result = f"✅ 已通过 Proposal-Commit 应用简历修改（proposal_id={proposal.proposal_id}）"
    else:
        result = await _replace_all_modules_short_txn(
            user_id,
            resume_id,
            validated_modules,
            complete=complete,
            expected_module_types=expected_types,
            expected_module_revision=expected_module_revision,
        )
    # G 可信度控制：AI 推断/补充内容（source≠fact）提醒用户核对具体模块
    inferred_modules = [
        m["module_type"] for m in validated_modules if m.get("source", "unknown") != "fact"
    ]
    if inferred_modules:
        result += (
            f"\n⚠️ {len(inferred_modules)} 个模块含 AI 推断/补充内容"
            f"（{', '.join(inferred_modules)}），请核对推断内容是否属实后再发布。"
        )
    # E2: 落库成功后附加字段级 PendingChange 审阅记录（best-effort，失败不阻断）
    if tool_name and not result.startswith("⚠️"):
        try:
            from services.pending_changes import save_pending_changes

            await save_pending_changes(
                user_id,
                resume_id,
                before_modules,
                validated_modules,
                tool_name=tool_name,
                rationale=rationale,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("save_pending_changes 附加失败（忽略）: %s", e)
    return result


async def _update_module_short_txn(
    user_id: int,
    resume_id: int,
    module_type: str,
    new_content: dict,
    *,
    restore_content: dict | None = None,
) -> str:
    """短事务独立写入模块（独立 session + commit）。

    短事务设计：不在请求 session 中操作，每次独立开 session → flush → commit → close。
    避免长事务锁行 / 请求超时导致回滚。
    """
    from models.resume_module import ResumeModule
    from services.resume_module_mutation import (
        ResumeModuleConflictError,
        load_resume_modules_for_mutation,
        lock_resume_for_module_mutation,
    )
    from schemas.resume_module import validate_module_content

    # 入口校验 content——失败抛 ToolRetryError 走 A3 回灌自愈：
    # loop 收到后标记坏调用并回灌结构化错误，LLM 补齐缺失/空字段后重试。
    from pydantic import ValidationError

    try:
        validate_module_content(module_type, new_content)
    except ValidationError as e:
        raise ToolRetryError(
            f"模块 {module_type} content 校验失败（{len(e.errors())} 处）:\n"
            + format_validation_error(e)
            + "\n请补充/修正必填字段（不能缺失或为空字符串）后重新调用工具提交。"
        ) from e
    except Exception as e:  # noqa: BLE001 未知 module_type 等
        raise ToolRetryError(f"模块 {module_type} content 校验失败: {e}") from e

    async with AsyncSessionLocal() as session:
        # 脱敏还原：modify/generate basic_info 场景输入经 sanitize 脱敏，
        # 用原始 content 还原 [姓名] 等占位符后再写入。
        if restore_content:
            new_content = _restore_sensitive_placeholders(
                [{"module_type": module_type, "content": new_content}],
                [{"module_type": module_type, "content": restore_content}],
            )[0]["content"]

        # 校验归属
        try:
            resume = await lock_resume_for_module_mutation(session, user_id, resume_id)
        except ResumeModuleConflictError as e:
            raise ToolRetryError(str(e)) from e
        if resume is None:
            return f"⚠️ 简历 {resume_id} 不存在或无权访问。"

        # 查现有模块
        current_modules = await load_resume_modules_for_mutation(session, resume_id)
        module = next((m for m in current_modules if m.module_type == module_type), None)

        if module:
            # 更新现有模块
            module.content = new_content
        else:
            # 新建模块
            # 查当前最大 sort_order
            max_order_result = await session.execute(
                select(ResumeModule.sort_order)
                .where(ResumeModule.resume_id == resume_id)
                .order_by(ResumeModule.sort_order.desc())
                .limit(1)
            )
            max_order = max_order_result.scalar()
            module = ResumeModule(
                resume_id=resume_id,
                module_type=module_type,
                content=new_content,
                sort_order=(max_order + 1) if max_order is not None else 0,
            )
            session.add(module)

        await session.flush()  # 新建模块立即可见（供下方全量合并）

        # 同步 parsed_text + content_hash + 状态：与整份重写草稿路径一致。
        # ready 简历被 AI 单模块修改后内容与 Chroma 索引不一致 → 置 draft，
        # 避免 Agent 检索到旧索引内容。
        from services.resume_builder import _merge_modules_to_text

        all_modules = await load_resume_modules_for_mutation(session, resume_id)
        merged = _merge_modules_to_text(list(all_modules))
        resume.parsed_text = merged
        resume.content_hash = hashlib.sha256(merged.encode("utf-8")).hexdigest()
        resume.updated_at = datetime.now(timezone.utc)
        if resume.status == "ready":
            from services.resume_service import set_resume_status

            await set_resume_status(session, resume, "draft", reason="Agent 修改待确认")

        await session.commit()

    return f"✅ 模块 {module_type} 已更新并保存。"


async def _replace_all_modules_short_txn(
    user_id: int,
    resume_id: int,
    modules_data: list[dict],
    *,
    complete: bool = False,
    expected_module_types: set[str] | None = None,
    expected_module_revision: int | None = None,
) -> str:
    """全量替换所有模块（rewrite_star / translate / rewrite_resume 共用）。

    每个模块 dict: {module_type: str, content: dict, sort_order: int}

    两条路径：
    - complete=False (草稿): 替换模块 + 更新 parsed_text/content_hash，不触发索引、不 bump version
    - complete=True  (完成):  同上 + ensure_indexed + 清 embedding 缓存 + bump version + status=ready
    """
    from models.resume_module import ResumeModule
    from schemas.resume_module import validate_module_content
    from services.resume_module_mutation import (
        ResumeModuleConflictError,
        load_resume_modules_for_mutation,
        lock_resume_for_module_mutation,
    )

    # 入口批量校验——任何错误都发生在打开事务和删除旧模块之前。
    from pydantic import ValidationError

    if not modules_data:
        raise ToolRetryError("全量替换 modules 不能为空。")

    for idx, mod in enumerate(modules_data):
        if not isinstance(mod, dict):
            raise ToolRetryError(f"全量替换模块 {idx} 不是对象。")
        if not isinstance(mod.get("module_type"), str):
            raise ToolRetryError(f"全量替换模块 {idx} module_type 必须为字符串。")

    module_types = [mod.get("module_type") for mod in modules_data]
    duplicate_types = sorted(
        str(module_type)
        for module_type in set(module_types)
        if module_types.count(module_type) > 1
    )
    if duplicate_types:
        raise ToolRetryError("全量替换 module_type 重复: " + ", ".join(duplicate_types))

    for mod in modules_data:
        source = mod.get("source", "unknown")
        if source not in ("fact", "inferred", "mixed", "unknown"):
            raise ToolRetryError(
                f"模块 {mod.get('module_type', '?')} source 非法: {source!r}"
            )
        try:
            validate_module_content(mod["module_type"], mod["content"])
        except ValidationError as e:
            raise ToolRetryError(
                f"模块 {mod.get('module_type', '?')} content 校验失败（{len(e.errors())} 处）:\n"
                + format_validation_error(e)
                + "\n请补充/修正必填字段（不能缺失或为空字符串）后重新调用工具提交。"
            ) from e
        except Exception as e:  # noqa: BLE001 未知 module_type 等
            raise ToolRetryError(f"模块 {mod.get('module_type', '?')} content 校验失败: {e}") from e

    async with AsyncSessionLocal() as session:
        # 校验归属
        try:
            resume = await lock_resume_for_module_mutation(
                session,
                user_id,
                resume_id,
                expected_revision=expected_module_revision,
            )
        except ResumeModuleConflictError as e:
            raise ToolRetryError(str(e)) from e
        if resume is None:
            return f"⚠️ 简历 {resume_id} 不存在或无权访问。"

        # 锁内 CAS：校验 LLM 生成期间父记录和模块集合均未变化，再允许删除。
        old_modules = await load_resume_modules_for_mutation(session, resume_id)
        if expected_module_types is not None:
            current_module_types = {module.module_type for module in old_modules}
            if current_module_types != set(expected_module_types):
                raise ToolRetryError("简历模块集合已发生并发变化，拒绝覆盖；请基于最新内容重试。")

        # CAS 通过后才删除旧模块。
        for old_mod in old_modules:
            await session.delete(old_mod)
        await session.flush()

        # 插新模块
        for idx, mod_data in enumerate(modules_data):
            module = ResumeModule(
                resume_id=resume_id,
                module_type=mod_data["module_type"],
                content=mod_data["content"],
                sort_order=mod_data.get("sort_order", idx),
                # G 可信度控制：AI 改写内容来源标注（fact/inferred/mixed）
                source=mod_data.get("source", "unknown"),
            )
            session.add(module)

        # 合并模块 → parsed_text + content_hash（两条路径都需要）
        from services.resume_builder import _merge_modules_to_text

        new_modules = []
        for idx, mod_data in enumerate(modules_data):
            m = ResumeModule(
                resume_id=resume_id,
                module_type=mod_data["module_type"],
                content=mod_data["content"],
                sort_order=mod_data.get("sort_order", idx),
            )
            m.id = idx  # _merge_modules_to_text 排序用
            new_modules.append(m)
        parsed_text = _merge_modules_to_text(new_modules)
        resume.parsed_text = parsed_text
        resume.content_hash = hashlib.sha256(parsed_text.encode("utf-8")).hexdigest()
        resume.updated_at = datetime.now(timezone.utc)

        # 草稿路径：改写内容待用户确认（未点"完成"发布），置为 draft。
        # 不设 status 的话，ready 简历被 Agent 改写后 status 仍 ready 但 parsed_text
        # 已变、Chroma 未重建 → Agent 会检索到旧索引内容（内容与表单不一致）。
        if not complete:
            from services.resume_service import set_resume_status

            await set_resume_status(session, resume, "draft", reason="Agent 改写待确认")

        if complete:
            # 完成路径：立即触发索引 + bump version + status=ready
            from core import cache as embedding_cache
            from services.rag.clients import knowledge_collection_name
            from services.rag.ensure_indexed import ensure_indexed
            from services.rag.asset_source import ASSET_TYPE_RESUME

            await embedding_cache.clear_resume(resume_id)
            try:
                indexed = await ensure_indexed(
                    session,
                    user_id=user_id,
                    asset_id=resume_id,
                    asset_type=ASSET_TYPE_RESUME,
                    collection=knowledge_collection_name(user_id),
                )
                if not indexed:
                    raise RuntimeError("ensure_indexed failed")
            except Exception as e:
                await session.rollback()
                logger.exception("Failed to rebuild vectors for resume %d", resume_id)
                return f"⚠️ 向量化重建失败: {e}"

            from services.resume_service import set_resume_status

            await set_resume_status(session, resume, "ready", reason="Agent 重写并发布")
            resume.version += 1

        await session.commit()

    if complete:
        return f"✅ 简历已重写并发布，共 {len(modules_data)} 个模块已保存，版本 {resume.version}。"
    return f"✅ 简历已重写为草稿，共 {len(modules_data)} 个模块已保存。"


async def _get_module_content(
    db: AsyncSession,
    user_id: int,
    resume_id: int,
    module_type: str,
):
    """读取指定模块的 content（用传入的 db session）。"""
    from models.resume import Resume
    from models.resume_module import ResumeModule

    result = await db.execute(
        select(Resume).where(Resume.id == resume_id, Resume.user_id == user_id)
    )
    resume = result.scalar_one_or_none()
    if resume is None:
        return None, None

    mod_result = await db.execute(
        select(ResumeModule).where(
            ResumeModule.resume_id == resume_id,
            ResumeModule.module_type == module_type,
        )
    )
    module = mod_result.scalar_one_or_none()
    return resume, module


class GenerateModuleTool(Tool):
    name = "generate_module"
    description = "AI 生成指定模块的内容（JSON 格式），生成后直接写入数据库"
    args_model = GenerateModuleArgs
    category = "builder"

    async def _execute(self, **kwargs) -> str:
        resume_id = kwargs.get("resume_id")
        module_type = kwargs.get("module_type")
        prompt = kwargs.get("prompt", "")
        few_shot = kwargs.get("few_shot") or ""

        # 获取简历 + 现有模块上下文
        try:
            resume, modules = await get_resume_with_modules(self.db, self.user_id, resume_id)
        except HTTPException:
            return f"⚠️ 简历 {resume_id} 不存在或无权访问。"

        # 构建 LLM prompt
        from schemas.resume_module import MODULE_CONTENT_SCHEMAS, ModuleType

        try:
            mt = ModuleType(module_type) if isinstance(module_type, str) else module_type
        except ValueError:
            return f"⚠️ 未知模块类型: {module_type}"

        schema_class = MODULE_CONTENT_SCHEMAS.get(mt)
        if schema_class is None:
            return f"⚠️ 模块类型 {module_type} 无对应 schema。"

        # 收集现有简历上下文（其他模块的内容摘要，脱敏后传给 LLM）
        context_parts = []
        for mod in modules:
            if mod.module_type != module_type:
                sanitized = (
                    sanitize_resume_module_for_ai(mod.module_type, mod.content) if isinstance(mod.content, dict) else mod.content
                )
                context_parts.append(
                    f"- {mod.module_type}: {_json.dumps(sanitized, ensure_ascii=False)[:200]}"
                )
        context_str = "\n".join(context_parts) if context_parts else "（空简历）"

        # 内部 function calling：parameters = 该模块 content schema 本身
        tool_schema = _make_function_schema(
            name="submit_module_content",
            description=f"提交 {module_type} 模块的完整 content。调用时把生成结果填入工具参数即可，不要输出解释文字。",
            parameters=schema_class.model_json_schema(),
        )
        system = (
            "你是专业简历撰写助手。请根据用户信息生成指定模块的内容。\n"
            "你必须通过调用 submit_module_content 工具提交结果：将完整 content 作为该工具的参数。"
        )
        if few_shot:
            system += (
                "\n\n参考范文示例（仅作结构与表述参照，内容必须基于用户真实信息，"
                "不得照抄范文中的他人经历/姓名/学校/公司）：\n"
                f"{few_shot[:3000]}"
            )
        user_msg = (
            f"模块类型: {module_type}\n"
            f"用户补充说明: {prompt or '无'}\n"
            f"现有简历上下文:\n{context_str}\n\n"
            f"请生成 {module_type} 模块的 content 并通过 submit_module_content 工具提交。"
        )

        try:
            response = await _stream_tool_llm(
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_msg},
                ],
                tools=[tool_schema],
                tool_name="generate_module",
                emit=self.emit,
                temperature=0.1,
                max_tokens=2000,
                model=_BUILDER_GEN_MODEL,
                user_id=self.user_id,
                usage_target=self.last_usage,
            )
            # 工具参数即 content（parameters == content schema）
            content = _extract_tool_args(response, "submit_module_content")
        except ToolRetryError:
            raise
        except Exception as e:
            return f"⚠️ AI 生成失败：{e}"

        # Real SSE Agent writes use the same Proposal-Commit boundary as the
        # full-resume tools; direct calls retain the compatibility transaction.
        existing = next((m for m in modules if m.module_type == module_type), None)
        if self.emit is not None and getattr(settings, "AGENT_PROPOSAL_COMMIT_ENABLED", True):
            from services.react_agent.proposal_commit import ProposalCommitService, ProposalError

            operation = {
                "module_type": module_type,
                "content": _restore_sensitive_placeholders(
                    [{"module_type": module_type, "content": content}],
                    [{"module_type": module_type, "content": existing.content}],
                )[0]["content"] if existing is not None else content,
                "sort_order": existing.sort_order if existing is not None else len(modules),
                "source": getattr(existing, "source", "unknown") if existing is not None else "unknown",
            }
            proposal_service = ProposalCommitService()
            idempotency_key = uuid.uuid4().hex
            try:
                proposal = await proposal_service.create(
                    user_id=self.user_id,
                    resume_id=resume_id,
                    call_id=f"generate_module:{uuid.uuid4().hex}",
                    operations=[operation],
                    rationale=f"generate_module:{module_type}",
                    idempotency_key=idempotency_key,
                )
                await _await_proposal_approval(
                    proposal=proposal,
                    user_id=self.user_id,
                    tool_name=self.name,
                    emit=self.emit,
                    rationale=f"generate_module:{module_type}",
                )
                result = f"✅ 已通过 Proposal-Commit 应用模块生成（proposal_id={proposal.proposal_id}）"
            except ProposalError as exc:
                raise ToolRetryError(f"Proposal 提交失败: {exc}") from exc
        else:
            result = await _update_module_short_txn(
                self.user_id,
                resume_id,
                module_type,
                content,
                restore_content=existing.content if existing is not None else None,
            )
        return result


class CheckModuleTool(Tool):
    name = "check_module"
    description = "检查模块的完整性和 ATS 兼容性，返回改进建议（不修改内容）"
    args_model = CheckModuleArgs
    category = "builder"

    async def _execute(self, **kwargs) -> str:
        resume_id = kwargs.get("resume_id")
        module_type = kwargs.get("module_type")

        resume, module = await _get_module_content(
            self.db,
            self.user_id,
            resume_id,
            module_type,
        )
        if resume is None:
            return f"⚠️ 简历 {resume_id} 不存在或无权访问。"
        if module is None:
            return f"⚠️ 模块 {module_type} 不存在，请先生成。"

        # 脱敏后传给 LLM
        sanitized_content = (
            sanitize_resume_module_for_ai(module.module_type, module.content) if isinstance(module.content, dict) else module.content
        )
        sanitized_str = _json.dumps(sanitized_content, ensure_ascii=False, indent=2)

        system = (
            "你是 ATS（Applicant Tracking System）简历检查专家。"
            f"当前日期是 {datetime.now(timezone.utc).date().isoformat()}。"
            "分析给定模块的内容，检查以下方面：\n"
            "1. 完整性：必填字段是否缺失\n"
            "2. ATS 兼容性：是否包含 ATS 难以解析的格式（特殊符号、图片引用等）\n"
            "3. 专业性：用词是否专业、表述是否清晰\n"
            "4. 一致性：日期格式、字段值是否统一\n\n"
            "事实约束：只能依据提供的模块内容判断；项目链接属于可选增强项，不得当作必填缺失；"
            "不得建议用户虚构并发量、性能提升、用户数或任何量化结果；证据不足时应提出需要补充的问题。"
            "不要把 JSON 字段名当成用户内容，不要输出 emoji 或装饰符号。\n\n"
            "输出格式：\n"
            "## 检查结果\n"
            "- 完整性: 通过/需改进 + 说明\n"
            "- ATS兼容性: 通过/需改进 + 说明\n"
            "- 专业性: 通过/需改进 + 说明\n"
            "- 一致性: 通过/需改进 + 说明\n\n"
            "## 改进建议\n"
            "1. ...\n"
            "2. ...\n"
        )
        user_msg = f"模块类型: {module_type}\n模块内容:\n{sanitized_str}\n\n请检查以上模块内容。"

        if self.emit is None:
            # A read-only direct call does not need the tool-calling wrapper;
            # use the cheaper text path and keep the editor/SSE path streamed.
            return await llm_generate(
                system,
                user_msg,
                temperature=0,
                max_tokens=1200,
                user_id=self.user_id,
                scenario="field_rewrite",
            )
        check_resp = await _stream_tool_llm(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_msg},
            ],
            tools=None,
            tool_name="check_module",
            emit=self.emit,
            temperature=0,
            max_tokens=1200,
            user_id=self.user_id,
            usage_target=self.last_usage,
        )
        return check_resp.content


class ModifyModuleTool(Tool):
    name = "modify_module"
    description = "按指令定向修改模块内容（如 '把工作描述改为 STAR 格式'），修改后直接写入数据库"
    args_model = ModifyModuleArgs
    category = "builder"

    async def _execute(self, **kwargs) -> str:
        resume_id = kwargs.get("resume_id")
        module_type = kwargs.get("module_type")
        instruction = kwargs.get("instruction")

        resume, module = await _get_module_content(
            self.db,
            self.user_id,
            resume_id,
            module_type,
        )
        if resume is None:
            return f"⚠️ 简历 {resume_id} 不存在或无权访问。"
        if module is None:
            return f"⚠️ 模块 {module_type} 不存在，请先用 generate_module 生成。"

        # 脱敏后传给 LLM
        sanitized_content = (
            sanitize_resume_module_for_ai(module.module_type, module.content) if isinstance(module.content, dict) else module.content
        )
        sanitized_str = _json.dumps(sanitized_content, ensure_ascii=False, indent=2)

        from schemas.resume_module import MODULE_CONTENT_SCHEMAS, ModuleType

        try:
            mt = ModuleType(module_type) if isinstance(module_type, str) else module_type
        except ValueError:
            return f"⚠️ 未知模块类型: {module_type}"

        schema_class = MODULE_CONTENT_SCHEMAS.get(mt)

        # 内部 function calling：parameters = 该模块 content schema 本身
        tool_schema = _make_function_schema(
            name="submit_modified_content",
            description=f"提交修改后的 {module_type} 模块完整 content（完整 JSON 对象，不是 diff，不是解释文字）。",
            parameters=schema_class.model_json_schema(),
        )
        system = (
            "你是简历修改助手。根据修改指令修改指定模块内容。\n"
            "必须通过调用 submit_modified_content 工具提交修改后的完整 content。"
        )
        user_msg = (
            f"模块类型: {module_type}\n"
            f"当前内容:\n{sanitized_str}\n\n"
            f"修改指令: {instruction}\n\n"
            f"请输出修改后的完整 content 并通过 submit_modified_content 工具提交。"
        )

        try:
            response = await _stream_tool_llm(
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_msg},
                ],
                tools=[tool_schema],
                tool_name="modify_module",
                emit=self.emit,
                temperature=0.1,
                max_tokens=2000,
                model=_BUILDER_GEN_MODEL,
                user_id=self.user_id,
                usage_target=self.last_usage,
            )
            # 工具参数即修改后的 content
            content = _extract_tool_args(response, "submit_modified_content")
        except ToolRetryError:
            raise
        except Exception as e:
            return f"⚠️ AI 修改失败：{e}"

        # Real SSE Agent writes use Proposal-Commit; direct legacy calls keep
        # the existing short transaction until their caller is migrated.
        if self.emit is not None and getattr(settings, "AGENT_PROPOSAL_COMMIT_ENABLED", True):
            from services.react_agent.proposal_commit import ProposalCommitService, ProposalError

            operation = {
                "module_type": module_type,
                "content": _restore_sensitive_placeholders(
                    [{"module_type": module_type, "content": content}],
                    [{"module_type": module_type, "content": module.content}],
                )[0]["content"] if module is not None else content,
                "sort_order": module.sort_order if module is not None else 0,
                "source": getattr(module, "source", "unknown") if module is not None else "unknown",
            }
            proposal_service = ProposalCommitService()
            idempotency_key = uuid.uuid4().hex
            try:
                proposal = await proposal_service.create(
                    user_id=self.user_id,
                    resume_id=resume_id,
                    call_id=f"modify_module:{uuid.uuid4().hex}",
                    operations=[operation],
                    rationale=instruction,
                    idempotency_key=idempotency_key,
                )
                await _await_proposal_approval(
                    proposal=proposal,
                    user_id=self.user_id,
                    tool_name=self.name,
                    emit=self.emit,
                    rationale=instruction,
                )
                result = f"✅ 已通过 Proposal-Commit 应用模块修改（proposal_id={proposal.proposal_id}）"
            except ProposalError as exc:
                raise ToolRetryError(f"Proposal 提交失败: {exc}") from exc
        else:
            result = await _update_module_short_txn(
                self.user_id,
                resume_id,
                module_type,
                content,
                restore_content=module.content if module is not None else None,
            )
        return result


class RewriteResumeTool(Tool):
    name = "rewrite_resume"
    description = (
        "整份简历重写：generate 模式（空简历→整份生成）或 optimize 模式（现有内容→按岗位优化）"
    )
    args_model = RewriteResumeArgs
    category = "builder"

    async def _execute(self, **kwargs) -> str:
        resume_id = kwargs.get("resume_id")
        mode = kwargs.get("mode", "generate")
        target_position = kwargs.get("target_position")
        few_shot = kwargs.get("few_shot") or ""

        resume, modules = await get_resume_with_modules(self.db, self.user_id, resume_id)
        if resume is None:
            return f"⚠️ 简历 {resume_id} 不存在或无权访问。"

        # 构建现有内容摘要
        if modules:
            context_parts = []
            for mod in modules:
                sanitized = (
                    sanitize_resume_module_for_ai(mod.module_type, mod.content) if isinstance(mod.content, dict) else mod.content
                )
                context_parts.append(
                    f"- {mod.module_type}: {_json.dumps(sanitized, ensure_ascii=False)[:300]}"
                )
            existing_context = "\n".join(context_parts)
        else:
            existing_context = "（空简历，无现有模块）"

        position_hint = f"，目标岗位：{target_position}" if target_position else ""

        if mode == "generate":
            system_prompt = (
                "你是专业简历撰写专家。请根据用户信息生成一份完整的简历。\n"
                f"{position_hint}\n"
                "必须包含至少：basic_info、education、work_experience、skills 四个核心模块；"
                "可选模块：project_experience、language、honors、certificates 等。\n"
                "必须通过调用 submit_rewritten_resume 工具提交，modules 参数为模块数组，"
                "每个元素含 module_type、content、sort_order、source；source 标注内容来源："
                "fact=简历事实/inferred=AI 推断补充/mixed=混合，不得把推断标为 fact。\n"
                "【重要】用户信息不完整时不得编造：若缺少教育背景/工作经历等核心信息，"
                "不要虚构经历，而是明确列出缺失项并建议用户先补充（或引导用户使用信息追问）。"
            )
        else:
            system_prompt = (
                "你是简历优化专家。请根据目标岗位优化现有简历内容。\n"
                f"{position_hint}\n"
                "保持原有模块结构，通过 submit_rewritten_resume 工具提交优化后的完整 modules 数组，"
                "每模块带 source 标注（fact=简历事实/inferred=AI 推断/mixed=混合），不得把推断标为 fact。"
            )
        if few_shot:
            system_prompt += (
                "\n\n参考范文（仅作结构与措辞参照，内容必须基于用户真实信息，"
                "不得照抄范文中的他人经历/姓名/学校/公司）：\n"
                f"{few_shot[:4000]}"
            )

        user_msg = (
            f"模式: {mode}\n"
            f"目标岗位: {target_position or '未指定'}\n"
            f"现有简历内容:\n{existing_context}\n\n"
            f"请{'生成' if mode == 'generate' else '优化'}完整简历并通过 submit_rewritten_resume 工具提交。"
        )

        # 复用公共写模块辅助：function calling 提交完整 modules → 校验 → 全量替换
        # 一律落草稿（不自动完成）：改写结果在前端实时预览并标记未保存，
        # 由用户审阅后显式点击「草稿/完成」才生效（完成才重建索引供 Agent 检索）。
        return await _submit_modules_via_llm(
            self.user_id,
            resume_id,
            system_prompt,
            user_msg,
            fail_prefix="AI 重写失败",
            emit=self.emit,
            usage_target=self.last_usage,
            complete=False,
            tool_name="rewrite_resume",
            rationale=("按目标岗位优化整份简历" if mode == "optimize" else "生成整份简历"),
            required_module_types={module.module_type for module in modules} if modules else None,
            expected_module_revision=resume.module_revision,
        )


class AskInfoTool(Tool):
    name = "ask_info"
    description = "编辑模式下追问用户补充信息（分析简历缺失项 → 生成追问问题）"
    args_model = AskInfoArgs
    category = "builder"

    async def _execute(self, **kwargs) -> str:
        resume_id = kwargs.get("resume_id")
        question = kwargs.get("question")

        resume, modules = await get_resume_with_modules(self.db, self.user_id, resume_id)
        if resume is None:
            return f"⚠️ 简历 {resume_id} 不存在或无权访问。"

        # 分析现有模块覆盖情况
        from schemas.resume_module import ModuleType

        existing_types = {mod.module_type for mod in modules}
        all_types = [mt.value for mt in ModuleType]
        missing_types = [t for t in all_types if t not in existing_types]

        # 收集已有模块的摘要
        filled_parts = []
        empty_parts = []
        for mod in modules:
            content_str = _json.dumps(mod.content, ensure_ascii=False)
            if (
                content_str == "{}"
                or content_str == '{"entries": []}'
                or content_str == '{"categories": []}'
            ):
                empty_parts.append(mod.module_type)
            else:
                filled_parts.append(f"- {mod.module_type}: {content_str[:150]}")

        context = (
            "已有模块:\n" + ("\n".join(filled_parts) if filled_parts else "（无）") + "\n"
            "缺失模块:\n" + (", ".join(missing_types) if missing_types else "（无）") + "\n"
            "空内容模块:\n" + (", ".join(empty_parts) if empty_parts else "（无）")
        )

        system = (
            "你是简历编辑助手。用户正在编辑简历，可能有信息缺失。"
            "根据简历当前状态和用户的问题，给出需要补充的信息建议。\n"
            "输出格式：\n"
            "1. 针对用户问题的回答\n"
            "2. 建议补充的信息列表（标注优先级：高/中/低）\n"
            "控制在 300 字以内。"
        )
        user_msg = (
            f"用户问题: {question}\n\n"
            f"简历当前状态:\n{context}\n\n"
            f"请回答用户问题并建议需要补充的信息。"
        )

        ask_resp = await _stream_tool_llm(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_msg},
            ],
            tools=None,
            tool_name="ask_info",
            emit=self.emit,
            temperature=0.3,
            max_tokens=1000,
            user_id=self.user_id,
        )
        return ask_resp.content


# ═══════════════════════════════════════════════════════════
# TOOL_REGISTRY
# ═══════════════════════════════════════════════════════════


TOOL_REGISTRY: dict[str, list[type[Tool]]] = {
    "qa": [
        SearchResumeTool,
        SearchAssetsTool,
        GetResumeContentTool,
        AnswerFromIndexTool,
        SaveMemoryTool,
        RecallMemoryTool,
        JDMatchTool,
        DiagnoseResumeTool,
        CompareResumesTool,
        RewriteStarTool,
        TranslateTool,
        InterviewCoachTool,
        CoverLetterTool,
        SearchJobsLiveTool,
        WebSearchTool,
        NegotiationBriefTool,  # I3: 谈薪简报（qa 16）
        SearchCorpusTool,  # B3: 公共语料检索（面经/题库/范文，qa 17）
        SpawnTool,  # 子代理委派（qa 18）
    ],
    "builder": [
        GenerateModuleTool,
        CheckModuleTool,
        ModifyModuleTool,
        RewriteResumeTool,
        AskInfoTool,
    ],
}

# v2: unified = qa + builder 合并（/ask/agent 统一使用）
TOOL_REGISTRY["unified"] = TOOL_REGISTRY["qa"] + TOOL_REGISTRY["builder"]


# ═══════════════════════════════════════════════════════════
# 查询函数
# ═══════════════════════════════════════════════════════════


def get_tools_for_agent() -> list[type[Tool]]:
    """/ask/agent 工具集 = unified(22)，qa + builder 合并。"""
    return TOOL_REGISTRY["unified"]


def get_tools_for_builder() -> list[type[Tool]]:
    """/ask/builder 工具集（已废弃，保留向后兼容）。

    .. deprecated:: v2
        使用 get_tools_for_agent() 获取统一工具集。
    """
    import warnings

    warnings.warn(
        "get_tools_for_builder() 已废弃，请使用 get_tools_for_agent()",
        DeprecationWarning,
        stacklevel=2,
    )
    return TOOL_REGISTRY["builder"]


def get_tool_by_name(name: str) -> type[Tool] | None:
    """按工具名查找工具类（在 unified 集中查找）。"""
    for tool_class in TOOL_REGISTRY["unified"]:
        if tool_class.name == name:
            return tool_class
    return None


def get_agent_schemas(strict: bool | None = None) -> list[dict]:
    """获取 /ask/agent 的 OpenAI function calling schema 列表（unified）。"""
    return [tool_class().to_openai_schema(strict=strict) for tool_class in get_tools_for_agent()]


def get_agent_tool_descriptors():
    """Return runtime policy metadata without changing provider schemas."""
    from services.react_agent.tool_registry import build_tool_descriptors

    return build_tool_descriptors(get_tools_for_agent())


def get_builder_schemas() -> list[dict]:
    """获取 builder 工具的 schema 列表（已废弃）。"""
    import warnings

    warnings.warn(
        "get_builder_schemas() 已废弃，请使用 get_agent_schemas()",
        DeprecationWarning,
        stacklevel=2,
    )
    return [tool_class().to_openai_schema() for tool_class in TOOL_REGISTRY["builder"]]
