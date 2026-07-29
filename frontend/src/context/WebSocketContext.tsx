import { createContext, useContext, useCallback, type ReactNode } from "react";
import { useWebSocket, type WSMessage } from "../hooks/useWebSocket";
import { useToast } from "../components/Toast";
import { useAuth } from "./AuthContext";

interface WebSocketContextValue {
  connected: boolean;
  send: (msg: WSMessage) => void;
}

const WebSocketContext = createContext<WebSocketContextValue>({
  connected: false,
  send: () => {},
});

/**
 * WebSocket 全局 Provider
 *
 * 在 App 根部包裹，登录后自动连接 WebSocket，
 * 接收后台分析完成/失败通知，并展示 Toast。
 */
export function WebSocketProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const { success, error, info } = useToast();

  // 从 localStorage 获取 token
  const token = user ? localStorage.getItem("access_token") : null;

  // 确定 WebSocket URL
  const wsUrl = (() => {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const host = window.location.host;
    return `${protocol}//${host}/api/v1/ws`;
  })();

  const handleMessage = useCallback(
    (msg: WSMessage) => {
      switch (msg.type) {
        case "analysis_complete":
          if (msg.status === "completed") {
            success(
              `简历分析已完成，可查看完整分析结果`,
              { title: "分析完成" }
            );
            // 触发额度刷新（自定义事件，QAPage 监听）
            window.dispatchEvent(new CustomEvent("quota:refresh"));
          } else if (msg.status === "failed") {
            error(
              msg.data?.message as string || "简历分析失败，请稍后重试",
              { title: "分析失败" }
            );
          } else if (msg.status === "quota_exceeded") {
            info(
              msg.data?.message as string || "Token 额度不足，分析已暂停",
              { title: "额度不足" }
            );
            window.dispatchEvent(new CustomEvent("quota:refresh"));
          }
          break;

        default:
          // 其他消息类型暂不处理
          break;
      }
    },
    [success, error, info]
  );

  const { connected, send } = useWebSocket({
    url: wsUrl,
    token,
    enabled: !!user,
    onMessage: handleMessage,
  });

  return (
    <WebSocketContext.Provider value={{ connected, send }}>
      {children}
    </WebSocketContext.Provider>
  );
}

export function useWebSocketContext() {
  return useContext(WebSocketContext);
}
