import { useEffect, useState, useRef, useCallback, type FormEvent } from "react";
import { useParams, Link } from "react-router-dom";
import { ChatCircleDots, MagnifyingGlass, Trash, ThumbsUp, ThumbsDown, X } from "@phosphor-icons/react";
import {
  askQuestionStream,
  getHistory,
  clearHistory,
  deleteQa,
  submitFeedback,
  getQuota,
  type SSEEvent,
  type QAMode,
  type QuotaResponse,
} from "../api/qa";
import { listResumes, type ResumeItem } from "../api/resumes";
import ConfirmDialog from "../components/ConfirmDialog";
import MarkdownRenderer from "../components/MarkdownRenderer";

interface ChatMessage {
  id: number | string;
  question: string;
  answer: string;
  sources: string[];
  streaming: boolean;
  /** Task 5.1: 质量反馈状态 */
  feedback?: "positive" | "negative" | null;
  /** 创建时间，用于排序和显示 */
  created_at?: string;
  /** Token 消耗 */
  token_usage?: { total: number; prompt: number; completion: number };
}

// Task 5.1: 预设提问
const PRESET_QUESTIONS = [
  "这份简历的亮点是什么？",
  "适合什么岗位？",
  "技能匹配度如何？",
];

// ── 来源引用组件 ────────────────────────────────────────

const SOURCE_TRUNCATE_LIMIT = 220;

function SourceCard({ index, text }: { index: number; text: string }) {
  const [expanded, setExpanded] = useState(false);
  const isLong = text.length > SOURCE_TRUNCATE_LIMIT;

  return (
    <div className="p-3 rounded-xl bg-indigo-500/6 border border-indigo-500/10 text-xs text-[var(--color-text-secondary)] leading-relaxed">
      <span className="text-indigo-400 font-semibold mr-2">[{index}]</span>
      {isLong && !expanded ? text.slice(0, SOURCE_TRUNCATE_LIMIT) + "..." : text}
      {isLong && (
        <button
          onClick={() => setExpanded((v) => !v)}
          className="ml-1 text-indigo-400 hover:text-indigo-300 underline-offset-2 hover:underline cursor-pointer"
        >
          {expanded ? "收起" : "展开"}
        </button>
      )}
    </div>
  );
}

function SourceToggle({ sources }: { sources: string[] }) {
  const [expanded, setExpanded] = useState(false);

  if (sources.length === 0) return null;

  return (
    <div className="mt-2">
      <button
        onClick={() => setExpanded(!expanded)}
        className="inline-flex items-center gap-1 text-xs text-[var(--color-text-muted)]
          hover:text-indigo-400 hover:bg-indigo-500/8 px-2 py-1 rounded-md
          transition-colors cursor-pointer"
      >
        来源 (<span className="tabular-nums">{sources.length}</span>) {expanded ? "▲" : "▼"}
      </button>
      {expanded && (
        <div className="mt-2 space-y-2 animate-fade-in-up">
          {sources.map((src, j) => (
            <SourceCard key={j} index={j + 1} text={src} />
          ))}
        </div>
      )}
    </div>
  );
}

function StreamingCursor() {
  return (
    <span className="inline-block w-0.5 h-4 bg-indigo-400 ml-0.5 align-middle animate-cursor-blink" />
  );
}

/** 将 ISO 时间字符串格式化为北京时间 "MM-DD HH:mm" */
function formatTimestamp(dateStr?: string): string | null {
  if (!dateStr) return null;
  // 后端返回 naive datetime（无 Z 后缀），实际是 UTC，需补 Z 才能正确转换时区
  const normalized = /[Z+]/.test(dateStr) ? dateStr : dateStr + "Z";
  const d = new Date(normalized);
  if (isNaN(d.getTime())) return null;
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "Asia/Shanghai",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(d);
  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? "";
  return `${get("month")}-${get("day")} ${get("hour")}:${get("minute")}`;
}

// ── 空状态 ──────────────────────────────────────────────

