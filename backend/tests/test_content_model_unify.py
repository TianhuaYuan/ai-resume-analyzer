"""根治回归：内容源统一（懒物化）+ content_hash 语义 + chunk_count 同步。

覆盖三缝隙修复：
1. 懒物化：上传简历 GET /builder 首次自动反解析模块（成功 / 失败降级 / 不重复物化）
2. content_hash：complete 后 = sha256(parsed_text)；draft 保存不改；complete 兜底保留原文本
3. chunk_count：ensure_indexed 懒重建后写回

依赖 conftest fixtures: client / auth_headers / registered_user / db_session
"""

import hashlib
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from models.resume import Resume
from schemas.resume_module import ModuleType, ResumeModuleCreate
from tests.conftest import AsyncSessionTest


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


async def _insert_upload_resume(db, user_id: int, parsed_text: str = "张三\nPython 工程师\n3 年经验") -> Resume:
    """DB 直插一份 source=upload 的已解析简历（无模块）。"""
    resume = Resume(
        user_id=user_id,
        filename="上传简历",
        file_path="/tmp/up.pdf",
        parsed_text=parsed_text,
        chunk_count=0,
        status="ready",
        source="upload",
    )
    db.add(resume)
    await db.commit()
    await db.refresh(resume)
    return resume


async def _fetch_resume(resume_id: int) -> Resume:
    async with AsyncSessionTest() as s:
        row = (await s.execute(select(Resume).where(Resume.id == resume_id))).scalar_one()
        return row


# ═══════════════════════════════════════════════════════════
# 1. 懒物化（缝隙 A）
# ═══════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_builder_materializes_upload_resume(
    client, auth_headers, registered_user, db_session
):
    """上传简历首次 GET /builder → 自动物化模块，source → builder，modules_materialized=true。"""
    resume = await _insert_upload_resume(db_session, registered_user["id"])

    parsed = [
        ResumeModuleCreate(module_type=ModuleType.BASIC_INFO, content={"name": "张三"}, sort_order=0),
        ResumeModuleCreate(
            module_type=ModuleType.SKILLS,
            content={"categories": [{"name": "编程语言", "items": ["Python"]}]},
            sort_order=1,
        ),
    ]
    with patch(
        "services.resume_parser.parse_text_to_modules", new_callable=AsyncMock
    ) as mock_parse:
        mock_parse.return_value = parsed
        resp = await client.get(
            f"/api/v1/resumes/{resume.id}/builder", headers=auth_headers
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["modules_materialized"] is True
    assert len(data["modules"]) == 2
    assert data["source"] == "builder"  # 已物化标记

    row = await _fetch_resume(resume.id)
    assert row.source == "builder"
    assert row.parsed_text == resume.parsed_text  # 物化不动解析文本


@pytest.mark.asyncio
async def test_get_builder_does_not_repeat_materialize(
    client, auth_headers, registered_user, db_session
):
    """已物化（source=builder）简历再次 GET /builder 不重复触发 LLM。"""
    resume = await _insert_upload_resume(db_session, registered_user["id"])

    parsed = [ResumeModuleCreate(module_type=ModuleType.BASIC_INFO, content={"name": "张三"}, sort_order=0)]
    with patch(
        "services.resume_parser.parse_text_to_modules", new_callable=AsyncMock
    ) as mock_parse:
        mock_parse.return_value = parsed
        await client.get(f"/api/v1/resumes/{resume.id}/builder", headers=auth_headers)

    # 第二次请求：source 已变 builder → 不再物化
    with patch(
        "services.resume_parser.parse_text_to_modules", new_callable=AsyncMock
    ) as mock_parse2:
        resp2 = await client.get(f"/api/v1/resumes/{resume.id}/builder", headers=auth_headers)

    assert resp2.status_code == 200
    assert len(resp2.json()["modules"]) == 1
    mock_parse2.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_builder_materialize_failure_degrades(
    client, auth_headers, registered_user, db_session
):
    """反解析失败 → 空模块 + modules_materialized=false，不抛 500，source 保持 upload。"""
    resume = await _insert_upload_resume(db_session, registered_user["id"])

    with patch(
        "services.resume_parser.parse_text_to_modules", new_callable=AsyncMock
    ) as mock_parse:
        mock_parse.side_effect = ValueError("LLM JSON 解析失败")
        resp = await client.get(
            f"/api/v1/resumes/{resume.id}/builder", headers=auth_headers
        )

    assert resp.status_code == 200  # 失败不阻断 builder 加载
    data = resp.json()
    assert data["modules_materialized"] is False
    assert data["modules"] == []
    assert data["source"] == "upload"


# ═══════════════════════════════════════════════════════════
# 2. content_hash 统一（缝隙 B）
# ═══════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_complete_content_hash_equals_sha256_parsed_text(
    client, auth_headers, registered_user, db_session
):
    """complete 后 content_hash == sha256(DB parsed_text)（统一语义）。"""
    resume = await _insert_upload_resume(db_session, registered_user["id"])

    with patch("services.resume_builder.ensure_indexed", new_callable=AsyncMock) as mock_idx, \
         patch("services.resume_builder.embedding_cache.clear_resume", new_callable=AsyncMock), \
         patch("services.react_agent.memory.build_l3_profile_background", new_callable=AsyncMock):
        mock_idx.return_value = True
        resp = await client.put(
            f"/api/v1/resumes/{resume.id}?mode=complete",
            json={"version": 1},  # 不带 modules → 走兜底
            headers=auth_headers,
        )

    assert resp.status_code == 200
    row = await _fetch_resume(resume.id)
    assert row.content_hash == _sha256(row.parsed_text)


