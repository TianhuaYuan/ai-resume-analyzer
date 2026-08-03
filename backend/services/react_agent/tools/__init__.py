"""工具注册表 — unified 18 工具（v2 合并 qa + builder）。

T11 创建骨架 + 注册表；T12/T13/T28 填充 _execute 实现。
v2 统一 Agent 编辑器：合并 qa(13) + builder(5) → unified(18)。

分类：
  qa (13):      search_resume / jd_match / diagnose_resume / compare_resumes
                rewrite_star / translate / interview_coach 等
  builder (5):  generate_module / check_module / modify_module
                rewrite_resume / ask_info
  unified (18): qa + builder 全部工具（/ask/agent 统一使用）
"""

from fastapi import HTTPException
from pydantic import BaseModel, Field
import hashlib
from datetime import datetime, timezone

from services.analyze_service import analyze_resume
from services.match_jd_service import match_jd
from services.react_agent.tools.base import Tool
from utils.privacy import sanitize_for_ai
from services.rag.asset_source import ASSET_TYPE_RESUME
from services.rag.clients import knowledge_collection_name
from services.rag.ensure_indexed import ensure_indexed
from services.rag.pipeline import (
    LLMToolResponse,
    ToolCall,
    llm_generate,
    llm_generate_with_tools,
    llm_generate_with_tools_stream,
)
from services.rag.retrieval import hybrid_search, hybrid_search_corpus, rerank
from services.resume_builder import get_resume_with_modules
from services.resume_service import compare_resumes


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
    resume_ids: list[int] = Field(..., description="要对比的简历 ID 列表（至少 2 个）")


class RewriteStarArgs(BaseModel):
    resume_id: int = Field(..., description="简历 ID")
    target_position: str | None = Field(None, description="目标岗位（可选，用于定向优化）")


class TranslateArgs(BaseModel):
    resume_id: int = Field(..., description="简历 ID")
    target_lang: str = Field(..., description="目标语言（如 en/ja）")


class InterviewCoachArgs(BaseModel):
    resume_id: int = Field(..., description="简历 ID")
    target_position: str = Field(..., description="目标岗位")


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
    mode: str = Field("generate", description="模式：generate（空简历生成）或 optimize（现有内容优化）")
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

        # T6 懒索引：首次检索 / 内容变更后触发重建
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

        # 填充结构化来源（Spec A#10: 用于 agent_done.sources 聚合去重）
        self.sources = [
            {
                "section": chunk.get("section", "未知"),
                "text": chunk.get("text", ""),
                "score": chunk.get("rerank_score", chunk.get("score", 0)),
            }
            for chunk in reranked
        ]

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

        text = (resume.parsed_text or "").strip()
        if text:
            return f"简历《{resume.filename}》内容（约 {len(text)} 字）：\n{text[:8000]}"

        # 草稿/未合并：读模块内容兜底（实时工作区）
        from services.resume_builder import get_resume_with_modules

        _, modules = await get_resume_with_modules(self.db, self.user_id, resume_id)
        if modules:
            lines = [f"【{m.module_type}】{m.content}" for m in modules if m.content]
            body = "\n".join(lines)
            if body:
                return f"简历《{resume.filename}》内容（模块视图，未合并渲染）：\n{body[:8000]}"
        return "⚠️ 简历内容为空。"


class SearchAssetsArgs(BaseModel):
    query: str = Field(..., description="检索查询词")
    asset_type: str = Field("resume", description="资产类型（resume/jd/interview/note）")
    asset_ids: list[int] = Field(..., description="要检索的资产 ID 列表")


