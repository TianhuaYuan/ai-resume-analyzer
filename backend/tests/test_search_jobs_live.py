"""M5: search_jobs_live 实时岗位搜索工具测试。

mock 引擎层（不真实联网），覆盖：
1. 主引擎成功 → 渲染编号文本 + sources 侧信道
2. 全部引擎空结果 → 友好降级提示
3. 引擎异常 → 跳过继续下一引擎；全部异常 → 降级提示
4. query 必填参数校验 → ToolRetryError
5. limit 上限截断（>10 → 10）
6. resume_id 归属校验 → ToolFailed
"""

import pytest
from unittest.mock import AsyncMock, patch

from services.react_agent.tools.base import ToolFailed, ToolRetryError
from services.react_agent.tools.search_jobs_live import SearchJobsLiveTool


class _FakeEngine:
    """可配置返回结果/异常的假引擎。"""

    def __init__(self, items=None, exc=None, name="fake"):
        self.items = items or []
        self.exc = exc
        self.name = name

    def search_sync(self, query, limit):
        if self.exc:
            raise self.exc
        return self.items


class _RecordingEngine:
    """记录收到的 limit 参数的假引擎。"""

    def __init__(self, items):
        self.calls: list[int] = []
        self.items = items
        self.name = "recording"  # 渲染时展示引擎名

    def search_sync(self, query, limit):
        self.calls.append(limit)
        return self.items


def _fake_items():
    # url 必须落在渠道白名单域名内（nowcoder 为默认招聘平台之一），
    # 否则被 _filter_by_site 结果层过滤掉，成功类测试会走降级提示。
    return [
        {
            "title": "深圳后端开发工程师",
            "url": "https://www.nowcoder.com/job/1",
            "snippet": "负责后端服务开发，要求 Python/Go",
            "source": "open-websearch/csdn",
        }
    ]


