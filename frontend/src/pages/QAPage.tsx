import { useEffect, useState, useRef, useCallback, type FormEvent } from "react";
import { useParams, Link } from "react-router-dom";
import { ChatCircleDots, MagnifyingGlass, Trash, X } from "@phosphor-icons/react";
import {
  askQuestionStream,
  getHistory,
  clearHistory,
  deleteQa,
  type SSEEvent,
} from "../api/qa";
import { listResumes, type ResumeItem } from "../api/resumes";
import ConfirmDialog from "../components/ConfirmDialog";

interface ChatMessage {
  id: number | string;
  question: string;
  answer: string;
  sources: string[];
  streaming: boolean;
}

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
        来源 ({sources.length}) {expanded ? "▲" : "▼"}
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

// ── 空状态 ──────────────────────────────────────────────

function EmptyChat({ searching }: { searching: boolean }) {
  return (
    <div className="flex-1 flex flex-col items-center justify-center py-16">
      <div className="w-16 h-16 rounded-2xl bg-indigo-500/10 border border-indigo-500/15
        flex items-center justify-center text-indigo-400 mb-5">
        <ChatCircleDots size={28} weight="duotone" aria-hidden="true" />
      </div>
      <p className="text-base text-[var(--color-text-secondary)] mb-1.5">
        {searching ? "没有匹配的问答" : "开始提问"}
      </p>
      <p className="text-sm text-[var(--color-text-muted)]">
        {searching
          ? "换个关键词试试"
          : "例如：这份简历的亮点是什么？适合什么岗位？"}
      </p>
    </div>
  );
}

// ── 消息气泡 ────────────────────────────────────────────

interface MessageBubbleProps {
  msg: ChatMessage;
  deleting: boolean;
  onDelete: (id: number | string) => void;
}

function MessageBubble({ msg, deleting, onDelete }: MessageBubbleProps) {
  // 流式消息（id 仍是字符串 tempId）不显示删除按钮
  const canDelete = !msg.streaming && typeof msg.id === "number";
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
              <span className="text-[var(--color-text-secondary)] whitespace-pre-wrap">
                {msg.answer}
                {msg.streaming && <StreamingCursor />}
              </span>
            )}
          </div>

          {/* 来源引用 + 单条删除按钮 */}
          {!msg.streaming && (
            <div className="flex items-start justify-between gap-2">
              <div className="flex-1 min-w-0">
                <SourceToggle sources={msg.sources} />
              </div>
              {canDelete && (
                <button
                  onClick={() => !deleting && onDelete(msg.id)}
                  disabled={deleting}
                  aria-label="删除该问答"
                  className="shrink-0 mt-2 inline-flex items-center gap-1 px-1.5 py-1
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
        }));
        // 保留正在流式输出的消息，避免搜索时把刚发出的问题冲掉
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
                    }
                  : m
              )
            );
            setAsking(false);
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
        }
      );
    },
    [question, asking, resumeId]
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

  return (
    <div className="min-h-screen bg-[var(--color-bg)] flex flex-col">
      {/* ── 顶栏 ── */}
      <div className="px-6 py-4 border-b border-[var(--color-border)] shrink-0">
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div className="min-w-0 flex-1">
            <h2 className="text-base font-semibold text-[var(--color-text)] truncate">
              {resume?.filename ?? "加载中..."}
            </h2>
            {resume && (
              <p className="text-xs text-[var(--color-text-muted)] mt-0.5">
                {resume.chunk_count} 个分块
              </p>
            )}
          </div>

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
            <EmptyChat searching={debouncedKeyword.length > 0} />
          ) : (
            chat.map((msg) => (
              <MessageBubble
                key={String(msg.id)}
                msg={msg}
                deleting={deletingId === msg.id}
                onDelete={handleDeleteMessage}
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