class SearchAssetsTool(Tool):
    """T12：知识资产库检索（T7 每用户集合 + scope 过滤）。"""
    name = "search_assets"
    description = "在知识资产库（可跨多份简历/JD/面试记录）中检索与查询语义相关的段落，返回 top5 结构化结果（含来源资产与版本）。"
    args_model = SearchAssetsArgs
    category = "qa"

    async def _execute(self, **kwargs) -> str:
        query = kwargs["query"]
        asset_type = kwargs["asset_type"]
        asset_ids = kwargs["asset_ids"]
        if not asset_ids:
            return "⚠️ 请指定要检索的资产 ID 列表。"

        scope = {asset_type: asset_ids}
        chunks = await hybrid_search_corpus(self.user_id, scope, query, top_k=20)
        if not chunks:
            return "未找到相关内容。"

        reranked = await rerank(query, chunks, top_k=5)
        if not reranked:
            return "未找到相关内容。"

        self.sources = [
            {
                "asset_id": c.get("asset_id"),
                "asset_type": asset_type,
                "version": c.get("version"),
                "section": c.get("section", "未知"),
                "text": c.get("text", ""),
                "score": c.get("rerank_score", c.get("score", 0)),
            }
            for c in reranked
        ]

        lines = [f"找到 {len(reranked)} 条相关结果：\n"]
        for i, c in enumerate(reranked, 1):
            asset = c.get("asset_id", "?")
            ver = c.get("version", "?")
            score = c.get("rerank_score", c.get("score", 0))
            lines.append(f"{i}. [资产{asset}:v{ver}] ({c.get('section', '未知')}) (评分: {score:.2f})\n{c.get('text', '')}\n")
        return "\n".join(lines)


class AnswerFromIndexArgs(BaseModel):
    question: str = Field(..., description="问题")
    resume_id: int = Field(..., description="当前简历 ID")


class AnswerFromIndexTool(Tool):
    """T12：agentic RAG 深度检索回答（T11 run_answer_from_index 入口）。"""
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
        self.sources = result["sources"]
        return answer


class SaveMemoryArgs(BaseModel):
    snippet: str = Field(..., description="要记住的原子事实（一条独立、可检索的记忆）")
    memory_type: str = Field("episodic", description="类型：episodic（原始情节）/ semantic（提炼后的语义事实）")
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
    description = "按语义召回用户的长期记忆片段（L4），用于跨会话一致性、参考用户偏好/目标/历史决策。"
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
                db=self.db, user_id=self.user_id,
                resume_id=resume_id, jd_text=jd_text,
            )
            return result.get("analysis", "分析结果为空")
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
        has_error = False

        for analysis_type in ("experience", "score"):
            try:
                result = await analyze_resume(
                    db=self.db, user_id=self.user_id,
                    resume_id=resume_id, analysis_type=analysis_type,
                )
                analysis = result.get("analysis", "")
                label = "经历分析" if analysis_type == "experience" else "评分"
                sections.append(f"## {label}\n{analysis}")
            except HTTPException as e:
                has_error = True
                if "不存在" in str(e.detail):
                    return f"⚠️ 简历不存在或无权访问。"
                sections.append(f"## {analysis_type}\n分析失败: {e.detail}")
            except Exception as e:
                has_error = True
                sections.append(f"## {analysis_type}\n分析失败: {e}")

        if not sections:
            return "⚠️ 诊断失败，请稍后重试。"

        return "\n\n".join(sections)


class CompareResumesTool(Tool):
    name = "compare_resumes"
    description = "对比多份简历的优劣，给出综合裁决"
    args_model = CompareResumesArgs
    category = "qa"

    async def _execute(self, **kwargs) -> str:
        resume_ids = kwargs.get("resume_ids")

        try:
            result = await compare_resumes(
                db=self.db, user_id=self.user_id,
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

        lines = [f"对比 {len(resumes)} 份简历："]
        for r in resumes:
            lines.append(f"  - {r['filename']} (ID: {r['id']})")

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
        resume, input_context = await _read_modules_context(self.db, self.user_id, resume_id)
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
            "覆盖输入中的所有模块（不增不减 module_type），每个元素含 module_type、content、sort_order。\n"
            "对 work_experience/project_experience/club_activities 等经历类模块 entries 的 description 用 STAR 结构重写；"
            "其余模块（basic_info/skills/language 等）保持内容不变。保持事实不变，不要编造。"
        )
        user_msg = (
            f"目标岗位: {target_position or '未指定'}\n"
            f"当前简历模块:\n{input_context}\n\n"
            f"请对经历类描述做 STAR 改写，并通过 submit_rewritten_resume 提交完整 modules 数组。"
        )
        return await _submit_modules_via_llm(
            self.user_id, resume_id, system, user_msg,
            fail_prefix="STAR 改写失败", emit=self.emit,
            usage_target=self.last_usage,
        )


