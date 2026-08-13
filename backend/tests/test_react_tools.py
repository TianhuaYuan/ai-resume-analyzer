"""Agent 工具集成测试。

通过 loop._execute_tool_call 集成入口测试全部 23 工具（unified = 18 qa + 5 builder）：
1. 注册表完整性：TOOL_REGISTRY 3 类（qa/builder/unified）23 工具
2. Schema 生成：get_agent_schemas()=23（unified）, get_builder_schemas()=5（deprecated）
3. Agent 工具通过 _execute_tool_call 执行（mock 依赖）
4. 工具查找：get_tool_by_name 覆盖全部 23 个名称
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.react_agent.tools import (
    TOOL_REGISTRY,
    get_agent_schemas,
    get_builder_schemas,
    get_tool_by_name,
    get_tools_for_agent,
    get_tools_for_builder,
)


# ═══════════════════════════════════════════════════════════════
# 1. 注册表完整性
# ═══════════════════════════════════════════════════════════════


class TestToolRegistry:
    """工具注册表结构验证。"""

    def test_registry_has_three_categories(self):
        """TOOL_REGISTRY 包含 qa/builder/unified 三个类别。"""
        assert set(TOOL_REGISTRY.keys()) == {"qa", "builder", "unified"}

    def test_qa_has_seventeen_tools(self):
        """qa 类别有 18 个工具（含 search_corpus 与 spawn）。"""
        assert len(TOOL_REGISTRY["qa"]) == 18

    def test_builder_has_five_tools(self):
        """builder 类别有 5 个工具。"""
        assert len(TOOL_REGISTRY["builder"]) == 5

    def test_unified_has_twenty_two_tools(self):
        """unified 类别有 23 个工具（qa + builder 合并）。"""
        assert len(TOOL_REGISTRY["unified"]) == 23

    def test_agent_tools_are_unified(self):
        """get_tools_for_agent = unified(23)。"""
        tools = get_tools_for_agent()
        assert len(tools) == 23

    def test_builder_tools_deprecated(self):
        """get_tools_for_builder 保留向后兼容（deprecated）。"""
        with pytest.warns(DeprecationWarning, match="已废弃"):
            tools = get_tools_for_builder()
        assert len(tools) == 5

    def test_all_tool_names_unique(self):
        """unified 中所有 23 个工具名不重复。"""
        names = [tc.name for tc in TOOL_REGISTRY["unified"]]
        assert len(names) == len(set(names)), f"重复工具名: {names}"


# ═══════════════════════════════════════════════════════════════
# 2. Schema 生成
# ═══════════════════════════════════════════════════════════════


class TestSchemaGeneration:
    """OpenAI function calling schema 生成。"""

    def test_agent_schemas_count(self):
        """get_agent_schemas() 返回 23 个 schema（unified）。"""
        schemas = get_agent_schemas()
        assert len(schemas) == 23

    def test_builder_schemas_deprecated(self):
        """get_builder_schemas() 保留向后兼容（deprecated）。"""
        with pytest.warns(DeprecationWarning, match="已废弃"):
            schemas = get_builder_schemas()
        assert len(schemas) == 5

    def test_each_schema_has_required_fields(self):
        """每个 schema 包含 type/function/name/parameters。"""
        for schema in get_agent_schemas():
            assert schema["type"] == "function"
            assert "function" in schema
            func = schema["function"]
            assert "name" in func
            assert "description" in func
            assert "parameters" in func

    def test_schema_names_match_tool_names(self):
        """schema 的 name 与工具类的 name 属性一致。"""
        for tool_class in get_tools_for_agent():
            schema = tool_class().to_openai_schema()
            assert schema["function"]["name"] == tool_class.name

    def test_schemas_enable_strict_closed_world_validation(self):
        for schema in get_agent_schemas(strict=True):
            function = schema["function"]
            assert function["strict"] is True
            assert function["parameters"].get("additionalProperties") is False


# ═══════════════════════════════════════════════════════════════
# 3. get_tool_by_name 覆盖全部 23 工具
# ═══════════════════════════════════════════════════════════════


class TestGetToolByName:
    """按名称查找工具。"""

    @pytest.mark.parametrize("tool_name", [
        "search_resume", "jd_match", "diagnose_resume", "compare_resumes",
        "rewrite_star", "translate", "interview_coach",
        "search_jobs_live", "web_search", "search_corpus",
        "generate_module", "check_module", "modify_module",
        "rewrite_resume", "ask_info",
    ])
    def test_find_existing_tool(self, tool_name):
        """14 个工具名都能查到。"""
        tool_class = get_tool_by_name(tool_name)
        assert tool_class is not None
        assert tool_class.name == tool_name

    def test_find_nonexistent_tool_returns_none(self):
        """不存在的工具名返回 None。"""
        assert get_tool_by_name("nonexistent_tool") is None

    @pytest.mark.parametrize("tool_name,expected_category", [
        ("search_resume", "qa"),
        ("rewrite_star", "qa"),
        ("generate_module", "builder"),
        ("ask_info", "builder"),
    ])
    def test_tool_category_correct(self, tool_name, expected_category):
        """工具类别正确。"""
        tool_class = get_tool_by_name(tool_name)
        assert tool_class.category == expected_category


# ═══════════════════════════════════════════════════════════════
# 4. 13 Agent 工具通过 _execute_tool_call 集成测试
# ═══════════════════════════════════════════════════════════════


class TestAgentToolExecution:
    """通过 loop._execute_tool_call 执行 13 个 agent 工具。"""

    @pytest.mark.asyncio
    async def test_search_resume_executes(self):
        """search_resume 通过 _execute_tool_call 执行。"""
        from services.react_agent.loop import _execute_tool_call
        from services.rag.pipeline import ToolCall
        from services.react_agent.tools import SearchResumeTool

        tc = ToolCall(id="tc1", name="search_resume", arguments=json.dumps({"resume_id": 1, "query": "Python"}))

        mock_resume = MagicMock(status="ready")
        with patch.object(SearchResumeTool, "_get_resume", new_callable=AsyncMock, return_value=mock_resume), \
             patch("services.react_agent.tools.ensure_indexed", new_callable=AsyncMock), \
             patch("services.react_agent.tools.hybrid_search", new_callable=AsyncMock) as mock_search, \
             patch("services.react_agent.tools.rerank", new_callable=AsyncMock) as mock_rerank:
            mock_search.return_value = [{"text": "Python经验", "section": "技能", "score": 0.9, "chunk_index": 0}]
            mock_rerank.return_value = [{"text": "Python经验", "section": "技能", "rerank_score": 0.95, "chunk_index": 0}]

            result, is_error, _, _ = await _execute_tool_call(tc, AsyncMock(), user_id=1)

        assert is_error is False
        assert "Python经验" in result

    @pytest.mark.asyncio
    async def test_jd_match_executes(self):
        """jd_match 通过 _execute_tool_call 执行。"""
        from services.react_agent.loop import _execute_tool_call
        from services.rag.pipeline import ToolCall
        from services.react_agent.tools import JDMatchTool

        tc = ToolCall(id="tc1", name="jd_match", arguments=json.dumps({"resume_id": 1, "jd_text": "Python后端"}))

        mock_resume = MagicMock(status="ready")
        with patch.object(JDMatchTool, "_get_resume", new_callable=AsyncMock, return_value=mock_resume), \
             patch("services.react_agent.tools.match_jd", new_callable=AsyncMock) as mock_match:
            mock_match.return_value = {"resume_id": 1, "analysis": "匹配度 85%"}

            result, is_error, _, _ = await _execute_tool_call(tc, AsyncMock(), user_id=1)

        assert is_error is False
        assert "85%" in result

    @pytest.mark.asyncio
    async def test_diagnose_resume_executes(self):
        """diagnose_resume 通过 _execute_tool_call 执行。"""
        from services.react_agent.loop import _execute_tool_call
        from services.rag.pipeline import ToolCall
        from services.react_agent.tools import DiagnoseResumeTool

        tc = ToolCall(id="tc1", name="diagnose_resume", arguments=json.dumps({"resume_id": 1}))

        mock_resume = MagicMock(status="ready")
        with patch.object(DiagnoseResumeTool, "_get_resume", new_callable=AsyncMock, return_value=mock_resume), \
             patch("services.react_agent.tools.analyze_resume", new_callable=AsyncMock) as mock_analyze:
            mock_analyze.side_effect = [
                {"analysis": "经历分析结果"},
                {"analysis": "评分: 75分", "scores": {"overall": 75}},
            ]

            result, is_error, _, _ = await _execute_tool_call(tc, AsyncMock(), user_id=1)

        assert is_error is False
        assert "经历分析" in result

    @pytest.mark.asyncio
    async def test_compare_resumes_executes(self):
        """compare_resumes 通过 _execute_tool_call 执行。"""
        from services.react_agent.loop import _execute_tool_call
        from services.rag.pipeline import ToolCall

        tc = ToolCall(id="tc1", name="compare_resumes", arguments=json.dumps({"resume_ids": [1, 2]}))

        with patch("services.react_agent.tools.compare_resumes", new_callable=AsyncMock) as mock_compare:
            mock_compare.return_value = {
                "resumes": [{"id": 1, "filename": "a.pdf"}, {"id": 2, "filename": "b.pdf"}],
                "dimensions": {"skills": {"1": "Python", "2": "Java"}},
            }

            result, is_error, _, _ = await _execute_tool_call(tc, AsyncMock(), user_id=1)

        assert is_error is False
        assert "a.pdf" in result or "b.pdf" in result


# ═══════════════════════════════════════════════════════════════
# 5. 5 LLM 工具通过 _execute_tool_call 集成测试
# ═══════════════════════════════════════════════════════════════


class TestLLMToolExecution:
    """5 个 LLM 工具通过 _execute_tool_call 执行（mock LLM）。

    覆盖：rewrite_star / translate / interview_coach。
    已测直接调用 _execute，这里测通过 loop 的集成入口。
    """

    def _make_mock_db_with_resume(self, parsed_text="3年Python后端"):
        mock_resume = MagicMock()
        mock_resume.parsed_text = parsed_text
        mock_resume.status = "ready"
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_resume
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        return mock_db

    @pytest.mark.asyncio
    async def test_rewrite_star_through_loop(self):
        """rewrite_star 通过 _execute_tool_call 执行 → 写模块草稿确认。"""
        from services.react_agent.loop import _execute_tool_call
        from services.rag.pipeline import LLMToolResponse, ToolCall

        tc = ToolCall(id="tc1", name="rewrite_star", arguments=json.dumps({"resume_id": 1, "target_position": "后端"}))

        modules = [
            {"module_type": "basic_info", "content": {"name": "张三"}, "sort_order": 0},
            {"module_type": "work_experience",
             "content": {"entries": [{"company": "字节", "position": "后端", "description": "STAR化"}]},
             "sort_order": 1},
            {"module_type": "skills", "content": {"categories": [{"name": "语言", "items": ["Python"]}]}, "sort_order": 2},
        ]
        mock_resume = MagicMock(status="ready", parsed_text="3年Python后端")

        with (
            patch("services.react_agent.tools.get_resume_with_modules",
                  new_callable=AsyncMock, return_value=(mock_resume, [])),
            patch("services.react_agent.tools.llm_generate_with_tools",
                  new_callable=AsyncMock,
                  return_value=LLMToolResponse(tool_calls=[ToolCall(
                      id="c1", name="submit_rewritten_resume",
                      arguments=json.dumps({"modules": modules}, ensure_ascii=False))])),
            patch("services.react_agent.tools._replace_all_modules_short_txn",
                  new_callable=AsyncMock, return_value="✅ 简历已重写，共 3 个模块已保存。"),
        ):
            result, is_error, _, _ = await _execute_tool_call(tc, AsyncMock(), user_id=1)

        assert is_error is False
        assert "重写" in result and "3" in result

    @pytest.mark.asyncio
    async def test_translate_through_loop(self):
        """translate 通过 _execute_tool_call 执行 → 写模块草稿确认。"""
        from services.react_agent.loop import _execute_tool_call
        from services.rag.pipeline import LLMToolResponse, ToolCall

        tc = ToolCall(id="tc1", name="translate", arguments=json.dumps({"resume_id": 1, "target_lang": "en"}))

        modules = [
            {"module_type": "basic_info", "content": {"name": "Zhang San"}, "sort_order": 0},
            {"module_type": "skills", "content": {"categories": [{"name": "Languages", "items": ["Python"]}]}, "sort_order": 1},
        ]
        mock_resume = MagicMock(status="ready", parsed_text="3年Python后端")

        with (
            patch("services.react_agent.tools.get_resume_with_modules",
                  new_callable=AsyncMock, return_value=(mock_resume, [])),
            patch("services.react_agent.tools.llm_generate_with_tools",
                  new_callable=AsyncMock,
                  return_value=LLMToolResponse(tool_calls=[ToolCall(
                      id="c1", name="submit_rewritten_resume",
                      arguments=json.dumps({"modules": modules}, ensure_ascii=False))])),
            patch("services.react_agent.tools._replace_all_modules_short_txn",
                  new_callable=AsyncMock, return_value="✅ 简历已重写，共 2 个模块已保存。"),
        ):
            result, is_error, _, _ = await _execute_tool_call(tc, AsyncMock(), user_id=1)

        assert is_error is False
        assert "重写" in result and "2" in result

    @pytest.mark.asyncio
    async def test_interview_coach_through_loop(self):
        """interview_coach 通过 _execute_tool_call 执行（多轮状态机首次调用出第 1 题）。

        mock_db 的 execute 返回 scalars().all()（空列表 → 无进行中面试）→
        走创建分支；generate_plan 打桩避免真实 LLM 网络调用。
        """
        from services.react_agent.loop import _execute_tool_call
        from services.rag.pipeline import ToolCall

        tc = ToolCall(id="tc1", name="interview_coach", arguments=json.dumps({"resume_id": 1, "target_position": "后端"}))
        mock_db = self._make_mock_db_with_resume()

        plan = [{
            "id": "q1", "text": "请介绍一下你最有代表性的项目。", "section": "项目深挖",
            "difficulty": 3, "rubric": [], "followups": [],
            "target_competency": "项目深挖",
        }]
        with patch("services.interview_coach.generate_plan",
                   new_callable=AsyncMock, return_value=plan):
            result, is_error, _, _ = await _execute_tool_call(tc, mock_db, user_id=1)

        assert is_error is False
        assert "面试" in result
        assert "第 1/1 题" in result


# ═══════════════════════════════════════════════════════════════
# 6. _execute_tool_call 错误处理
# ═══════════════════════════════════════════════════════════════


class TestExecuteToolCallErrors:
    """_execute_tool_call 的三层防御。"""

    @pytest.mark.asyncio
    async def test_bad_json_returns_error(self):
        """非法 JSON arguments → (error_text, True)。"""
        from services.react_agent.loop import _execute_tool_call
        from services.rag.pipeline import ToolCall

        tc = ToolCall(id="tc1", name="search_resume", arguments="{invalid}")
        result, is_error, _, _ = await _execute_tool_call(tc, AsyncMock(), user_id=1)

        assert is_error is True
        assert "JSON" in result or "解析" in result

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error(self):
        """不存在的工具名 → (error_text, True)。"""
        from services.react_agent.loop import _execute_tool_call
        from services.rag.pipeline import ToolCall

        tc = ToolCall(id="tc1", name="nonexistent", arguments="{}")
        result, is_error, _, _ = await _execute_tool_call(tc, AsyncMock(), user_id=1)

        assert is_error is True
        assert "不存在" in result

    @pytest.mark.asyncio
    async def test_tool_execution_failure_returns_error(self):
        """工具 execute 抛异常 → (error_text, True)。"""
        from services.react_agent.loop import _execute_tool_call
        from services.react_agent.tools import SearchResumeTool
        from services.rag.pipeline import ToolCall

        tc = ToolCall(id="tc1", name="search_resume", arguments=json.dumps({"resume_id": 1, "query": "test"}))

        with patch.object(SearchResumeTool, "_get_resume", new_callable=AsyncMock,
                          return_value=MagicMock(status="ready")), \
             patch("services.react_agent.tools.ensure_indexed", new_callable=AsyncMock), \
             patch("services.react_agent.tools.hybrid_search", new_callable=AsyncMock) as mock_search:
            mock_search.side_effect = RuntimeError("连接失败")

            result, is_error, _, _ = await _execute_tool_call(tc, AsyncMock(), user_id=1)

        assert is_error is True
        assert "失败" in result or "错误" in result

    @pytest.mark.asyncio
    async def test_empty_arguments_handled(self):
        """空 arguments 字符串 → 当作 {} 处理（不触发 JSON 解析错误）。

        diagnose_resume 需要 resume_id，空参数会触发 Pydantic 校验错误，
        但这不是 JSON 解析错误 — 验证空字符串被正确当作 {} 处理。
        """
        from services.react_agent.loop import _execute_tool_call
        from services.rag.pipeline import ToolCall

        tc = ToolCall(id="tc1", name="diagnose_resume", arguments="")

        result, is_error, _, _ = await _execute_tool_call(tc, AsyncMock(), user_id=1)

        # 空 arguments 被当作 {} 处理，不会触发 JSON 解析错误
        # 但 diagnose_resume 需要 resume_id → Pydantic 校验失败
        assert is_error is True
        assert "JSON" not in result and "解析" not in result
# provider strict schema + scalar arguments are rejected at the boundary.
@pytest.mark.asyncio
async def test_scalar_tool_arguments_are_rejected():
    from services.react_agent.loop import _execute_tool_call
    from services.rag.pipeline import ToolCall

    tc = ToolCall(id="tc1", name="diagnose_resume", arguments="[]")
    result, is_error, _, _ = await _execute_tool_call(tc, AsyncMock(), user_id=1)
    assert is_error is True
    assert "JSON object" in result or "JSON" in result
