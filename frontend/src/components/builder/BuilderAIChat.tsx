/**
 * T31: BuilderAIChat — Builder AI 聊天面板。
 *
 * 功能：
 * - 输入框向 Builder Agent 提问
 * - 使用 askBuilderStream() 进行 SSE 流式通信
 * - 使用 AgentProcessPanel 展示 Agent 推理过程
 * - 使用 MarkdownRenderer 渲染最终答案
 * - 会话内保留对话历史
 * - 可通过外部触发自动发送问题（如 ModuleList 的 AI 生成按钮）
 * - 可切换显示/隐藏
 */

import {
  useState,
  useRef,
  useEffect,
  useCallback,
  type FormEvent,
} from "react";
import { ChatCircleDots, PaperPlaneRight, X, Stop } from "@phosphor-icons/react";
import { askBuilderStream } from "../../api/builder";
import type { AgentSSEEvent, AgentStep } from "../../api/qa";
import AgentProcessPanel from "../AgentProcessPanel";
import MarkdownRenderer from "../MarkdownRenderer";

/** 对话消息 */
interface ChatMessage {
  id: number | string;
  question: string;
  answer: string;
  streaming: boolean;
  agent_steps?: AgentStep[];
}

interface BuilderAIChatProps {
  /** 简历 ID */
  resumeId: number;
  /** 是否显示 */
  show: boolean;
  /** 切换显示回调 */
  onToggle: () => void;
  /** 外部触发的问题（如 ModuleList AI 生成） */
  externalQuestion?: string;
  /** 外部触发序号（变化时发送 externalQuestion） */
  externalTrigger?: number;
  /** agent 回复完成回调（用于刷新模块、回填表单） */
  onAgentDone?: () => void;
}