class TranslateTool(Tool):
    name = "translate"
    description = "将简历翻译为指定语言（整份重写为模块草稿）"
    args_model = TranslateArgs
    category = "qa"

    async def _execute(self, **kwargs) -> str:
        resume_id = kwargs.get("resume_id")
        target_lang = kwargs.get("target_lang")

        resume, input_context = await _read_modules_context(self.db, self.user_id, resume_id)
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
            self.user_id, resume_id, system, user_msg,
            max_tokens=8000, fail_prefix="翻译失败", emit=self.emit,
            usage_target=self.last_usage,
        )


class InterviewCoachTool(Tool):
    name = "interview_coach"
    description = "基于简历模拟面试，生成可能的面试问题和回答建议（最多 8 轮）"
    args_model = InterviewCoachArgs
    category = "qa"

    async def _execute(self, **kwargs) -> str:
        resume_id = kwargs.get("resume_id")
        target_position = kwargs.get("target_position")

        resume = await self._get_resume(resume_id)
        if not resume:
            return "⚠️ 简历不存在或无权访问。"

        system = (
            f"你是面试教练，基于候选人的简历模拟 {target_position} 岗位的面试。"
            "生成最多 8 轮可能的面试问题和回答建议。"
            "每轮包含：问题、考察点、建议回答方向。"
            "回答建议要基于简历中的实际经历，不要编造。"
        )
        user = f"目标岗位：{target_position}\n\n简历内容：\n{resume.parsed_text}"

        return await llm_generate(system=system, user=user, user_id=self.user_id)


class RecommendJobsArgs(BaseModel):
    resume_id: int = Field(..., description="简历 ID（自动归属校验）")
    top_k: int = Field(5, ge=1, le=10, description="返回岗位数")
    job_type: str | None = Field(None, description="限定校招/社招/实习：campus/social/intern")


class RecommendJobsTool(Tool):
    """岗位匹配推荐：向量预筛（market_public 公共集合）+ LLM 精排评分。"""

    name = "recommend_jobs"
    description = "根据简历内容推荐匹配的校招/社招/实习岗位（向量预筛 + LLM 精排），返回匹配分、匹配点与差距"
    args_model = RecommendJobsArgs
    category = "qa"

    async def _execute(self, **kwargs) -> str:
        resume_id = kwargs["resume_id"]
        top_k = kwargs.get("top_k", 5)
        job_type = kwargs.get("job_type")

        from services.market_match_service import recommend_jobs

        try:
            items = await recommend_jobs(
                self.db, user_id=self.user_id, resume_id=resume_id,
                top_k=top_k, job_type=job_type,
            )
        except HTTPException as e:
            return f"⚠️ {e.detail}"
        except Exception as e:
            return f"⚠️ 岗位推荐失败: {e}"

        if not items:
            return "没有找到匹配的岗位，试试放宽筛选条件。"

        self.sources = [
            {
                "asset_id": it["id"],
                "title": it["title"],
                "company": it["company"],
                "score": it["score"],
                "job_type": it["job_type"],
            }
            for it in items
        ]

        _JT = {"campus": "校招", "social": "社招", "intern": "实习"}
        lines = [f"为你推荐 {len(items)} 个匹配岗位：\n"]
        for i, it in enumerate(items, 1):
            jt = _JT.get(it["job_type"], it["job_type"] or "")
            lines.append(
                f"{i}. {it['company'] or ''} {it['title']}（{jt}）匹配分 {it['score']}/100"
            )
            if it.get("matched"):
                lines.append(f"   匹配点: {'、'.join(it['matched'][:3])}")
            if it.get("gaps"):
                lines.append(f"   差距: {'、'.join(it['gaps'][:3])}")
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
# Builder 工具实现 (5) — T28
# 设计：短事务独立 commit + 编辑锁 TTL 2min 心跳
# ═══════════════════════════════════════════════════════════

import json as _json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import AsyncSessionLocal
from services.edit_lock import acquire_edit_lock, release_edit_lock


# ── Builder 工具公共辅助 ──


