"""WebSocket 端点。

提供实时消息推送通道，用于：
- 简历后台分析完成/失败通知
- 分析进度实时推送
- 其他实时状态更新
"""

import asyncio
import json
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from core.config import settings
from core.websocket_manager import ws_manager
from core.security import decode_token, is_token_revoked

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ws", tags=["websocket"])


def _extract_token(websocket: WebSocket, query_token: str | None) -> str | None:
    """取 JWT：优先 header（避免 token 进访问日志），query 兼容旧客户端。

    - Authorization: Bearer <jwt>
    - X-Nanobot-Token: <jwt>
    - 回退 query ?token=<jwt>（旧客户端；生产建议升级到 header）
    """
    auth = websocket.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    header_token = websocket.headers.get("x-nanobot-token")
    if header_token:
        return header_token.strip()
    return query_token


@router.websocket("")
async def websocket_endpoint(
    websocket: WebSocket,
    token: str | None = None,
):
    """WebSocket 连接端点。

    认证 token 优先从 header 取（Authorization: Bearer / X-Nanobot-Token），
    避免经 query 参数进 nginx/uvicorn 访问日志（P2-8 安全）；query ?token=
    保留兼容旧客户端。
    """
    jwt = _extract_token(websocket, token)
    if not jwt:
        await websocket.close(code=4001, reason="Missing token")
        return

    # 验证 JWT
    try:
        payload = decode_token(jwt)
        user_id = payload.get("sub") or payload.get("user_id")
        if user_id is None:
            await websocket.close(code=4001, reason="Invalid token")
            return
        user_id = int(user_id)
        # P2-8：连接时校验 token 是否已撤销（撤销名单）
        jti = payload.get("jti")
        if jti and await is_token_revoked(jti):
            logger.warning("WebSocket 连接被拒：token 已撤销 user_id=%d", user_id)
            await websocket.close(code=4001, reason="Token revoked")
            return
    except Exception as e:
        logger.warning("WebSocket 认证失败: %s", e)
        await websocket.close(code=4001, reason="Invalid token")
        return

    # P2-8：每用户连接数上限（DoS 防护）——先 accept 再检查计数，
    # 超限时 close 且不注册。
    await websocket.accept()
    if not ws_manager.try_connect(user_id, websocket):
        logger.warning(
            "WebSocket 连接被拒：user_id=%d 连接数达上限 %d",
            user_id,
            settings.WS_MAX_CONNECTIONS_PER_USER,
        )
        await websocket.close(code=4009, reason="Too many connections")
        return

    # 发送连接确认
    await websocket.send_text(json.dumps({
        "type": "connected",
        "message": "WebSocket 连接成功",
        "user_id": user_id,
    }))

    # 保持连接直到断开（P2-8：asyncio.wait_for 做服务端心跳——
    # 客户端静默掉线（无 close 帧）时超时关闭，避免连接滞留）
    try:
        while True:
            try:
                data = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=settings.WS_IDLE_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                # 超时（无客户端消息）= 心跳超时，关闭连接清理滞留
                logger.info(
                    "WebSocket 心跳超时关闭 user_id=%d（%.0fs 无消息）",
                    user_id,
                    settings.WS_IDLE_TIMEOUT_SECONDS,
                )
                break
            try:
                msg = json.loads(data)
                if msg.get("type") == "ping":
                    await websocket.send_text(json.dumps({
                        "type": "pong",
                    }))
            except json.JSONDecodeError:
                pass  # 忽略非 JSON 消息
    except WebSocketDisconnect:
        logger.info("WebSocket 断开连接: user_id=%d", user_id)
    except Exception as e:
        logger.error("WebSocket 异常: user_id=%d, error=%s", user_id, e)
    finally:
        ws_manager.disconnect(user_id, websocket)