export function BuilderAIChat({
  resumeId,
  show,
  onToggle,
  externalQuestion,
  externalTrigger,
  onAgentDone,
}: BuilderAIChatProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [question, setQuestion] = useState("");
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState("");

  const abortRef = useRef<(() => void) | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const externalQuestionRef = useRef(externalQuestion);
  externalQuestionRef.current = externalQuestion;

  // 发送问题（核心 SSE 逻辑）
  const sendQuestion = useCallback(
    (q: string) => {
      setError("");
      setAsking(true);

      const tempId = `streaming-${Date.now()}`;
      const newMsg: ChatMessage = {
        id: tempId,
        question: q,
        answer: "",
        streaming: true,
      };
      setMessages((prev) => [...prev, newMsg]);

      abortRef.current = askBuilderStream(
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
            // Spec A#7: LLM 推理过程内容，流式分段 emit，需追加到最后一个 agent_thought step
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
                    {
                      type: "agent_thought" as const,
                      name: "思考",
                      detail: event.content,
                    },
                  ],
                };
              }),
            );
          } else if (event.type === "tool_stream") {
            // T17: 工具内部 LLM 流式 token → 追加到最后一个同工具 tool_stream step（边出边看）
            setMessages((prev) =>
              prev.map((m) => {
                if (m.id !== tempId) return m;
                const steps = m.agent_steps ?? [];
                const lastStep = steps[steps.length - 1];
                if (
                  lastStep &&
                  lastStep.type === "tool_stream" &&
                  lastStep.name === event.tool_name
                ) {
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
                    {
                      type: "tool_stream" as const,
                      name: event.tool_name ?? "",
                      detail: event.content ?? "",
                    },
                  ],
                };
              }),
            );
          } else if (event.type === "tool_call") {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === tempId
                  ? {
                      ...m,
                      agent_steps: [
                        ...(m.agent_steps ?? []),
                        {
                          type: "tool_call" as const,
                          name: event.tool_name ?? "",
                          detail: event.args,
                          id: event.id,
                        },
                      ],
                    }
                  : m,
              ),
            );
          } else if (event.type === "tool_result") {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === tempId
                  ? {
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
                    }
                  : m,
              ),
            );
          } else if (event.type === "tool_error") {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === tempId
                  ? {
                      ...m,
                      agent_steps: [
                        ...(m.agent_steps ?? []),
                        {
                          type: "tool_error" as const,
                          name: event.tool_name ?? "",
                          detail: event.error,
                          id: event.id,
                        },
                      ],
                    }
                  : m,
              ),
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
                      // Spec: process_trace 是紧凑摘要，不覆盖 agent_steps
                    }
                  : m,
              ),
            );
            setAsking(false);
            // 通知父组件刷新模块（agent 可能已通过工具写入/修改了模块）
            onAgentDone?.();
          } else if (event.type === "quota_exceeded") {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === tempId
                  ? {
                      ...m,
                      answer: event.message ?? "今日额度已用完",
                      streaming: false,
                    }
                  : m,
              ),
            );
            setAsking(false);
          } else if (event.type === "error") {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === tempId
                  ? {
                      ...m,
                      answer: event.message ?? "Agent 处理失败",
                      streaming: false,
                    }
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
              m.id === tempId
                ? { ...m, answer: "生成失败，请重试", streaming: false }
                : m,
            ),
          );
          setAsking(false);
        },
        () => {
          setAsking(false);
          setMessages((prev) =>
            prev.map((m) =>
              m.id === tempId ? { ...m, streaming: false } : m,
            ),
          );
        },
      );
    },
    [resumeId, onAgentDone],
  );

  // 外部触发（ModuleList AI 生成按钮）
  useEffect(() => {
    if (
      externalTrigger !== undefined &&
      externalTrigger > 0 &&
      externalQuestionRef.current
    ) {
      sendQuestion(externalQuestionRef.current);
    }
  }, [externalTrigger, sendQuestion]);

  // 自动滚动到底部
  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages]);

  // 组件卸载时取消请求
  useEffect(() => {
    return () => abortRef.current?.();
  }, []);

  const handleSend = useCallback(
    (e: FormEvent) => {
      e.preventDefault();
      const q = question.trim();
      if (!q || asking) return;
      setQuestion("");
      sendQuestion(q);
    },
    [question, asking, sendQuestion],
  );

  const handleCancel = useCallback(() => {
    abortRef.current?.();
    setAsking(false);
    setMessages((prev) =>
      prev.map((m) =>
        m.streaming
          ? { ...m, answer: m.answer || "已取消", streaming: false }
          : m,
      ),
    );
  }, []);

  if (!show) return null;

  return (
    <div className="flex flex-col h-full w-80 border-l border-[var(--color-border)]
      bg-[var(--color-bg)] animate-fade-in-up motion-reduce:animate-none">
      {/* 标题栏 */}
      <div className="shrink-0 flex items-center justify-between px-4 py-3
        border-b border-[var(--color-border)]">
        <div className="flex items-center gap-2">
          <ChatCircleDots
            size={14}
            weight="duotone"
            className="text-brand"
            aria-hidden="true"
          />
          <h3 className="text-xs font-semibold text-[var(--color-text-secondary)] uppercase tracking-wider">
            AI 助手
          </h3>
        </div>
        <button
          onClick={onToggle}
          className="p-1 rounded-md text-[var(--color-text-muted)]
            hover:text-[var(--color-text)] hover:bg-[var(--color-bg-secondary)]
            transition-all cursor-pointer"
          aria-label="关闭 AI 助手"
        >
          <X size={14} weight="bold" aria-hidden="true" />
        </button>
      </div>

      {/* 消息列表 */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
        {messages.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-center">
            <div className="w-14 h-14 rounded-2xl bg-brand/10 border border-brand/15
              flex items-center justify-center text-brand mb-4">
              <ChatCircleDots size={24} weight="duotone" aria-hidden="true" />
            </div>
            <p className="text-sm text-[var(--color-text-secondary)] mb-1">
              向 AI 提问
            </p>
            <p className="text-xs text-[var(--color-text-muted)] max-w-[220px]">
              AI 可以帮你生成模块内容、优化措辞、检查格式
            </p>
          </div>
        ) : (
          messages.map((msg) => (
            <div key={String(msg.id)} className="animate-fade-in-up">
              {/* 用户问题 */}
              <div className="flex justify-end mb-3">
                <div className="max-w-[85%] px-3 py-2 bg-brand
                  text-white text-xs leading-relaxed rounded-2xl rounded-br-md">
                  {msg.question}
                </div>
              </div>

              {/* AI 回答 */}
              <div className="flex justify-start mb-3">
                <div className="max-w-[90%] w-full">
                  <div className="px-3 py-2.5 rounded-2xl rounded-bl-md leading-relaxed text-sm
                    bg-[var(--color-bg-secondary)] border border-[var(--color-border)]">
                    {/* Agent 推理过程 */}
                    {msg.agent_steps && msg.agent_steps.length > 0 && (
                      <AgentProcessPanel
                        steps={msg.agent_steps}
                        streaming={msg.streaming}
                      />
                    )}
                    {msg.streaming && !msg.answer ? (
                      <span className="text-[var(--color-text-muted)] text-xs">
                        {msg.agent_steps ? "Agent 思考中..." : "思考中..."}
                      </span>
                    ) : (
                      <MarkdownRenderer>{msg.answer}</MarkdownRenderer>
                    )}
                    {msg.streaming && msg.answer && (
                      <span className="inline-block w-0.5 h-4 bg-brand ml-0.5
                        align-middle animate-cursor-blink" />
                    )}
                  </div>
                </div>
              </div>
            </div>
          ))
        )}

        {/* 错误提示 */}
        {error && (
          <div className="p-2.5 rounded-xl bg-red-500/10 border border-red-500/20
            text-red-400 text-xs">
            {error}
          </div>
        )}
      </div>

      {/* 输入区 */}
      <div className="shrink-0 px-3 py-3 border-t border-[var(--color-border)]">
        <form onSubmit={handleSend} className="flex gap-2 items-center">
          <input
            type="text"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="输入问题..."
            disabled={asking}
            className="flex-1 px-3 py-2 rounded-xl text-xs text-[var(--color-text)]
              bg-[#F2F2F7] border border-transparent
              placeholder:text-[var(--color-text-muted)]
              focus:outline-none focus:bg-white focus:ring-4 focus:ring-brand/15
              focus:border-brand/40
              disabled:opacity-50 transition-all duration-150"
          />
          {asking ? (
            <button
              type="button"
              onClick={handleCancel}
              className="shrink-0 p-2 rounded-xl text-xs font-medium
                border border-[var(--color-border)] text-[var(--color-text-secondary)]
                hover:text-red-400 hover:border-red-500/30 hover:bg-red-500/8
                transition-all cursor-pointer"
              aria-label="取消"
            >
              <Stop size={14} weight="fill" aria-hidden="true" />
            </button>
          ) : (
            <button
              type="submit"
              disabled={!question.trim()}
              className="shrink-0 p-2 rounded-xl text-white
                bg-brand
                hover:brightness-110
                disabled:opacity-40 disabled:cursor-not-allowed
                transition-all cursor-pointer"
              aria-label="发送"
            >
              <PaperPlaneRight size={14} weight="fill" aria-hidden="true" />
            </button>
          )}
        </form>
      </div>
    </div>
  );
}