class TestSearchJobsLive:

    @pytest.mark.asyncio
    async def test_success_renders_results_with_sources(self):
        """主引擎成功 → 渲染编号文本 + sources 侧信道。"""
        tool = SearchJobsLiveTool()
        with patch.object(
            SearchJobsLiveTool, "_engines", new=[_FakeEngine(_fake_items())]
        ):
            result = await tool.execute(query="后端开发", city="深圳", job_type="social", limit=3)

        assert "实时岗位搜索结果" in result
        assert "深圳后端开发工程师" in result
        assert "负责后端服务开发" in result
        assert len(tool.sources) == 1
        assert tool.sources[0]["url"] == "https://www.nowcoder.com/job/1"

    @pytest.mark.asyncio
    async def test_all_engines_empty_degrades_friendly(self):
        """全部引擎空结果 → 友好降级提示。"""
        tool = SearchJobsLiveTool()
        with patch.object(
            SearchJobsLiveTool, "_engines", new=[_FakeEngine([]), _FakeEngine([])]
        ):
            result = await tool.execute(query="不存在岗位", city="深圳")

        assert "没有找到" in result
        assert "更换关键词" in result
        assert tool.sources == []

    @pytest.mark.asyncio
    async def test_engine_exception_falls_through_to_next(self):
        """第一个引擎异常 → 跳过继续第二个。"""
        tool = SearchJobsLiveTool()
        engines = [
            _FakeEngine(exc=RuntimeError("网络失败")),
            _FakeEngine(_fake_items()),
        ]
        with patch.object(SearchJobsLiveTool, "_engines", new=engines):
            result = await tool.execute(query="后端")

        assert "深圳后端开发工程师" in result

    @pytest.mark.asyncio
    async def test_all_engines_exception_degrades(self):
        """全部引擎异常 → 降级提示。"""
        tool = SearchJobsLiveTool()
        engines = [_FakeEngine(exc=RuntimeError("1")), _FakeEngine(exc=RuntimeError("2"))]
        with patch.object(SearchJobsLiveTool, "_engines", new=engines):
            result = await tool.execute(query="后端")

        assert "没有找到" in result

    @pytest.mark.asyncio
    async def test_missing_query_raises_tool_retry(self):
        """query 必填 → 参数校验失败抛 ToolRetryError（LLM 可修复重试）。"""
        tool = SearchJobsLiveTool()
        with pytest.raises(ToolRetryError):
            await tool.execute()

    @pytest.mark.asyncio
    async def test_limit_capped_at_20(self):
        """limit>20 被截断到 20 传给引擎（博查 count 最多 50，岗位搜索取 20）。"""
        rec = _RecordingEngine(_fake_items())
        tool = SearchJobsLiveTool()
        with patch.object(SearchJobsLiveTool, "_engines", new=[rec]):
            await tool.execute(query="后端", limit=30)

        assert rec.calls[0] == 20

    @pytest.mark.asyncio
    async def test_resume_id_ownership_checked(self):
        """resume_id 不属于当前用户 → ToolFailed（不累计坏调用）。"""
        tool = SearchJobsLiveTool(db=AsyncMock(), user_id=1)
        with patch.object(
            SearchJobsLiveTool, "_get_resume", new_callable=AsyncMock, return_value=None
        ):
            with pytest.raises(ToolFailed, match="不存在或无权访问"):
                await tool.execute(query="后端", resume_id=999)

    @pytest.mark.asyncio
    async def test_resume_id_owned_passes(self):
        """resume_id 归属通过 → 正常执行（不触发归属错误）。"""
        tool = SearchJobsLiveTool(db=AsyncMock(), user_id=1)
        with patch.object(
            SearchJobsLiveTool, "_get_resume", new_callable=AsyncMock, return_value=object()
        ), patch.object(SearchJobsLiveTool, "_engines", new=[_FakeEngine(_fake_items())]):
            result = await tool.execute(query="后端", resume_id=1)

        assert "深圳后端开发工程师" in result

    def test_job_type_label_mapping(self):
        """job_type → 搜索词映射正确（campus/social/intern）。"""
        tool = SearchJobsLiveTool()
        assert "校园招聘" in tool._build_query("前端", None, None, "campus")
        assert "社会招聘" in tool._build_query("前端", None, None, "social")
        assert "实习" in tool._build_query("前端", None, None, "intern")

    def test_build_query_with_city(self):
        """query 构造包含岗位 + 城市 + 类型。"""
        tool = SearchJobsLiveTool()
        q = tool._build_query("后端开发", None, "深圳", "social")
        assert "后端开发" in q
        assert "深圳" in q
        assert "社会招聘" in q

    # ── 渠道白名单过滤（M2 增强：所有引擎含兜底统一限制） ──

    def test_filter_by_site_keeps_whitelist(self):
        """只保留主域名/子域名命中白名单的结果，丢弃新闻/就业中心。"""
        from services.react_agent.tools.search_jobs_live import _filter_by_site

        items = [
            {"url": "https://www.zhipin.com/job/1", "title": "zhipin"},
            {"url": "https://nowcoder.com/job/2", "title": "nowcoder"},
            {"url": "https://job.lagou.com/3", "title": "lagou sub"},
            {"url": "https://news.qq.com/x", "title": "qq news"},
            {"url": "https://nankai.edu.cn/job", "title": "univ"},
            {"url": "", "title": "no url"},
        ]
        kept = _filter_by_site(items, "zhipin.com|nowcoder.com|lagou.com")
        assert [i["title"] for i in kept] == ["zhipin", "nowcoder", "lagou sub"]

    def test_filter_by_site_empty_include_keeps_all(self):
        from services.react_agent.tools.search_jobs_live import _filter_by_site

        items = [
            {"url": "https://qq.com/x", "title": "a"},
            {"url": "", "title": "b"},
        ]
        assert _filter_by_site(items, "") == items

    def test_filter_by_site_case_insensitive_host(self):
        from services.react_agent.tools.search_jobs_live import _filter_by_site

        items = [{"url": "HTTPS://WWW.ZHIPIN.COM/JOB/1", "title": "upper"}]
        assert len(_filter_by_site(items, "zhipin.com")) == 1

    @pytest.mark.asyncio
    async def test_execute_filters_non_whitelist(self):
        """混合结果：只渲染招聘平台域名，丢弃新闻/就业中心。"""
        tool = SearchJobsLiveTool()
        items = [
            {"title": "牛客网 字节AI岗", "url": "https://www.nowcoder.com/job/1", "snippet": "", "source": "f"},
            {"title": "腾讯新闻 AI资讯", "url": "https://news.qq.com/x", "snippet": "", "source": "f"},
            {"title": "boss直聘 大模型开发", "url": "https://www.zhipin.com/job/2", "snippet": "", "source": "f"},
        ]
        with patch.object(SearchJobsLiveTool, "_engines", new=[_FakeEngine(items)]):
            result = await tool.execute(query="AI 大模型", job_type="social")

        assert "牛客网 字节AI岗" in result
        assert "boss直聘 大模型开发" in result
        assert "腾讯新闻" not in result

    @pytest.mark.asyncio
    async def test_execute_all_filtered_returns_fallback(self):
        """全部结果不在渠道白名单 → 过滤后为空 → 友好降级提示。"""
        tool = SearchJobsLiveTool()
        items = [
            {"title": "新闻资讯", "url": "https://news.qq.com/x", "snippet": "", "source": "f"}
        ]
        with patch.object(SearchJobsLiveTool, "_engines", new=[_FakeEngine(items)]):
            result = await tool.execute(query="AI 大模型", job_type="social")

        assert "没有找到" in result
        assert tool.sources == []

    @pytest.mark.asyncio
    async def test_execute_tries_next_engine_after_filtered_out(self):
        """第一个引擎全被过滤 → 试下一引擎，命中白名单则渲染。"""
        tool = SearchJobsLiveTool()
        bad = _FakeEngine(
            [{"title": "非招聘渠道", "url": "https://news.qq.com/x", "snippet": "", "source": "f"}],
            name="bad",
        )
        good = _FakeEngine(
            [{"title": "拉勾 AI岗", "url": "https://www.lagou.com/job/9", "snippet": "", "source": "f"}],
            name="good",
        )
        with patch.object(SearchJobsLiveTool, "_engines", new=[bad, good]):
            result = await tool.execute(query="AI 大模型", job_type="social")

        assert "拉勾 AI岗" in result
        assert "非招聘渠道" not in result