@pytest.mark.asyncio
async def test_complete_without_modules_preserves_parsed_text(
    client, auth_headers, registered_user, db_session
):
    """上传简历 complete（请求不带 modules，绕过编辑器直调）→ 保留原解析文本，不丢内容。"""
    original = "张三\nPython 工程师\n3 年经验\n本科毕业\n熟练 FastAPI"
    resume = await _insert_upload_resume(db_session, registered_user["id"], parsed_text=original)

    with patch("services.resume_builder.ensure_indexed", new_callable=AsyncMock) as mock_idx, \
         patch("services.resume_builder.embedding_cache.clear_resume", new_callable=AsyncMock), \
         patch("services.react_agent.memory.build_l3_profile_background", new_callable=AsyncMock):
        mock_idx.return_value = True
        resp = await client.put(
            f"/api/v1/resumes/{resume.id}?mode=complete",
            json={"version": 1},
            headers=auth_headers,
        )

    assert resp.status_code == 200
    row = await _fetch_resume(resume.id)
    assert row.parsed_text == original  # 兜底保留原文本
    assert row.content_hash == _sha256(original)


@pytest.mark.asyncio
async def test_draft_save_does_not_change_content_hash(
    client, auth_headers, registered_user, db_session
):
    """草稿保存模块变化 → content_hash 不变（parsed_text 未变，不置脏）。"""
    resume = Resume(
        user_id=registered_user["id"],
        filename="草稿简历",
        file_path="",
        parsed_text="旧文本",
        chunk_count=0,
        status="draft",
        source="builder",
        content_hash="initial-hash",  # 模拟已完成过一次的内容哈希
    )
    db_session.add(resume)
    await db_session.commit()
    await db_session.refresh(resume)

    resp = await client.put(
        f"/api/v1/resumes/{resume.id}?mode=draft",
        json={
            "filename": "改名草稿",
            "modules": [{"module_type": "basic_info", "content": {"name": "李四"}, "sort_order": 0}],
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200

    row = await _fetch_resume(resume.id)
    assert row.content_hash == "initial-hash"  # draft 不改 content_hash


# ═══════════════════════════════════════════════════════════
# 3. chunk_count 同步（缝隙 C）
# ═══════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_ensure_indexed_writes_chunk_count(db_session, registered_user):
    """ensure_indexed 懒重建成功后写回 chunk_count。"""
    resume = await _insert_upload_resume(db_session, registered_user["id"])
    resume.content_hash = _sha256(resume.parsed_text)
    resume.indexed_hash = None  # 从未索引 → 脏
    await db_session.commit()

    fake_store = AsyncMock()
    fake_store.get.return_value = []  # 向量库无该资产 → _is_ready False → 重建

    from services.rag.ensure_indexed import ensure_indexed

    with patch("services.rag.ensure_indexed.acquire_index_lock", new_callable=AsyncMock, return_value="lock-1"), \
         patch("services.rag.ensure_indexed.release_index_lock", new_callable=AsyncMock), \
         patch("services.rag.ensure_indexed.index_asset", new_callable=AsyncMock, return_value=5), \
         patch("services.rag.ensure_indexed.get_vector_store", return_value=fake_store), \
         patch("services.rag.ensure_indexed.clear_bm25", new_callable=AsyncMock):
        ok = await ensure_indexed(
            db_session,
            user_id=registered_user["id"],
            asset_id=resume.id,
            asset_type="resume",
            collection="knowledge_test",
        )

    assert ok is True
    row = await _fetch_resume(resume.id)
    assert row.chunk_count == 5  # index_asset 返回值写回
    assert row.index_version == 1
    assert row.indexed_hash == resume.content_hash
