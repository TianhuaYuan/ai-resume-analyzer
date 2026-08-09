import { useCallback, useEffect, useRef, useState } from "react";
import type { ChatMessage } from "./ChatMessage";

/**
 * useChatScroll — QA 页消息区滚动跟踪。
 *
 * 提供：
 * - scrollContainerRef / chatEndRef：挂在滚动容器与列表末尾
 * - isNearBottomRef：距底部 80px 内视为"在底部"（流式刷新时仅底部时自动滚）
 * - checkNearBottom：onScroll 回调
 * - scrollToBottom：平滑/瞬时滚动到底
 * - scrolled：滚动离开顶部（供 Navbar 滚动渐变背景）
 * - 自动滚动触发 effect：新消息加入 / 流式内容增长 / 流式刚结束 三种时机
 */
export function useChatScroll(chat: ChatMessage[]) {
  const chatEndRef = useRef<HTMLDivElement>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);

  // 实时滚动：跟踪用户是否在底部（上滚暂停自动滚动，回底部恢复）
  const isNearBottomRef = useRef(true);
  const [scrolled, setScrolled] = useState(false);

  /** 检测滚动容器是否在底部附近（距底部 80px 以内视为"在底部"） */
  const checkNearBottom = useCallback(() => {
    const el = scrollContainerRef.current;
    if (!el) return;
    const threshold = 80;
    isNearBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < threshold;
    setScrolled(el.scrollTop > 24);
  }, []);

  /** 滚动到底部（smooth） */
  const scrollToBottom = useCallback((smooth = true) => {
    const el = scrollContainerRef.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior: smooth ? "smooth" : "instant" });
  }, []);

  // 滚动到底部：仅在新消息添加或流式回答增长时触发
  // 仅当用户在底部附近时才自动滚动，避免打断用户阅读历史
  const prevChatLenRef = useRef(0);
  const prevLastAnswerRef = useRef("");
  const prevStreamingRef = useRef(false);
  useEffect(() => {
    const len = chat.length;
    const lastMsg = chat[len - 1];
    const lastAnswer = lastMsg?.answer ?? "";
    const isStreaming = lastMsg?.streaming ?? false;
    const streamingJustEnded = prevStreamingRef.current && !isStreaming;

    // 触发滚动的条件：
    // 1. 新消息加入
    // 2. 流式回答内容增长（streaming 中）
    // 3. 流式刚结束（streaming→false，AgentProcessPanel 折叠后高度变化，需重新定位底部）
    if (len > prevChatLenRef.current ||
        (isStreaming && lastAnswer !== prevLastAnswerRef.current) ||
        streamingJustEnded) {
      if (isNearBottomRef.current) {
        // 新消息加入 / 流式结束用 instant（立即跳转），流式内容增长用 smooth（平滑跟随）
        const smooth = len === prevChatLenRef.current && !streamingJustEnded;
        scrollToBottom(smooth);
        // 流式结束后：AgentProcessPanel 折叠需要 DOM 更新后高度才变化，
        // 延迟一帧确保折叠完成后再滚动一次，避免停留在被折叠挤占的位置
        if (streamingJustEnded) {
          requestAnimationFrame(() => scrollToBottom(false));
        }
      }
    }
    prevChatLenRef.current = len;
    prevLastAnswerRef.current = lastAnswer;
    prevStreamingRef.current = isStreaming;
  }, [chat, scrollToBottom]);

  return {
    chatEndRef,
    scrollContainerRef,
    isNearBottomRef,
    checkNearBottom,
    scrollToBottom,
    scrolled,
  };
}
