"""MCP 鉴权（T13）：scope 资产归属校验。

所有带 scope 的 MCP 工具（search_index / answer_from_index / get_asset 等）必须先过
``assert_user_owns_assets``：对 scope 内每个 (asset_type, asset_id) 调
``resolve_asset_user_id`` 校验归属，越权/不存在统一抛 HTTPException 403
（不区分 403/404，避免泄露资产存在性）。

scope 归一化在此统一处理：MCP 工具把 scope 以 JSON 字符串传入，
这里同时兼容 dict / 字符串，并把 asset_id 强转 int。
"""

import json
import logging
from typing import Any

from fastapi import HTTPException

from core.database import AsyncSessionLocal
from services.rag.asset_source import resolve_asset_user_id

logger = logging.getLogger(__name__)

_ACCESS_DENIED = "access denied: asset does not belong to current user"


def normalize_scope(scope: Any) -> dict[str, list[int]]:
    """把 scope（dict 或 JSON 字符串）归一化为 {asset_type: [int, ...]}。

    非法输入抛 HTTPException 400；None / 空 dict 归一化为 {}。
    """
    if scope is None:
        return {}
    if isinstance(scope, str):
        scope = scope.strip()
        if not scope:
            return {}
        try:
            scope = json.loads(scope)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid scope: not valid JSON")

    if not isinstance(scope, dict):
        raise HTTPException(status_code=400, detail="Invalid scope: expected object")

    normalized: dict[str, list[int]] = {}
    for asset_type, ids in scope.items():
        if isinstance(ids, (int, str)) and not isinstance(ids, bool):
            ids = [ids]
        if not isinstance(ids, (list, tuple, set)):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid scope for '{asset_type}': expected list of asset ids",
            )
        int_ids: list[int] = []
        for i in ids:
            try:
                int_ids.append(int(i))
            except (ValueError, TypeError):
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid asset id in scope for '{asset_type}': {i!r}",
                )
        if int_ids:
            normalized[str(asset_type)] = int_ids
    return normalized


async def assert_user_owns_assets(user_id: int, scope: Any) -> dict[str, list[int]]:
    """校验 scope 内每个资产都归属当前用户，越权抛 HTTPException 403。

    返回归一化后的 scope（asset_id 已转 int），供检索 / 直读复用。
    空 scope 直接放行（检索层集合是 per-user 的，无跨用户泄露风险）。
    """
    normalized = normalize_scope(scope)
    if not normalized:
        return normalized

    async with AsyncSessionLocal() as db:
        for asset_type, asset_ids in normalized.items():
            for asset_id in asset_ids:
                owner = await resolve_asset_user_id(db, asset_type, asset_id)
                if owner is None or owner != user_id:
                    logger.warning(
                        "MCP scope authz denied: user=%d asset=%s/%d owner=%s",
                        user_id, asset_type, asset_id, owner,
                    )
                    raise HTTPException(
                        status_code=403,
                        detail=f"{_ACCESS_DENIED}: {asset_type}/{asset_id}",
                    )
    return normalized
