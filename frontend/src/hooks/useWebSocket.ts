import { useEffect, useRef, useCallback, useState } from "react";

/**
 * WebSocket 消息类型
 */
export interface WSMessage {
  type: string;
  status?: string;
  resume_id?: number;
  user_id?: number;
  timestamp?: string;
  data?: Record<string, unknown>;
  message?: string;
}

interface UseWebSocketOptions {
  /** WebSocket URL，如 ws://localhost:8000/api/v1/ws */
  url: string;
  /** 认证 token */
  token: string | null;
  /** 收到消息时的回调 */
  onMessage?: (msg: WSMessage) => void;
  /** 是否启用（登录后才连接） */
  enabled?: boolean;
  /** 重连间隔（毫秒），默认 3000 */
  reconnectInterval?: number;
  /** 最大重连次数，默认 5 */
  maxReconnectAttempts?: number;
}

interface UseWebSocketReturn {
  /** 当前连接状态 */
  connected: boolean;
  /** 手动发送消息 */
  send: (msg: WSMessage) => void;
  /** 手动重连 */
  reconnect: () => void;
}

/**
 * WebSocket 连接 Hook
 *
 * 特性：
 * - 自动重连（指数退避）
 * - 心跳保活（30秒 ping）
 * - 登录后才连接（enabled 控制）
 * - token 过期时自动断开
 *
 * @example
 * ```tsx
 * const { connected } = useWebSocket({
 *   url: "ws://localhost:8000/api/v1/ws",
 *   token: userToken,
 *   enabled: !!user,
 *   onMessage: (msg) => {
 *     if (msg.type === "analysis_complete") {
 *       toast.success("简历分析完成");
 *     }
 *   },
 * });
 * ```
 */
export function useWebSocket({
  url,
  token,
  onMessage,
  enabled = true,
  reconnectInterval = 3000,
  maxReconnectAttempts = 5,
}: UseWebSocketOptions): UseWebSocketReturn {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const heartbeatTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const onMessageRef = useRef(onMessage);
  const [connected, setConnected] = useState(false);

  // 保持 onMessage 引用最新
  useEffect(() => {
    onMessageRef.current = onMessage;
  }, [onMessage]);

  const clearTimers = useCallback(() => {
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
    if (heartbeatTimerRef.current) {
      clearInterval(heartbeatTimerRef.current);
      heartbeatTimerRef.current = null;
    }
  }, []);

  const startHeartbeat = useCallback(() => {
    heartbeatTimerRef.current = setInterval(() => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ type: "ping" }));
      }
    }, 30000);
  }, []);

  const connect = useCallback(() => {
    if (!enabled || !token) return;

    // 构建带 token 的 URL
    const wsUrl = `${url}?token=${encodeURIComponent(token)}`;

    try {
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        reconnectAttemptsRef.current = 0;
        setConnected(true);
        startHeartbeat();
      };

      ws.onmessage = (event) => {
        try {
          const msg: WSMessage = JSON.parse(event.data);
          // 忽略 pong 心跳响应
          if (msg.type === "pong") return;
          onMessageRef.current?.(msg);
        } catch {
          // 忽略非 JSON 消息
        }
      };

      ws.onerror = () => {
        // error 事件后通常会跟一个 close 事件
      };

      ws.onclose = () => {
        setConnected(false);
        clearTimers();

        // 自动重连
        if (
          enabled &&
          reconnectAttemptsRef.current < maxReconnectAttempts
        ) {
          reconnectAttemptsRef.current += 1;
          // 指数退避：3s, 6s, 12s, 24s, 48s
          const delay = reconnectInterval * Math.pow(2, reconnectAttemptsRef.current - 1);
          reconnectTimerRef.current = setTimeout(() => {
            connect();
          }, delay);
        }
      };
    } catch {
      // WebSocket 构造失败，尝试重连
      if (enabled && reconnectAttemptsRef.current < maxReconnectAttempts) {
        reconnectAttemptsRef.current += 1;
        reconnectTimerRef.current = setTimeout(() => connect(), reconnectInterval);
      }
    }
  }, [url, token, enabled, reconnectInterval, maxReconnectAttempts, clearTimers, startHeartbeat]);

  // 连接/断开
  useEffect(() => {
    if (enabled && token) {
      connect();
    }

    return () => {
      if (wsRef.current) {
        wsRef.current.close(1000, "component unmount");
        wsRef.current = null;
      }
      clearTimers();
      reconnectAttemptsRef.current = 0;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, token]);

  // 页面可见性变化时重连
  useEffect(() => {
    const handleVisibility = () => {
      if (
        document.visibilityState === "visible" &&
        enabled &&
        token &&
        wsRef.current?.readyState !== WebSocket.OPEN
      ) {
        reconnectAttemptsRef.current = 0;
        connect();
      }
    };
    document.addEventListener("visibilitychange", handleVisibility);
    return () => document.removeEventListener("visibilitychange", handleVisibility);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, token]);

  const send = useCallback((msg: WSMessage) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(msg));
    }
  }, []);

  const reconnect = useCallback(() => {
    reconnectAttemptsRef.current = 0;
    if (wsRef.current) {
      wsRef.current.close();
    }
    connect();
  }, [connect]);

  return { connected, send, reconnect };
}