# builder 工具内部 function calling 使用的模型：judge=DeepSeek v4 flash。
# 注意：本代码库中 CHAT_MODEL（MiMo）从未被传过 tools，function calling 支持未验证；
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
        raise ValueError("AI 未通过工具提交内容，请重新调用工具提交。")
    tc = response.tool_calls[0]
    if tc.name != expected_name:
        raise ValueError(
            f"AI 调用了非预期工具 {tc.name}（期望 {expected_name}），请重新调用工具提交。"
        )
    try:
        args = _json.loads(tc.arguments) if tc.arguments else {}
    except (_json.JSONDecodeError, TypeError) as e:
        raise ValueError("工具参数 JSON 解析失败，请重新调用工具提交纯 JSON。") from e
    if not isinstance(args, dict):
        raise ValueError("工具参数应为 JSON 对象，请重新调用工具提交。")
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


class _RewriteResumeOutput(BaseModel):
    """rewrite_resume 的 submit_rewritten_resume 工具参数。"""

    modules: list[_RewrittenModule] = Field(
        ...,
        description="重写后的模块数组（generate 模式至少包含 basic_info/education/work_experience/skills 四个核心模块）",
    )


async def _read_modules_context(db, user_id: int, resume_id: int):
    """读简历 + 模块上下文。返回 (resume, input_context)。

    模块化简历走模块 JSON；上传型简历（无模块）用 parsed_text 兜底。
    简历不存在/无权访问时返回 (None, "")。
    """
    try:
        resume, modules = await get_resume_with_modules(db, user_id, resume_id)
    except HTTPException:
        return None, ""
    if resume is None:
        return None, ""
    if modules:
        parts = [
            f"- {m.module_type}: {_json.dumps(sanitize_for_ai(m.content) if isinstance(m.content, dict) else m.content, ensure_ascii=False)[:300]}"
            for m in modules
        ]
        return resume, "\n".join(parts)
    if resume.parsed_text:
        return resume, f"（无模块，原始文本）\n{resume.parsed_text[:8000]}"
    return resume, ""


async def _submit_modules_via_llm(
    user_id: int,
    resume_id: int,
    system_prompt: str,
    user_msg: str,
    *,
    tool_desc: str = "提交整份重写后的简历模块数组。modules 每项为 {module_type, content, sort_order}。",
    max_tokens: int = 4000,
    fail_prefix: str = "AI 重写失败",
    emit=None,
    usage_target: dict | None = None,
    complete: bool = False,
) -> str:
    """让 LLM 通过 function calling 提交完整 modules 数组 → 逐模块校验 → 短事务全量替换。

    改写/翻译/重写类工具共用。整份重写保证：_replace_all_modules_short_txn 删旧插新原子全量替换，
    且不新建 Resume（多轮对话累积到同一份草稿）。

    emit：工具内部 LLM 流式 token 回调（无则退化为非流式）。
    """
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
            temperature=0.1, max_tokens=max_tokens,
            model=_BUILDER_GEN_MODEL,
            user_id=user_id,
            usage_target=usage_target,
        )
        args = _extract_tool_args(response, "submit_rewritten_resume")
    except Exception as e:
        return f"⚠️ {fail_prefix}：{e}"

    raw_modules = args.get("modules")
    if not isinstance(raw_modules, list):
        return "⚠️ AI 重写结果格式错误：modules 应为数组。"

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
        try:
            mt = ModuleType(mt_str)
            validate_module_content(mt, content)
            validated_modules.append({
                "module_type": mt_str,
                "content": content,
                "sort_order": sort_order if isinstance(sort_order, int) and sort_order >= 0 else idx,
            })
        except (ValueError, ValidationError) as e:
            errors.append(f"模块 {idx} ({mt_str}): {e}")

    if not validated_modules:
        return f"⚠️ 重写结果校验失败，无有效模块:\n" + "\n".join(errors)

    result = await _replace_all_modules_short_txn(user_id, resume_id, validated_modules, complete=complete)
    if errors:
        result += f"\n⚠️ {len(errors)} 个模块校验失败被跳过。"
    return result


