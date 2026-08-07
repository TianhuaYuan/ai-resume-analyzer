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
  token_used?: number;
  completed?: number;
  total?: number;
  current_type?: string;
  current_type_label?: string;
  // 上传简历解析进度（parse_progress 事件）
  stage?: string;
  percent?: number;
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

  // 使用 ref 追踪 token/enabled，避免 React 状态闪烁断开 WS
  const enabledRef = useRef(enabled);
  const tokenRef = useRef(token);
  enabledRef.current = enabled;
  tokenRef.current = token;

  const connect = useCallback(() => {
    if (!enabledRef.current || !tokenRef.current) return;

    // 清掉旧的 heartbeat / reconnect 定时器，避免重复 startHeartbeat 泄漏 interval
    clearTimers();

    // 先关闭旧连接（reconnect()/visibilitychange 路径会走到这里，旧连接可能仍 CONNECTING），
    // 避免 new WebSocket 覆盖 wsRef 时旧连接挂在服务器上泄漏
    if (wsRef.current && wsRef.current.readyState !== WebSocket.CLOSED) {
      try {
        wsRef.current.close(1000, "reconnect");
      } catch {
        // 忽略关闭异常
      }
    }

    const wsUrl = `${url}?token=${encodeURIComponent(tokenRef.current)}`;

    try {
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        // 过期连接（已被替换/关闭）的回调直接忽略，避免污染新连接状态
        if (wsRef.current !== ws) return;
        reconnectAttemptsRef.current = 0;
        setConnected(true);
        startHeartbeat();
      };

      ws.onmessage = (event) => {
        if (wsRef.current !== ws) return;
        try {
          const msg: WSMessage = JSON.parse(event.data);
          if (msg.type === "pong") return;
          onMessageRef.current?.(msg);
        } catch {
          // 忽略非 JSON 消息
        }
      };

      ws.onerror = () => {
        // error 事件后通常会跟一个 close 事件
      };

      ws.onclose = (event: CloseEvent) => {
        // 过期连接的回调直接忽略（cleanup 主动关闭时 wsRef.current 已置 null）
        if (wsRef.current !== ws) return;
        setConnected(false);
        clearTimers();

        const isUnmount = event.code === 1000 && event.reason === "component unmount";
        if (
          !isUnmount &&
          enabledRef.current &&
          reconnectAttemptsRef.current < maxReconnectAttempts
        ) {
          reconnectAttemptsRef.current += 1;
          const delay = reconnectInterval * Math.pow(2, reconnectAttemptsRef.current - 1);
          reconnectTimerRef.current = setTimeout(() => { connect(); }, delay);
        }
      };
    } catch {
      if (enabledRef.current && reconnectAttemptsRef.current < maxReconnectAttempts) {
        reconnectAttemptsRef.current += 1;
        reconnectTimerRef.current = setTimeout(() => connect(), reconnectInterval);
      }
    }
  }, [url, reconnectInterval, maxReconnectAttempts, clearTimers, startHeartbeat]);

  // 连接管理：只在 enabled/token 变化时尝试连接。
  // cleanup 必须主动关闭 WS——StrictMode 双挂载 / 页面卸载 / token 刷新时，
  // 若不关闭，旧连接对象被覆盖但连接仍挂在服务器 → 服务器连接数只增不减（泄漏）。
  useEffect(() => {
    if (enabled && token && (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN)) {
      connect();
    }
    return () => {
      const ws = wsRef.current;
      wsRef.current = null;
      if (ws) {
        try {
          ws.close(1000, "component unmount");
        } catch {
          // 忽略关闭异常
        }
      }
      clearTimers();
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
