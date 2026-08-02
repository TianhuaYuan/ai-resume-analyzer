import {
  createContext,
  useContext,
  useState,
  useCallback,
  type ReactNode,
} from "react";
import type { ConversationItem } from "../api/qa";

/**
 * AppChatContext — QAPage 与 Sidebar 之间的共享状态。
 *
 * QAPage 负责所有 API 调用（加载/创建/删除对话），并通过 setter
 * 同步到 Context；Sidebar 从 Context 读取对话列表并展示，
 * 用户操作通过 window CustomEvent 通知 QAPage 执行。
 *
 * 事件协议：
 *  - "chat:select-conversation"  detail: { conversationId: number }
 *  - "chat:create-conversation"  (无 detail)
 *  - "chat:delete-conversation"  detail: { conversationId: number }
 *  - "chat:rename-conversation"  detail: { conversationId: number, title: string }
 */

interface AppChatContextValue {
  /** 当前选中的简历 ID（QAPage 自动选择后写入） */
  resumeId: number | null;
  /** 对话列表 */
  conversations: ConversationItem[];
  /** 当前活跃对话 ID */
  activeConversationId: number | null;
  /** 是否正在加载对话 */
  conversationLoading: boolean;

  setResumeId: (id: number | null) => void;
  setConversations: (convs: ConversationItem[]) => void;
  setActiveConversationId: (id: number | null) => void;
  setConversationLoading: (loading: boolean) => void;
}

const AppChatContext = createContext<AppChatContextValue | null>(null);

export function AppChatProvider({ children }: { children: ReactNode }) {
  const [resumeId, setResumeId] = useState<number | null>(null);
  const [conversations, setConversations] = useState<ConversationItem[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<number | null>(null);
  const [conversationLoading, setConversationLoading] = useState(false);

  const value: AppChatContextValue = {
    resumeId,
    conversations,
    activeConversationId,
    conversationLoading,
    setResumeId: useCallback((id: number | null) => setResumeId(id), []),
    setConversations: useCallback((convs: ConversationItem[]) => setConversations(convs), []),
    setActiveConversationId: useCallback((id: number | null) => setActiveConversationId(id), []),
    setConversationLoading: useCallback((loading: boolean) => setConversationLoading(loading), []),
  };

  return <AppChatContext.Provider value={value}>{children}</AppChatContext.Provider>;
}

export function useAppChat() {
  const ctx = useContext(AppChatContext);
  if (!ctx) throw new Error("useAppChat must be used within AppChatProvider");
  return ctx;
}

// ── 事件工具函数（Sidebar 调用，QAPage 监听） ──

export function dispatchSelectConversation(conversationId: number) {
  window.dispatchEvent(
    new CustomEvent("chat:select-conversation", { detail: { conversationId } }),
  );
}

export function dispatchCreateConversation() {
  window.dispatchEvent(new CustomEvent("chat:create-conversation"));
}

export function dispatchDeleteConversation(conversationId: number) {
  window.dispatchEvent(
    new CustomEvent("chat:delete-conversation", { detail: { conversationId } }),
  );
}

export function dispatchRenameConversation(conversationId: number, title: string) {
  window.dispatchEvent(
    new CustomEvent("chat:rename-conversation", { detail: { conversationId, title } }),
  );
}
