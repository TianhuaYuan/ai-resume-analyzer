/**
 * ChatPanel — 从 QAPage 提取的 Agent 聊天面板（v2 简化版）。
 *
 * 核心功能：
 * - 输入框向 Agent 提问（使用 unified /ask/agent）
 * - SSE 流式通信 + AgentProcessPanel 推理过程
 * - MarkdownRenderer 渲染最终答案
 * - 对话历史（可选）
 *
 * 简化点（vs QAPage）：
 * - 移除对比选择、简历切换等复杂 UI
 * - 保留核心聊天 + 历史搜索
 */

import { useState, useRef, useEffect, useCallback, memo } from "react";
import { PaperPlaneRight, Stop, MagnifyingGlass } from "@phosphor-icons/react";
import { askAgentStream, getHistory, type AgentSSEEvent, type AgentStep } from "../../api/qa";
import type { ResumeModule } from "../../api/builder";
import AgentProcessPanel from "../AgentProcessPanel";
import MarkdownRenderer from "../MarkdownRenderer";
import ChatInput from "../ChatInput";

// ── 类型定义 ──────────────────────────────────────────────

interface ChatMessage {
  id: number | string;
  question: string;
  answer: string;
  streaming: boolean;
  agent_steps?: AgentStep[];
  created_at?: string;
}

interface ChatPanelProps {
  /** 简历 ID */
  resumeId: number;
  /** 当前模块列表（用于上下文） */
  modules?: ResumeModule[];
  /** Agent 完成后刷新回调 */
  onModulesRefresh?: () => void;
}

// ── 流式光标 ──────────────────────────────────────────────

function StreamingCursor() {
  return (
    <span className="inline-block w-0.5 h-4 bg-brand/70 animate-pulse ml-0.5 align-text-bottom" />
  );
}

// ── 消息气泡 ──────────────────────────────────────────────

const MessageBubble = memo(function MessageBubble({ msg }: { msg: ChatMessage }) {
  return (
    <div className="group animate-fade-in-up">
      {/* 用户问题 */}
      <div className="flex justify-end mb-4">
        <div className="max-w-[75%] px-4 py-3 bg-brand text-white text-sm leading-relaxed rounded-2xl rounded-br-md">
          {msg.question}
        </div>
      </div>

      {/* AI 回答 */}
      <div className="flex justify-start mb-4">
        <div className="max-w-[82%]">
          <div className="px-4 py-3.5 rounded-2xl rounded-bl-md leading-relaxed text-sm
            bg-[var(--color-bg-secondary)] border border-[var(--color-border)]">
            {msg.streaming || (msg.agent_steps && msg.agent_steps.length > 0) ? (
              <AgentProcessPanel steps={msg.agent_steps ?? []} streaming={msg.streaming} />
            ) : null}
            {msg.streaming && !msg.answer && !(msg.agent_steps && msg.agent_steps.length > 0) ? (
              <span className="text-[var(--color-text-muted)]">思考中...</span>
            ) : (
              <MarkdownRenderer>{msg.answer}</MarkdownRenderer>
            )}
            {msg.streaming && msg.answer && <StreamingCursor />}
          </div>
        </div>
      </div>
    </div>
  );
});

// ── 主组件 ──────────────────────────────────────────────

