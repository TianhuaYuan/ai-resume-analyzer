"""Task: 简历分析结果 Redis 缓存服务测试。"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestAnalysisCacheGetSet:
    """缓存读写基本操作。"""

    @pytest.mark.asyncio
    async def test_get_analysis_cache_hit(self):
        """缓存命中时返回解析后的 dict。"""
        from services.resume_analysis_cache import get_analysis_cache

        mock_redis = MagicMock()
        mock_redis.get = AsyncMock(
            return_value=json.dumps(
                {"analysis_type": "skills", "analysis": "Python, FastAPI"},
                ensure_ascii=False,
            )
        )

        with patch(
            "services.resume_analysis_cache.get_redis", AsyncMock(return_value=mock_redis)
        ):
            result = await get_analysis_cache(resume_id=1, analysis_type="skills")

            assert result is not None
            assert result["analysis_type"] == "skills"
            assert "Python" in result["analysis"]
            mock_redis.get.assert_called_once_with("resume_analysis:1:skills")

    @pytest.mark.asyncio
    async def test_get_analysis_cache_miss(self):
        """缓存未命中时返回 None。"""
        from services.resume_analysis_cache import get_analysis_cache

        mock_redis = MagicMock()
        mock_redis.get = AsyncMock(return_value=None)

        with patch(
            "services.resume_analysis_cache.get_redis", AsyncMock(return_value=mock_redis)
        ):
            result = await get_analysis_cache(resume_id=1, analysis_type="summary")

            assert result is None

    @pytest.mark.asyncio
    async def test_get_analysis_cache_redis_unavailable(self):
        """Redis 不可用时返回 None（降级）。"""
        from services.resume_analysis_cache import get_analysis_cache

        with patch(
            "services.resume_analysis_cache.get_redis", AsyncMock(return_value=None)
        ):
            result = await get_analysis_cache(resume_id=1, analysis_type="skills")
            assert result is None

    @pytest.mark.asyncio
    async def test_get_analysis_cache_invalid_json(self):
        """缓存内容损坏（非 JSON）时返回 None。"""
        from services.resume_analysis_cache import get_analysis_cache

        mock_redis = MagicMock()
        mock_redis.get = AsyncMock(return_value="not-valid-json{{{")

        with patch(
            "services.resume_analysis_cache.get_redis", AsyncMock(return_value=mock_redis)
        ):
            result = await get_analysis_cache(resume_id=1, analysis_type="skills")
            assert result is None

    @pytest.mark.asyncio
    async def test_set_analysis_cache_writes_json_with_ttl(self):
        """写入缓存时序列化 JSON 并设置 TTL。"""
        from services.resume_analysis_cache import set_analysis_cache

        mock_redis = MagicMock()
        mock_redis.setex = AsyncMock()

        with patch(
            "services.resume_analysis_cache.get_redis", AsyncMock(return_value=mock_redis)
        ):
            result = await set_analysis_cache(
                resume_id=1,
                analysis_type="skills",
                value={"analysis_type": "skills", "analysis": "Python"},
                ttl_seconds=3600,
            )

            assert result is True
            mock_redis.setex.assert_called_once()
            args = mock_redis.setex.call_args[0]
            assert args[0] == "resume_analysis:1:skills"
            assert args[1] == 3600
            stored = json.loads(args[2])
            assert stored["analysis"] == "Python"

    @pytest.mark.asyncio
    async def test_set_analysis_cache_redis_unavailable(self):
        """Redis 不可用时写入返回 False。"""
        from services.resume_analysis_cache import set_analysis_cache

        with patch(
            "services.resume_analysis_cache.get_redis", AsyncMock(return_value=None)
        ):
            result = await set_analysis_cache(
                resume_id=1,
                analysis_type="skills",
                value={"analysis": "Python"},
            )
            assert result is False


class TestAnalysisCacheInvalidate:
    """缓存失效。"""

    @pytest.mark.asyncio
    async def test_invalidate_resume_cache_deletes_all_analysis_types(self):
        """失效某简历缓存时删除全部 4 种分析类型。"""
        from services.resume_analysis_cache import invalidate_resume_cache

        mock_redis = MagicMock()
        mock_redis.delete = AsyncMock(return_value=4)

        with patch(
            "services.resume_analysis_cache.get_redis", AsyncMock(return_value=mock_redis)
        ):
            result = await invalidate_resume_cache(resume_id=5)

            assert result is True
            # 应删除 4 个 key（summary/skills/experience/score）
            mock_redis.delete.assert_called_once()
            deleted_keys = mock_redis.delete.call_args[0]
            assert len(deleted_keys) == 4
            assert all("resume_analysis:5:" in k for k in deleted_keys)
            assert any(":summary" in k for k in deleted_keys)
            assert any(":skills" in k for k in deleted_keys)
            assert any(":experience" in k for k in deleted_keys)
            assert any(":score" in k for k in deleted_keys)

    @pytest.mark.asyncio
    async def test_invalidate_resume_cache_redis_unavailable(self):
        """Redis 不可用时返回 False。"""
        from services.resume_analysis_cache import invalidate_resume_cache

        with patch(
            "services.resume_analysis_cache.get_redis", AsyncMock(return_value=None)
        ):
            result = await invalidate_resume_cache(resume_id=1)
            assert result is False


class TestGetFullAnalysisCache:
    """批量获取一份简历的完整分析结果。"""

    @pytest.mark.asyncio
    async def test_get_full_cache_all_hit(self):
        """4 种类型都缓存时返回完整 dict。"""
        from services.resume_analysis_cache import get_full_analysis_cache

        cached = {
            "summary": {"analysis_type": "summary", "analysis": "s1"},
            "skills": {"analysis_type": "skills", "analysis": "k1"},
            "experience": {"analysis_type": "experience", "analysis": "e1"},
            "score": {
                "analysis_type": "score",
                "analysis": "评分文本",
                "scores": {"overall": 80, "ats_match": 70, "keyword_coverage": 75, "skill_density": 85},
            },
        }

        mock_redis = MagicMock()

        # mget 返回按 keys 顺序的列表：summary, skills, experience, score
        async def _fake_mget(*keys):
            ordered = []
            for key in keys:
                if key.endswith(":summary"):
                    ordered.append(json.dumps(cached["summary"], ensure_ascii=False))
                elif key.endswith(":skills"):
                    ordered.append(json.dumps(cached["skills"], ensure_ascii=False))
                elif key.endswith(":experience"):
                    ordered.append(json.dumps(cached["experience"], ensure_ascii=False))
                elif key.endswith(":score"):
                    ordered.append(json.dumps(cached["score"], ensure_ascii=False))
                else:
                    ordered.append(None)
            return ordered

        mock_redis.mget = AsyncMock(side_effect=_fake_mget)

        with patch(
            "services.resume_analysis_cache.get_redis", AsyncMock(return_value=mock_redis)
        ):
            result = await get_full_analysis_cache(resume_id=1)

            assert result is not None
            assert len(result) == 4
            assert "summary" in result and result["summary"]["analysis"] == "s1"
            assert "score" in result and result["score"]["scores"]["overall"] == 80

    @pytest.mark.asyncio
    async def test_get_full_cache_partial_miss_returns_none(self):
        """任一分析类型未命中时返回 None（对比/分析需要完整 4 种）。"""
        from services.resume_analysis_cache import get_full_analysis_cache

        mock_redis = MagicMock()
        # mget 返回按 summary, skills, experience, score 顺序，experience 为 None
        async def _fake_mget(*keys):
            ordered = []
            for key in keys:
                if key.endswith(":experience"):
                    ordered.append(None)
                else:
                    ordered.append(json.dumps({"analysis": "x"}, ensure_ascii=False))
            return ordered

        mock_redis.mget = AsyncMock(side_effect=_fake_mget)

        with patch(
            "services.resume_analysis_cache.get_redis", AsyncMock(return_value=mock_redis)
        ):
            result = await get_full_analysis_cache(resume_id=1)
            assert result is None

    @pytest.mark.asyncio
    async def test_cache_key_format(self):
        """缓存 key 格式: resume_analysis:{resume_id}:{analysis_type}。"""
        from services.resume_analysis_cache import _cache_key

        assert _cache_key(1, "skills") == "resume_analysis:1:skills"
        assert _cache_key(123, "summary") == "resume_analysis:123:summary"
