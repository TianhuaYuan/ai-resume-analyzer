"""T27: 简历预览服务 — content hash 缓存 + 零模块守卫。

职责：
- get_resume_preview: 获取简历 + 模块 → 计算内容 hash → 缓存命中则返回缓存 HTML，
  未命中则 render_resume 渲染后缓存
- 缓存 key = content hash（模块内容 + 样式 + 模板 ID 的 SHA256）
- 缓存 TTL = 5 分钟（300 秒），过期自动失效

设计依据：
- plan.md T27: GET /preview（content hash 缓存 TTL 5min + 零模块守卫）
- spec: preview 端点用于 BuilderPage iframe 实时预览，高频调用需缓存
- 风险表: 反解析/生成模块的 LLM JSON 不稳 → T27 pydantic 校验 + 回灌重试
"""

import hashlib
import json
import logging
import time
from collections import OrderedDict

from sqlalchemy.ext.asyncio import AsyncSession

from models.resume_module import ResumeModule
from schemas.resume_module import ResumeStyle
from services.resume_template import render_resume

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════
# 缓存配置
# ═══════════════════════════════════════════════════════════

_CACHE_TTL_SECONDS: int = 300  # 5 分钟
_MAX_CACHE_ENTRIES: int = 200  # 最多缓存 200 份预览（LRU 淘汰）

# LRU 缓存：key = content_hash, value = (html, timestamp)
_preview_cache: OrderedDict[str, tuple[str, float]] = OrderedDict()


def _compute_content_hash(
    modules: list[ResumeModule],
    style: ResumeStyle,
    filename: str,
) -> str:
    """计算简历内容的 hash 值。

    hash 输入：
    - 所有模块的 module_type + content + sort_order（按 sort_order 排序）
    - 样式（template_id, font_family, font_size, line_height, spacing, accent_color）
    - 文件名

    Returns:
        SHA256 hex 字符串
    """
    sorted_modules = sorted(modules, key=lambda m: (m.sort_order, m.id))
    modules_data = [
        {
            "module_type": m.module_type,
            "content": m.content,
            "sort_order": m.sort_order,
        }
        for m in sorted_modules
    ]
    hash_input = {
        "modules": modules_data,
        "style": style.model_dump(),
        "filename": filename,
    }
    # sort_keys=True 确保相同内容生成相同 hash
    json_str = json.dumps(hash_input, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(json_str.encode("utf-8")).hexdigest()


def _get_cached(html_hash: str) -> str | None:
    """从缓存获取 HTML，过期则返回 None。"""
    entry = _preview_cache.get(html_hash)
    if entry is None:
        return None

    html, timestamp = entry
    # 检查 TTL
    if time.time() - timestamp > _CACHE_TTL_SECONDS:
        # 过期，从缓存移除
        _preview_cache.pop(html_hash, None)
        return None

    # LRU: 标记为最近使用
    _preview_cache.move_to_end(html_hash)
    return html


def _set_cached(html_hash: str, html: str) -> None:
    """写入缓存，超过上限时 LRU 淘汰。"""
    _preview_cache[html_hash] = (html, time.time())
    _preview_cache.move_to_end(html_hash)

    # LRU 淘汰
    while len(_preview_cache) > _MAX_CACHE_ENTRIES:
        _preview_cache.popitem(last=False)


def clear_preview_cache() -> int:
    """清空预览缓存（测试 / 管理用）。返回清除的条目数。"""
    count = len(_preview_cache)
    _preview_cache.clear()
    return count


def get_cache_stats() -> dict:
    """返回缓存统计信息。"""
    now = time.time()
    active = sum(
        1 for _, (_, ts) in _preview_cache.items()
        if now - ts <= _CACHE_TTL_SECONDS
    )
    expired = len(_preview_cache) - active
    return {
        "total_entries": len(_preview_cache),
        "active_entries": active,
        "expired_entries": expired,
        "max_entries": _MAX_CACHE_ENTRIES,
        "ttl_seconds": _CACHE_TTL_SECONDS,
    }


# ═══════════════════════════════════════════════════════════
# 主预览入口
# ═══════════════════════════════════════════════════════════


async def get_resume_preview(
    db: AsyncSession,
    user_id: int,
    resume_id: int,
) -> tuple[str, bool]:
    """获取简历预览 HTML。

    流程：
    1. 获取简历 + 模块（校验归属）
    2. 零模块守卫
    3. 计算内容 hash
    4. 缓存命中 → 返回缓存 HTML（cache_hit=True）
    5. 缓存未命中 → render_resume 渲染 → 缓存 → 返回（cache_hit=False）

    Args:
        db: 数据库会话
        user_id: 用户 ID
        resume_id: 简历 ID

    Returns:
        (html_str, cache_hit)

    Raises:
        HTTPException 404: 简历不存在或非本人
    """
    from services.resume_builder import get_resume_with_modules

    resume, modules = await get_resume_with_modules(db, user_id, resume_id)

    # 零模块时不拦截 — 返回空模板预览（用户可看到模板框架）
    # 导出端点仍保留 _guard_has_modules 守卫

    # 解析 style（防御历史脏数据：style 可能是双重序列化的 JSON 字符串）
    style = ResumeStyle.from_db(resume.style)

    # 计算内容 hash
    content_hash = _compute_content_hash(modules, style, resume.filename)

    # 查缓存
    cached_html = _get_cached(content_hash)
    if cached_html is not None:
        logger.debug("Preview cache hit: resume=%d, hash=%s", resume_id, content_hash[:12])
        return cached_html, True

    # 缓存未命中，渲染 HTML
    html = render_resume(modules, style, resume.filename)

    # 写入缓存
    _set_cached(content_hash, html)

    logger.info(
        "Preview cache miss: resume=%d, hash=%s, html_size=%d chars",
        resume_id, content_hash[:12], len(html),
    )
    return html, False