export function ChatPanel({ resumeId, modules, onModulesRefresh }: ChatPanelProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [question, setQuestion] = useState("");
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState("");
  const [history, setHistory] = useState<Array<{ id: number; question: string; answer: string; created_at: string }>>([]);
  const [showHistory, setShowHistory] = useState(false);
  const [historyKeyword, setHistoryKeyword] = useState("");

  const abortRef = useRef<(() => void) | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // 自动滚动到底部
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  // ── 发送问题 ──
  const sendQuestion = useCallback(
    (q: string) => {
      if (!q.trim() || asking) return;
      setError("");
      setAsking(true);
      setShowHistory(false);

      const tempId = `streaming-${Date.now()}`;
      const newMsg: ChatMessage = {
        id: tempId,
        question: q,
        answer: "",
        streaming: true,
      };
      setMessages((prev) => [...prev, newMsg]);

      abortRef.current = askAgentStream(
        resumeId,
        q,
        (event: AgentSSEEvent) => {
          if (event.type === "agent_start") {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === tempId ? { ...m, agent_steps: [] } : m,
              ),
            );
          } else if (event.type === "agent_thought") {
            setMessages((prev) =>
              prev.map((m) => {
                if (m.id !== tempId) return m;
                const steps = m.agent_steps ?? [];
                const lastStep = steps[steps.length - 1];
                if (lastStep && lastStep.type === "agent_thought") {
                  const updatedSteps = [...steps];
                  updatedSteps[updatedSteps.length - 1] = {
                    ...lastStep,
                    detail: (lastStep.detail ?? "") + event.content,
                  };
                  return { ...m, agent_steps: updatedSteps };
                }
                return {
                  ...m,
                  agent_steps: [
                    ...steps,
                    { type: "agent_thought" as const, name: "思考", detail: event.content },
                  ],
                };
              }),
            );
          } else if (event.type === "tool_call") {
            setMessages((prev) =>
              prev.map((m) => {
                if (m.id !== tempId) return m;
                return {
                  ...m,
                  agent_steps: [
                    ...(m.agent_steps ?? []),
                    {
                      type: "tool_call" as const,
                      name: event.tool_name ?? "",
                      detail: JSON.stringify(event.args ?? {}),
                      id: event.id,
                    },
                  ],
                };
              }),
            );
          } else if (event.type === "tool_result") {
            setMessages((prev) =>
              prev.map((m) => {
                if (m.id !== tempId) return m;
                return {
                  ...m,
                  agent_steps: [
                    ...(m.agent_steps ?? []),
                    {
                      type: "tool_result" as const,
                      name: event.tool_name ?? "",
                      detail: event.summary,
                      id: event.id,
                    },
                  ],
                };
              }),
            );
          } else if (event.type === "agent_done") {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === tempId
                  ? {
                      ...m,
                      id: event.qa_id ?? tempId,
                      answer: event.answer ?? "",
                      streaming: false,
                    }
                  : m,
              ),
            );
            setAsking(false);
            onModulesRefresh?.();
          } else if (event.type === "error") {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === tempId
                  ? { ...m, answer: event.message ?? "处理失败", streaming: false }
                  : m,
              ),
            );
            setAsking(false);
          }
        },
        (err: Error) => {
          setError(err.message);
          setMessages((prev) =>
            prev.map((m) =>
              m.id === tempId ? { ...m, answer: "生成失败，请重试", streaming: false } : m,
            ),
          );
          setAsking(false);
        },
        () => {
          setAsking(false);
        },
      );
    },
    [resumeId, asking, onModulesRefresh],
  );

  // ── 停止生成 ──
  const handleStop = useCallback(() => {
    abortRef.current?.();
    setAsking(false);
  }, []);

  // ── 加载历史 ──
  const loadHistory = useCallback(async () => {
    try {
      const data = await getHistory(resumeId, 20, 0, historyKeyword || undefined);
      setHistory(data.items ?? []);
    } catch {
      // 忽略
    }
  }, [resumeId, historyKeyword]);

  useEffect(() => {
    if (showHistory) loadHistory();
  }, [showHistory, loadHistory]);

  // ── 渲染 ──
  return (
    <div className="flex flex-col h-full bg-[var(--color-bg)]">
      {/* 历史搜索栏 */}
      {showHistory && (
        <div className="shrink-0 px-3 py-2 border-b border-[var(--color-border)]">
          <div className="flex items-center gap-2">
            <MagnifyingGlass size={14} className="text-[var(--color-text-muted)]" />
            <input
              type="text"
              value={historyKeyword}
              onChange={(e) => setHistoryKeyword(e.target.value)}
              placeholder="搜索历史对话..."
              className="flex-1 text-xs bg-transparent outline-none"
            />
          </div>
          <div className="mt-2 max-h-40 overflow-y-auto space-y-1">
            {history.map((h) => (
              <button
                key={h.id}
                onClick={() => {
                  setMessages((prev) => [
                    ...prev,
                    { id: h.id, question: h.question, answer: h.answer, streaming: false, created_at: h.created_at },
                  ]);
                  setShowHistory(false);
                }}
                className="w-full text-left px-2 py-1.5 rounded-lg text-xs
                  text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-secondary)] truncate cursor-pointer"
              >
                {h.question}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* 消息列表 */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-4 space-y-2">
        {messages.length === 0 && !asking && (
          <div className="flex flex-col items-center justify-center h-full text-center">
            <div className="w-12 h-12 rounded-2xl bg-brand/10 flex items-center justify-center mb-3">
              <span className="text-brand text-xl">💬</span>
            </div>
            <p className="text-sm font-medium text-[var(--color-text-secondary)] mb-1">
              AI 简历助手
            </p>
            <p className="text-xs text-[var(--color-text-muted)] max-w-[240px]">
              问我任何关于简历的问题，或让我帮你优化、翻译、诊断简历
            </p>
          </div>
        )}
        {messages.map((msg) => (
          <MessageBubble key={msg.id} msg={msg} />
        ))}
        {error && (
          <div className="text-center text-xs text-red-400 py-2">{error}</div>
        )}
      </div>

      {/* 输入区 */}
      <div className="shrink-0 px-4 py-3 border-t border-[var(--color-border)]">
        <div className="flex items-center gap-2">
          <input
            ref={inputRef}
            type="text"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                sendQuestion(question);
                setQuestion("");
              }
            }}
            placeholder="问我关于简历的问题..."
            className="flex-1 px-4 py-2.5 rounded-xl text-sm bg-[var(--color-bg-secondary)]
              border border-[var(--color-border)] focus:outline-none focus:border-brand/40
              focus:ring-4 focus:ring-brand/15 transition-all"
            disabled={asking}
          />
          {asking ? (
            <button
              onClick={handleStop}
              className="p-2.5 rounded-xl bg-red-500 text-white hover:bg-red-600 transition-colors cursor-pointer"
              title="停止生成"
            >
              <Stop size={16} weight="fill" />
            </button>
          ) : (
            <button
              onClick={() => {
                sendQuestion(question);
                setQuestion("");
              }}
              disabled={!question.trim()}
              className="p-2.5 rounded-xl bg-brand text-white hover:bg-brand/90
                disabled:opacity-40 disabled:cursor-not-allowed transition-colors cursor-pointer"
              title="发送"
            >
              <PaperPlaneRight size={16} weight="fill" />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