async def _update_module_short_txn(
    user_id: int,
    resume_id: int,
    module_type: str,
    new_content: dict,
) -> str:
    """短事务独立写入模块（独立 session + commit）。

    短事务设计：不在请求 session 中操作，每次独立开 session → flush → commit → close。
    避免长事务锁行 / 请求超时导致回滚。
    """
    from models.resume import Resume
    from models.resume_module import ResumeModule
    from schemas.resume_module import validate_module_content

    # 入口校验 content（T22 四方契约）
    try:
        validate_module_content(module_type, new_content)
    except Exception as e:
        return f"⚠️ 模块 {module_type} content 校验失败: {e}。请重新调用工具提交修正后的 content。"

    async with AsyncSessionLocal() as session:
        # 校验归属
        result = await session.execute(
            select(Resume).where(Resume.id == resume_id, Resume.user_id == user_id)
        )
        resume = result.scalar_one_or_none()
        if resume is None:
            return f"⚠️ 简历 {resume_id} 不存在或无权访问。"

        # 查现有模块
        mod_result = await session.execute(
            select(ResumeModule).where(
                ResumeModule.resume_id == resume_id,
                ResumeModule.module_type == module_type,
            )
        )
        module = mod_result.scalar_one_or_none()

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

        await session.commit()

    return f"✅ 模块 {module_type} 已更新并保存。"


async def _replace_all_modules_short_txn(
    user_id: int,
    resume_id: int,
    modules_data: list[dict],
    *,
    complete: bool = False,
) -> str:
    """全量替换所有模块（rewrite_star / translate / rewrite_resume 共用）。

    每个模块 dict: {module_type: str, content: dict, sort_order: int}

    两条路径：
    - complete=False (草稿): 替换模块 + 更新 parsed_text/content_hash，不触发索引、不 bump version
    - complete=True  (完成):  同上 + ensure_indexed + 清 embedding 缓存 + bump version + status=ready
    """
    from models.resume import Resume
    from models.resume_module import ResumeModule
    from schemas.resume_module import validate_module_content

    # 入口批量校验
    for mod in modules_data:
        try:
            validate_module_content(mod["module_type"], mod["content"])
        except Exception as e:
            return f"⚠️ 模块 {mod.get('module_type', '?')} content 校验失败: {e}。请重新调用工具提交修正后的 content。"

    async with AsyncSessionLocal() as session:
        # 校验归属
        result = await session.execute(
            select(Resume).where(Resume.id == resume_id, Resume.user_id == user_id)
        )
        resume = result.scalar_one_or_none()
        if resume is None:
            return f"⚠️ 简历 {resume_id} 不存在或无权访问。"

        # 删旧模块
        old_result = await session.execute(
            select(ResumeModule).where(ResumeModule.resume_id == resume_id)
        )
        for old_mod in old_result.scalars().all():
            await session.delete(old_mod)
        await session.flush()

        # 插新模块
        for idx, mod_data in enumerate(modules_data):
            module = ResumeModule(
                resume_id=resume_id,
                module_type=mod_data["module_type"],
                content=mod_data["content"],
                sort_order=mod_data.get("sort_order", idx),
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

            resume.status = "ready"
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
                sanitized = sanitize_for_ai(mod.content) if isinstance(mod.content, dict) else mod.content
                context_parts.append(f"- {mod.module_type}: {_json.dumps(sanitized, ensure_ascii=False)[:200]}")
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
                temperature=0.1, max_tokens=2000,
                model=_BUILDER_GEN_MODEL,
                user_id=self.user_id,
                usage_target=self.last_usage,
            )
            # 工具参数即 content（parameters == content schema）
            content = _extract_tool_args(response, "submit_module_content")
        except Exception as e:
            return f"⚠️ AI 生成失败：{e}"

        # 短事务写入（内部 validate_module_content 严格校验 + 失败回灌含修复指引）
        result = await _update_module_short_txn(
            self.user_id, resume_id, module_type, content,
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
            self.db, self.user_id, resume_id, module_type,
        )
        if resume is None:
            return f"⚠️ 简历 {resume_id} 不存在或无权访问。"
        if module is None:
            return f"⚠️ 模块 {module_type} 不存在，请先生成。"

        content_str = _json.dumps(module.content, ensure_ascii=False, indent=2)

        # 脱敏后传给 LLM
        sanitized_content = sanitize_for_ai(module.content) if isinstance(module.content, dict) else module.content
        sanitized_str = _json.dumps(sanitized_content, ensure_ascii=False, indent=2)

        system = (
            "你是 ATS（Applicant Tracking System）简历检查专家。"
            "分析给定模块的内容，检查以下方面：\n"
            "1. 完整性：必填字段是否缺失\n"
            "2. ATS 兼容性：是否包含 ATS 难以解析的格式（特殊符号、图片引用等）\n"
            "3. 专业性：用词是否专业、表述是否清晰\n"
            "4. 一致性：日期格式、字段值是否统一\n\n"
            "输出格式：\n"
            "## 检查结果\n"
            "- 完整性: ✅/⚠️/❌ + 说明\n"
            "- ATS兼容性: ✅/⚠️/❌ + 说明\n"
            "- 专业性: ✅/⚠️/❌ + 说明\n"
            "- 一致性: ✅/⚠️/❌ + 说明\n\n"
            "## 改进建议\n"
            "1. ...\n"
            "2. ...\n"
        )
        user_msg = (
            f"模块类型: {module_type}\n"
            f"模块内容:\n{sanitized_str}\n\n"
            f"请检查以上模块内容。"
        )

        check_resp = await _stream_tool_llm(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_msg},
            ],
            tools=None,
            tool_name="check_module",
            emit=self.emit,
            temperature=0.2, max_tokens=1500,
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
            self.db, self.user_id, resume_id, module_type,
        )
        if resume is None:
            return f"⚠️ 简历 {resume_id} 不存在或无权访问。"
        if module is None:
            return f"⚠️ 模块 {module_type} 不存在，请先用 generate_module 生成。"

        content_str = _json.dumps(module.content, ensure_ascii=False, indent=2)

        # 脱敏后传给 LLM
        sanitized_content = sanitize_for_ai(module.content) if isinstance(module.content, dict) else module.content
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
                temperature=0.1, max_tokens=2000,
                model=_BUILDER_GEN_MODEL,
                user_id=self.user_id,
                usage_target=self.last_usage,
            )
            # 工具参数即修改后的 content
            content = _extract_tool_args(response, "submit_modified_content")
        except Exception as e:
            return f"⚠️ AI 修改失败：{e}"

        # 短事务写入（内部 validate_module_content 严格校验 + 失败回灌含修复指引）
        result = await _update_module_short_txn(
            self.user_id, resume_id, module_type, content,
        )
        return result


