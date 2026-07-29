"""WebSocket 端点。

提供实时消息推送通道，用于：
- 简历后台分析完成/失败通知
- 其他实时状态更新
"""

import json
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt

from core.config import settings
from core.websocket_manager import ws_manager
from core.security import decode_token

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ws", tags=["websocket"])

http_bearer = HTTPBearer(auto_error=False)


@router.websocket("/")
async def websocket_endpoint(
    websocket: WebSocket,
    token: str | None = None,
    credentials: HTTPAuthorizationCredentials = Depends(http_bearer),
):
    """WebSocket 连接端点。

    客户端连接时需携带 token，支持两种方式：
    1. Query 参数: ws://host/api/v1/ws?token=eyJ...
    2. Header: Authorization: Bearer eyJ...
    """
    # 获取 token
    bearer_token = None
    if credentials is not None:
        bearer_token = credentials.credentials
    elif token:
        bearer_token = token

    if not bearer_token:
        await websocket.close(code=4001, reason="Missing token")
        return

    # 验证 token
    try:
        payload = decode_token(bearer_token)
        user_id = payload.get("sub") or payload.get("user_id")
        if user_id is None:
            await websocket.close(code=4001, reason="Invalid token")
            return
        user_id = int(user_id)
    except Exception as e:
        logger.warning("WebSocket 认证失败: %s", e)
        await websocket.close(code=4001, reason="Invalid token")
        return

    # 建立连接
    await ws_manager.connect(user_id, websocket)

    # 发送连接确认
    await websocket.send_text(json.dumps({
        "type": "connected",
        "message": "WebSocket 连接成功",
        "user_id": user_id,
    }))

    # 保持连接直到断开
    try:
        while True:
            # 客户端可以发送消息（目前仅用于心跳）
            data = await websocket.receive_text()
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
