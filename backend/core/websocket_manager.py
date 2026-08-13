"""WebSocket 管理器。

管理 WebSocket 连接，支持按用户 ID 推送消息。
用于推送后台分析完成/失败通知。
"""

import json
import logging
from typing import Optional
from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)


class WebSocketManager:
    """WebSocket 连接管理器。"""

    def __init__(self):
        # {user_id: set[WebSocket]}
        self._connections: dict[int, set[WebSocket]] = {}

    def try_connect(self, user_id: int, websocket: WebSocket) -> bool:
        """尝试注册连接；超上限返回 False。

        Args:
            user_id: 用户 ID
            websocket: WebSocket 实例

        Returns:
            True 注册成功（并 accept）；False 连接数达上限（调用方自行 close）
        """
        from core.config import settings

        max_per_user = max(1, settings.WS_MAX_CONNECTIONS_PER_USER)
        if user_id in self._connections and len(self._connections[user_id]) >= max_per_user:
            return False
        if user_id not in self._connections:
            self._connections[user_id] = set()
        self._connections[user_id].add(websocket)
        logger.info(
            "WebSocket 连接建立: user_id=%d, 当前连接数=%d",
            user_id, len(self._connections[user_id]),
        )
        return True

    def disconnect(self, user_id: int, websocket: WebSocket) -> None:
        """断开 WebSocket 连接。

        Args:
            user_id: 用户 ID
            websocket: WebSocket 实例
        """
        if user_id in self._connections:
            self._connections[user_id].discard(websocket)
            if not self._connections[user_id]:
                del self._connections[user_id]
            logger.info(
                "WebSocket 连接断开: user_id=%d, 剩余连接数=%d",
                user_id,
                len(self._connections.get(user_id, set())),
            )

    async def send_to_user(self, user_id: int, message: dict) -> None:
        """向指定用户推送消息。

        Args:
            user_id: 用户 ID
            message: 消息体（字典，会被序列化为 JSON）
        """
        if user_id not in self._connections:
            return

        disconnected = []
        for websocket in self._connections[user_id]:
            try:
                await websocket.send_text(json.dumps(message, ensure_ascii=False))
            except WebSocketDisconnect:
                disconnected.append(websocket)
            except Exception as e:
                logger.warning(
                    "WebSocket 推送失败: user_id=%d, error=%s", user_id, e
                )
                disconnected.append(websocket)

        # 清理断开的连接
        for ws in disconnected:
            self.disconnect(user_id, ws)

    async def broadcast(self, message: dict) -> None:
        """向所有连接的用户广播消息。

        Args:
            message: 消息体
        """
        for user_id in list(self._connections.keys()):
            await self.send_to_user(user_id, message)

    def get_connection_count(self, user_id: Optional[int] = None) -> int:
        """获取连接数量。

        Args:
            user_id: 用户 ID，None 时返回总连接数

        Returns:
            连接数量
        """
        if user_id is None:
            return sum(len(conns) for conns in self._connections.values())
        return len(self._connections.get(user_id, set()))


# 全局单例
ws_manager = WebSocketManager()
