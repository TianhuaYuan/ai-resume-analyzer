import { createContext, useContext, useCallback, useMemo, type ReactNode } from "react";
import { useWebSocket, type WSMessage } from "../hooks/useWebSocket";
import { useToast } from "../components/Toast";
import { useAuth } from "./AuthContext";
import { setCachedProgress } from "../stores/progressStore";

interface WebSocketContextValue {
  connected: boolean;
  send: (msg: WSMessage) => void;
}

const WebSocketContext = createContext<WebSocketContextValue>({
  connected: false,
  send: () => {},
});

export function WebSocketProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const { success, error, info } = useToast();

  const token = user ? localStorage.getItem("access_token") : null;

  const wsUrl = (() => {
    const isDev = window.location.hostname === "localhost" && window.location.port === "5173";
    if (isDev) {
      return "ws://127.0.0.1:8081/api/v1/ws";
    }
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${protocol}//${window.location.host}/api/v1/ws`;
  })();

  const handleMessage = useCallback(
    (msg: WSMessage) => {
      switch (msg.type) {
        case "analysis_complete":
          if (msg.status === "completed") {
            const tokenInfo = msg.token_used ? `（消耗 ${msg.token_used} tokens）` : "";
            success(`简历分析已完成${tokenInfo}`, { title: "分析完成" });
            window.dispatchEvent(new CustomEvent("quota:refresh"));
            window.dispatchEvent(
              new CustomEvent("resume:analysis-complete", {
                detail: { resume_id: msg.resume_id },
              })
            );
          } else if (msg.status === "failed") {
            error(msg.data?.message as string || "简历分析失败，请稍后重试", { title: "分析失败" });
            window.dispatchEvent(
              new CustomEvent("resume:analysis-failed", {
                detail: { resume_id: msg.resume_id, message: msg.data?.message },
              })
            );
          } else if (msg.status === "quota_exceeded") {
            info(msg.data?.message as string || "Token 额度不足，分析已暂停", { title: "额度不足" });
            window.dispatchEvent(new CustomEvent("quota:refresh"));
          }
          break;

        case "analysis_update":
          if (msg.status === "started") {
            window.dispatchEvent(
              new CustomEvent("resume:analysis-start", {
                detail: { resume_id: msg.resume_id },
              })
            );
          }
          break;

        case "analysis_progress":
          if (msg.resume_id != null && msg.completed != null && msg.total != null) {
            setCachedProgress(msg.resume_id, {
              completed: msg.completed,
              total: msg.total,
              current_type: msg.current_type || "",
              current_type_label: msg.current_type_label || "",
            });
          }
          window.dispatchEvent(
            new CustomEvent("resume:analysis-progress", {
              detail: {
                resume_id: msg.resume_id,
                completed: msg.completed,
                total: msg.total,
                current_type: msg.current_type,
                current_type_label: msg.current_type_label,
              },
            })
          );
          break;

        case "parse_progress":
          // 上传简历解析进度（parsing → materializing → done），驱动卡片进度条
          window.dispatchEvent(
            new CustomEvent("resume:parse-progress", {
              detail: {
                resume_id: msg.resume_id,
                stage: msg.stage,
                percent: msg.percent,
                message: msg.message,
              },
            })
          );
          break;

        default:
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

  // memoize context value：send 稳定，仅 connected 变化时重建，
  // 避免 WebSocketProvider 每次渲染都新建对象 → 所有 useWebSocketContext 消费者级联重渲染
  const value = useMemo(() => ({ connected, send }), [connected, send]);

  return (
    <WebSocketContext.Provider value={value}>
      {children}
    </WebSocketContext.Provider>
  );
}

export function useWebSocketContext() {
  return useContext(WebSocketContext);
}