function EmptyChat({
  searching,
  asking,
  onPresetClick,
}: {
  searching: boolean;
  asking: boolean;
  onPresetClick: (q: string) => void;
}) {
  return (
    <div className="flex-1 flex flex-col items-center justify-center py-16">
      <div className="w-16 h-16 rounded-2xl bg-indigo-500/10 border border-indigo-500/15
        flex items-center justify-center text-indigo-400 mb-5">
        <ChatCircleDots size={28} weight="duotone" aria-hidden="true" />
      </div>
      <p className="text-base text-[var(--color-text-secondary)] mb-1.5">
        {searching ? "没有匹配的问答" : "开始提问"}
      </p>
      <p className="text-sm text-[var(--color-text-muted)] mb-4">
        {searching
          ? "换个关键词试试"
          : "点击下方问题快速开始"}
      </p>
      {!searching && (
        <div className="flex flex-wrap justify-center gap-2">
          {PRESET_QUESTIONS.map((q) => (
            <button
              key={q}
              onClick={() => onPresetClick(q)}
              disabled={asking}
              className="px-4 py-2 rounded-xl text-xs text-[var(--color-text-secondary)]
                bg-white/5 border border-[var(--color-border)]
                hover:border-indigo-500/40 hover:text-indigo-300 hover:bg-indigo-500/8
                active:scale-[0.97] motion-reduce:active:scale-100
                transition-all cursor-pointer
                disabled:opacity-40 disabled:cursor-not-allowed"
              aria-label={q}
            >
              {q}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ── 消息气泡 ────────────────────────────────────────────

interface MessageBubbleProps {
  msg: ChatMessage;
  deleting: boolean;
  onDelete: (id: number | string) => void;
  onFeedback: (id: number | string, rating: "positive" | "negative") => void;
}

function MessageBubble({ msg, deleting, onDelete, onFeedback }: MessageBubbleProps) {
  // 流式消息（id 仍是字符串 tempId）不显示删除按钮和反馈按钮
  const canDelete = !msg.streaming && typeof msg.id === "number";
  const canFeedback = !msg.streaming && typeof msg.id === "number";
  return (
    <div className="group animate-fade-in-up">
      {/* 用户问题 */}
      <div className="flex justify-end mb-4">
        <div className="max-w-[75%] px-4 py-3 bg-linear-to-br from-indigo-500 to-purple-600
          text-white text-sm leading-relaxed rounded-2xl rounded-br-md">
          {msg.question}
        </div>
      </div>

      {/* AI 回答 */}
      <div className="flex justify-start mb-4">
        <div className="max-w-[82%]">
          <div className="px-4 py-3.5 rounded-2xl rounded-bl-md leading-relaxed text-sm
            bg-white/5 border border-[var(--color-border)] backdrop-blur-sm">
            {msg.streaming && !msg.answer ? (
              <span className="text-[var(--color-text-muted)]">思考中...</span>
            ) : (
              <MarkdownRenderer>
                {msg.answer}
              </MarkdownRenderer>
            )}
            {msg.streaming && msg.answer && <StreamingCursor />}
          </div>

          {/* 来源引用 + 反馈 + 删除按钮 */}
          {!msg.streaming && (
            <div className="flex items-start justify-between gap-2">
              <div className="flex-1 min-w-0">
                {msg.created_at && formatTimestamp(msg.created_at) && (
                  <span
                    data-testid="message-timestamp"
                    className="text-[10px] text-[var(--color-text-muted)] mt-1 block"
                  >
                    {formatTimestamp(msg.created_at)}
                    {msg.token_usage?.total ? (
                      <span className="ml-2 font-mono-label tabular-nums">· {msg.token_usage.total} tokens</span>
                    ) : null}
                  </span>
                )}
                <SourceToggle sources={msg.sources} />
              </div>
              <div className="shrink-0 flex items-center gap-1 mt-2">
                {/* Task 5.1: 质量反馈按钮 */}
                {canFeedback && (
                  <>
                    <button
                      onClick={() => !msg.feedback && onFeedback(msg.id, "positive")}
                      disabled={!!msg.feedback}
                      aria-label="有帮助"
                      className={`inline-flex items-center gap-0.5 px-1.5 py-1
                        rounded-md text-xs transition-all cursor-pointer
                        ${msg.feedback === "positive"
                          ? "text-indigo-400 bg-indigo-500/10"
                          : "text-[var(--color-text-muted)] hover:text-indigo-400 hover:bg-indigo-500/8"
                        }
                        disabled:cursor-not-allowed
                        opacity-0 group-hover:opacity-100 focus:opacity-100
                        ${msg.feedback ? "!opacity-100" : ""}`}
                    >
                      <ThumbsUp size={12} weight={msg.feedback === "positive" ? "fill" : "regular"} aria-hidden="true" />
                    </button>
                    <button
                      onClick={() => !msg.feedback && onFeedback(msg.id, "negative")}
                      disabled={!!msg.feedback}
                      aria-label="没帮助"
                      className={`inline-flex items-center gap-0.5 px-1.5 py-1
                        rounded-md text-xs transition-all cursor-pointer
                        ${msg.feedback === "negative"
                          ? "text-red-400 bg-red-500/10"
                          : "text-[var(--color-text-muted)] hover:text-red-400 hover:bg-red-500/8"
                        }
                        disabled:cursor-not-allowed
                        opacity-0 group-hover:opacity-100 focus:opacity-100
                        ${msg.feedback ? "!opacity-100" : ""}`}
                    >
                      <ThumbsDown size={12} weight={msg.feedback === "negative" ? "fill" : "regular"} aria-hidden="true" />
                    </button>
                  </>
                )}
                {canDelete && (
                  <button
                    onClick={() => !deleting && onDelete(msg.id)}
                    disabled={deleting}
                    aria-label="删除该问答"
                    className="inline-flex items-center gap-1 px-1.5 py-1
                      rounded-md text-xs text-[var(--color-text-muted)]
                      hover:text-red-400 hover:bg-red-500/10
                      active:scale-[0.95] motion-reduce:active:scale-100
                      transition-all cursor-pointer
                      opacity-0 group-hover:opacity-100 focus:opacity-100
                      disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {deleting ? (
                      <span
                        className="inline-block w-3 h-3 rounded-full border-2 border-current border-t-transparent animate-spin"
                        aria-hidden="true"
                      />
                    ) : (
                      <Trash size={12} weight="regular" aria-hidden="true" />
                    )}
                    删除
                  </button>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── 主组件 ──────────────────────────────────────────────

export default function QAPage() {
  const { id } = useParams<{ id: string }>();
  const resumeId = Number(id);

  const [resume, setResume] = useState<ResumeItem | null>(null);
  const [chat, setChat] = useState<ChatMessage[]>([]);
  const [question, setQuestion] = useState("");
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState("");

  // Task 4：搜索 + 删除相关状态
  const [keyword, setKeyword] = useState("");
  const [debouncedKeyword, setDebouncedKeyword] = useState("");
  const [historyLoading, setHistoryLoading] = useState(false);
  const [clearConfirmOpen, setClearConfirmOpen] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [deletingId, setDeletingId] = useState<number | string | null>(null);

  // Task 2.3：RAG 模式切换。默认 "stream"（传统流式），可切到 "agentic"（完整 Agentic RAG 图）
  const [qaMode, setQaMode] = useState<QAMode>("stream");

  // Token 限额状态
  const [quota, setQuota] = useState<QuotaResponse | null>(null);

  const chatEndRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<(() => void) | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // 加载历史（封装成函数，便于搜索时复用）
  const loadHistory = useCallback(
    async (kw: string) => {
      setHistoryLoading(true);
      setError("");
      try {
        const data = await getHistory(resumeId, 20, 0, kw || undefined);
        const historyItems: ChatMessage[] = data.items.map((it) => ({
          id: it.id,
          question: it.question,
          answer: it.answer,
          sources: it.sources,
          streaming: false,
          created_at: it.created_at,
          token_usage: it.token_usage,
        }));
        // 保留正在流式输出的消息，避免搜索时把刚发出的问题冲掉
        // 按 id 升序排列（id 自增，等价于时间正序），确保旧在上、新在下
        historyItems.sort((a, b) => Number(a.id) - Number(b.id));
        setChat((prev) => {
          const streamingMsgs = prev.filter((m) => m.streaming);
          return [...streamingMsgs, ...historyItems];
        });
      } catch (e) {
        setError(e instanceof Error ? e.message : "加载历史失败");
      } finally {
        setHistoryLoading(false);
      }
    },
    [resumeId]
  );

  // 加载简历元信息
  useEffect(() => {
    listResumes().then((data) => {
      const r = data.items.find((item) => item.id === resumeId);
      if (r) setResume(r);
    });
  }, [resumeId]);

  // 加载 token 限额
  useEffect(() => {
    getQuota().then(setQuota).catch(() => {});
  }, []);

  // 监听 WebSocket 触发的额度刷新事件（后台分析完成/额度不足时）
  useEffect(() => {
    const handleQuotaRefresh = () => {
      getQuota().then(setQuota).catch(() => {});
    };
    window.addEventListener("quota:refresh", handleQuotaRefresh);
    return () => window.removeEventListener("quota:refresh", handleQuotaRefresh);
  }, []);

  // 防抖 keyword → debouncedKeyword（300ms）
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      setDebouncedKeyword(keyword);
    }, 300);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [keyword]);

  // debouncedKeyword 变化时重新加载历史（含初次加载）
  useEffect(() => {
    loadHistory(debouncedKeyword);
  }, [debouncedKeyword, loadHistory]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chat]);

  useEffect(() => {
    return () => abortRef.current?.();
  }, []);

  const handleAsk = useCallback(
    (e: FormEvent) => {
      e.preventDefault();
      const q = question.trim();
      if (!q || asking) return;

      setQuestion("");
      setError("");
      setAsking(true);

      const tempId = `streaming-${Date.now()}`;
      const newMsg: ChatMessage = {
        id: tempId,
        question: q,
        answer: "",
        sources: [],
        streaming: true,
      };
      setChat((prev) => [...prev, newMsg]);

      abortRef.current = askQuestionStream(
        resumeId,
        q,
        (event: SSEEvent) => {
          if (event.type === "reset") {
            // 流式降级时，后端通知客户端丢弃已收到的部分 token
            setChat((prev) =>
              prev.map((m) =>
                m.id === tempId ? { ...m, answer: "" } : m
              )
            );
          } else if (event.type === "token" && event.content) {
            setChat((prev) =>
              prev.map((m) =>
                m.id === tempId
                  ? { ...m, answer: m.answer + event.content }
                  : m
              )
            );
          } else if (event.type === "done") {
            setChat((prev) =>
              prev.map((m) =>
                m.id === tempId
                  ? {
                      ...m,
                      id: event.qa_id ?? tempId,
                      sources: event.sources ?? [],
                      streaming: false,
                      token_usage: event.token_usage,
                    }
                  : m
              )
            );
            setAsking(false);
            window.dispatchEvent(new CustomEvent("quota:refresh"));
          } else if (event.type === "error") {
            setChat((prev) =>
              prev.map((m) =>
                m.id === tempId
                  ? {
                      ...m,
                      answer: event.message ?? "生成失败",
                      streaming: false,
                    }
                  : m
              )
            );
            setAsking(false);
          }
        },
        (err: Error) => {
          setError(err.message);
          setChat((prev) =>
            prev.map((m) =>
              m.id === tempId
                ? { ...m, answer: "生成失败，请重试", streaming: false }
                : m
            )
          );
          setAsking(false);
        },
        // C2：兜底。即使后端中途断开、没发 done 事件，也复位 asking 并结束该条流式消息。
        () => {
          setAsking(false);
          setChat((prev) =>
            prev.map((m) =>
              m.id === tempId ? { ...m, streaming: false } : m
            )
          );
        },
        // Task 2.3：透传 RAG 模式。stream=普通流式，agentic=完整 Agentic RAG 图
        { mode: qaMode }
      );
    },
    [question, asking, resumeId, qaMode]
  );

  const handleCancel = () => {
    abortRef.current?.();
    setAsking(false);
    setChat((prev) =>
      prev.map((m) =>
        m.streaming
          ? { ...m, answer: m.answer || "已取消", streaming: false }
          : m
      )
    );
    inputRef.current?.focus();
  };

  // Task 4：清空整份简历的问答历史
  const handleConfirmClear = async () => {
    setClearing(true);
    setError("");
    try {
      await clearHistory(resumeId);
      setChat([]);
      setKeyword("");
      setDebouncedKeyword("");
      setClearConfirmOpen(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "清空失败");
    } finally {
      setClearing(false);
    }
  };

  // Task 4：删单条问答
  const handleDeleteMessage = async (msgId: number | string) => {
    if (typeof msgId !== "number") return;
    setDeletingId(msgId);
    setError("");
    try {
      await deleteQa(msgId);
      setChat((prev) => prev.filter((m) => m.id !== msgId));
    } catch (e) {
      setError(e instanceof Error ? e.message : "删除失败");
    } finally {
      setDeletingId(null);
    }
  };

  // Task 5.1：预设提问 — 直接发送预设问题
  const handlePresetAsk = useCallback(
    (q: string) => {
      if (asking || !q.trim()) return;
      setError("");
      setAsking(true);

      const tempId = `streaming-${Date.now()}`;
      const newMsg: ChatMessage = {
        id: tempId,
        question: q.trim(),
        answer: "",
        sources: [],
        streaming: true,
      };
      setChat((prev) => [...prev, newMsg]);

      abortRef.current = askQuestionStream(
        resumeId,
        q.trim(),
        (event: SSEEvent) => {
          if (event.type === "reset") {
            setChat((prev) =>
              prev.map((m) =>
                m.id === tempId ? { ...m, answer: "" } : m
              )
            );
          } else if (event.type === "token" && event.content) {
            setChat((prev) =>
              prev.map((m) =>
                m.id === tempId
                  ? { ...m, answer: m.answer + event.content }
                  : m
              )
            );
          } else if (event.type === "done") {
            setChat((prev) =>
              prev.map((m) =>
                m.id === tempId
                  ? {
                      ...m,
                      id: event.qa_id ?? tempId,
                      sources: event.sources ?? [],
                      streaming: false,
                      token_usage: event.token_usage,
                    }
                  : m
              )
            );
            setAsking(false);
            window.dispatchEvent(new CustomEvent("quota:refresh"));
          } else if (event.type === "error") {
            // 捕获 quota_exceeded 错误，刷新额度状态
            if (event.code === "quota_exceeded") {
              getQuota().then(setQuota).catch(() => {});
            }
            setChat((prev) =>
              prev.map((m) =>
                m.id === tempId
                  ? {
                      ...m,
                      answer: event.message ?? "生成失败",
                      streaming: false,
                    }
                  : m
              )
            );
            setAsking(false);
          }
        },
        (err: Error) => {
          setError(err.message);
          setChat((prev) =>
            prev.map((m) =>
              m.id === tempId
                ? { ...m, answer: "生成失败，请重试", streaming: false }
                : m
            )
          );
          setAsking(false);
        },
        () => {
          setAsking(false);
          setChat((prev) =>
            prev.map((m) =>
              m.id === tempId ? { ...m, streaming: false } : m
            )
          );
        },
        { mode: qaMode }
      );
    },
    [asking, resumeId, qaMode]
  );

  // Task 5.1：质量反馈
  const handleFeedback = useCallback(
    async (msgId: number | string, rating: "positive" | "negative") => {
      if (typeof msgId !== "number") return;
      // 乐观更新 UI
      setChat((prev) =>
        prev.map((m) =>
          m.id === msgId ? { ...m, feedback: rating } : m
        )
      );
      try {
        await submitFeedback(msgId, rating);
      } catch {
        // 失败时回滚反馈状态
        setChat((prev) =>
          prev.map((m) =>
            m.id === msgId ? { ...m, feedback: null } : m
          )
        );
      }
    },
    []
  );

  return (
    <div className="min-h-screen bg-[var(--color-bg)] flex flex-col">
      {/* ── 顶栏 ── */}
      <div className="sticky top-[49px] z-30 bg-[var(--color-bg)] px-6 py-4 border-b border-[var(--color-border)] shrink-0">
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div className="min-w-0 flex-1">
            <h2 className="text-base font-semibold text-[var(--color-text)] truncate">
              {resume?.filename ?? "加载中..."}
            </h2>
            {resume && (
              <p className="text-xs text-[var(--color-text-muted)] mt-0.5">
                <span className="tabular-nums">{resume.chunk_count}</span> 个分块
              </p>
            )}
          </div>

          {/* Task 2.3：RAG 模式 Segmented Control */}
          <div
            role="radiogroup"
            aria-label="RAG 模式"
            className="shrink-0 inline-flex items-center p-0.5 rounded-lg
              bg-white/5 border border-[var(--color-border)]"
          >
            <label
              className={`px-3 py-1 rounded-md text-xs font-medium cursor-pointer
                transition-all duration-150
                ${
                  qaMode === "stream"
                    ? "bg-indigo-500/20 text-indigo-300 border border-indigo-500/40"
                    : "text-[var(--color-text-muted)] hover:text-[var(--color-text-secondary)] border border-transparent"
                }`}
            >
              <input
                type="radio"
                name="qa-mode"
                value="stream"
                checked={qaMode === "stream"}
                onChange={() => setQaMode("stream")}
                disabled={asking}
                className="sr-only"
              />
              传统
            </label>
            <label
              className={`px-3 py-1 rounded-md text-xs font-medium cursor-pointer
                transition-all duration-150
                ${
                  qaMode === "agentic"
                    ? "bg-indigo-500/20 text-indigo-300 border border-indigo-500/40"
                    : "text-[var(--color-text-muted)] hover:text-[var(--color-text-secondary)] border border-transparent"
                }`}
            >
              <input
                type="radio"
                name="qa-mode"
                value="agentic"
                checked={qaMode === "agentic"}
                onChange={() => setQaMode("agentic")}
                disabled={asking}
                className="sr-only"
              />
              Agentic
            </label>
          </div>

          {/* Token 限额显示 */}
          {quota?.enabled && (
            <div className="shrink-0 px-3 py-1.5 rounded-lg text-xs
              bg-white/5 border border-[var(--color-border)]
              flex items-center gap-2">
              <span className="text-[var(--color-text-muted)]">今日额度</span>
              <span className={`font-mono tabular-nums ${
                quota.remaining < quota.limit * 0.1
                  ? "text-red-400"
                  : quota.remaining < quota.limit * 0.3
                  ? "text-yellow-400"
                  : "text-indigo-400"
              }`}>
                {quota.used}/{quota.limit}
              </span>
              {quota.remaining < quota.limit * 0.1 && (
                <span className="text-red-400 text-[10px]">额度不足</span>
              )}
            </div>
          )}

          {/* 搜索框 */}
          <div className="relative shrink-0">
            <MagnifyingGlass
              size={14}
              weight="bold"
              aria-hidden="true"
              className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--color-text-muted)] pointer-events-none"
            />
            <input
              type="text"
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
              placeholder="搜索问答"
              disabled={asking}
              className="w-40 sm:w-56 pl-8 pr-8 py-1.5 rounded-lg text-xs text-[var(--color-text)]
                bg-white/5 border border-[var(--color-border)]
                placeholder:text-[var(--color-text-muted)]
                focus:outline-none focus:ring-2 focus:ring-indigo-500/40
                focus:border-indigo-500/50
                disabled:opacity-50 transition-all duration-200"
            />
            {keyword && (
              <button
                onClick={() => setKeyword("")}
                aria-label="清除搜索"
                className="absolute right-2 top-1/2 -translate-y-1/2 p-0.5 rounded
                  text-[var(--color-text-muted)] hover:text-[var(--color-text)] hover:bg-white/8
                  active:scale-[0.95] motion-reduce:active:scale-100
                  transition-all cursor-pointer"
              >
                <X size={12} weight="bold" aria-hidden="true" />
              </button>
            )}
          </div>

          {/* 清除历史 */}
          <button
            onClick={() => setClearConfirmOpen(true)}
            disabled={chat.length === 0 || clearing || asking}
            className="shrink-0 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg
              text-xs font-medium border border-[var(--color-border)] text-[var(--color-text-secondary)]
              hover:text-red-400 hover:border-red-500/30 hover:bg-red-500/8
              active:scale-[0.98] motion-reduce:active:scale-100
              transition-all cursor-pointer
              disabled:opacity-40 disabled:cursor-not-allowed"
          >
            <Trash size={14} weight="regular" aria-hidden="true" />
            清除历史
          </button>

          <Link
            to="/"
            className="shrink-0 text-xs text-[var(--color-text-muted)] hover:text-indigo-400 transition-colors"
          >
            ← 返回列表
          </Link>
        </div>
      </div>

      {/* ── 聊天区 ── */}
      <div className="flex-1 overflow-y-auto px-4 sm:px-6 py-6">
        <div className="max-w-3xl mx-auto">
          {historyLoading && chat.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16">
              <span
                className="inline-block w-6 h-6 rounded-full border-2 border-indigo-400 border-t-transparent animate-spin"
                aria-hidden="true"
              />
              <p className="text-xs text-[var(--color-text-muted)] mt-3">加载历史中...</p>
            </div>
          ) : chat.length === 0 ? (
            <EmptyChat searching={debouncedKeyword.length > 0} asking={asking} onPresetClick={handlePresetAsk} />
          ) : (
            chat.map((msg) => (
              <MessageBubble
                key={String(msg.id)}
                msg={msg}
                deleting={deletingId === msg.id}
                onDelete={handleDeleteMessage}
                onFeedback={handleFeedback}
              />
            ))
          )}

          {/* 错误提示 */}
          {error && (
            <div className="max-w-3xl mx-auto mb-4 p-3 rounded-xl
              bg-red-500/10 border border-red-500/20 text-red-400 text-sm animate-shake">
              {error}
            </div>
          )}

          <div ref={chatEndRef} />
        </div>
      </div>

      {/* ── 输入区 ── */}
      <div className="shrink-0 px-4 sm:px-6 py-4 border-t border-[var(--color-border)]">
        <form
          onSubmit={handleAsk}
          className="max-w-3xl mx-auto flex gap-3 items-center"
        >
          <input
            ref={inputRef}
            type="text"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="输入问题，例如：这份简历的亮点是什么？"
            disabled={asking}
            className="flex-1 px-5 py-3 rounded-2xl text-sm text-[var(--color-text)]
              bg-white/5 border border-[var(--color-border)]
              placeholder:text-[var(--color-text-muted)]
              focus:outline-none focus:ring-2 focus:ring-indigo-500/40
              focus:border-indigo-500/50 focus:shadow-[0_0_15px_rgba(99,102,241,0.15)]
              disabled:opacity-50 transition-all duration-200"
          />
          {asking ? (
            <button
              type="button"
              onClick={handleCancel}
              className="px-5 py-3 rounded-2xl text-sm font-medium
                border border-[var(--color-border)] text-[var(--color-text-secondary)]
                hover:text-red-400 hover:border-red-500/30 hover:bg-red-500/8
                transition-all duration-200 cursor-pointer shrink-0"
            >
              ■ 取消
            </button>
          ) : (
            <button
              type="submit"
              disabled={!question.trim()}
              className="px-6 py-3 rounded-2xl text-sm font-semibold text-white
                bg-linear-to-br from-indigo-500 to-purple-600
                hover:brightness-110 hover:shadow-lg hover:shadow-indigo-500/25
                active:scale-[0.98] disabled:opacity-40 disabled:cursor-not-allowed
                transition-all duration-200 cursor-pointer shrink-0"
            >
              发送
            </button>
          )}
        </form>
      </div>

      {/* ── 清除历史确认弹窗 ── */}
      <ConfirmDialog
        open={clearConfirmOpen}
        title="清空问答历史？"
        description={`将删除本简历下所有问答记录，共 ${chat.length} 条，操作不可恢复。`}
        confirmText="清空"
        cancelText="取消"
        danger
        loading={clearing}
        onConfirm={handleConfirmClear}
        onCancel={() => setClearConfirmOpen(false)}
      />
    </div>
  );
}