class RewriteResumeTool(Tool):
    name = "rewrite_resume"
    description = "整份简历重写：generate 模式（空简历→整份生成）或 optimize 模式（现有内容→按岗位优化）"
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
                sanitized = sanitize_for_ai(mod.content) if isinstance(mod.content, dict) else mod.content
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
                "每个元素含 module_type、content、sort_order。"
            )
        else:
            system_prompt = (
                "你是简历优化专家。请根据目标岗位优化现有简历内容。\n"
                f"{position_hint}\n"
                "保持原有模块结构，通过 submit_rewritten_resume 工具提交优化后的完整 modules 数组。"
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
        return await _submit_modules_via_llm(
            self.user_id, resume_id, system_prompt, user_msg,
            fail_prefix="AI 重写失败", emit=self.emit,
            usage_target=self.last_usage,
            complete=(mode == "generate"),  # generate 模式自动完成
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
            if content_str == "{}" or content_str == '{"entries": []}' or content_str == '{"categories": []}':
                empty_parts.append(mod.module_type)
            else:
                filled_parts.append(f"- {mod.module_type}: {content_str[:150]}")

        context = (
            f"已有模块:\n" + ("\n".join(filled_parts) if filled_parts else "（无）") + "\n"
            f"缺失模块:\n" + (", ".join(missing_types) if missing_types else "（无）") + "\n"
            f"空内容模块:\n" + (", ".join(empty_parts) if empty_parts else "（无）")
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
            temperature=0.3, max_tokens=1000,
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
        RecommendJobsTool,
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
    """/ask/agent 工具集 = unified(18)，qa + builder 合并。"""
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


def get_agent_schemas() -> list[dict]:
    """获取 /ask/agent 的 OpenAI function calling schema 列表（unified）。"""
    return [tool_class().to_openai_schema() for tool_class in get_tools_for_agent()]


def get_builder_schemas() -> list[dict]:
    """获取 builder 工具的 schema 列表（已废弃）。"""
    import warnings
    warnings.warn(
        "get_builder_schemas() 已废弃，请使用 get_agent_schemas()",
        DeprecationWarning,
        stacklevel=2,
    )
    return [tool_class().to_openai_schema() for tool_class in TOOL_REGISTRY["builder"]]
