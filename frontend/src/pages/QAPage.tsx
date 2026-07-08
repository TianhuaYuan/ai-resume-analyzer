import { useEffect, useState, useRef, useCallback, type FormEvent } from "react";
import { useParams, Link } from "react-router-dom";
import { askQuestionStream, getHistory, type SSEEvent } from "../api/qa";
import { listResumes, type ResumeItem } from "../api/resumes";

interface ChatMessage {
  id: number | string;
  question: string;
  answer: string;
  sources: string[];
  streaming: boolean;
}

// ── 来源引用组件 ────────────────────────────────────────

function SourceCard({ index, text }: { index: number; text: string }) {
  return (
    <div className="p-3 rounded-xl bg-indigo-500/6 border border-indigo-500/10 text-xs text-slate-400 leading-relaxed">
      <span className="text-indigo-400 font-semibold mr-2">[{index}]</span>
      {text.length > 220 ? text.slice(0, 220) + "..." : text}
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
        className="inline-flex items-center gap-1 text-xs text-slate-500
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

function EmptyChat() {
  return (
    <div className="flex-1 flex flex-col items-center justify-center py-16">
      <div className="w-16 h-16 rounded-2xl bg-indigo-500/10 border border-indigo-500/15
        flex items-center justify-center text-3xl mb-5">
        💬
      </div>
      <p className="text-base text-slate-300 mb-1.5">开始提问</p>
      <p className="text-sm text-slate-500">
        例如：这份简历的亮点是什么？适合什么岗位？
      </p>
    </div>
  );
}

// ── 消息气泡 ────────────────────────────────────────────

function MessageBubble({ msg }: { msg: ChatMessage }) {
  return (
    <div className="animate-fade-in-up">
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
            bg-white/5 border border-white/8 backdrop-blur-sm">
            {msg.streaming && !msg.answer ? (
              <span className="text-slate-500">思考中...</span>
            ) : (
              <span className="text-slate-300 whitespace-pre-wrap">
                {msg.answer}
                {msg.streaming && <StreamingCursor />}
              </span>
            )}
          </div>

          {/* 来源引用 */}
          {!msg.streaming && <SourceToggle sources={msg.sources} />}
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
  const chatEndRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<(() => void) | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    listResumes().then((data) => {
      const r = data.items.find((item) => item.id === resumeId);
      if (r) setResume(r);
    });
    getHistory(resumeId)
      .then((data) =>
        setChat(
          data.items.map((it) => ({
            id: it.id,
            question: it.question,
            answer: it.answer,
            sources: it.sources,
            streaming: false,
          }))
        )
      )
      .catch(() => {});
  }, [resumeId]);

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
          if (event.type === "token" && event.content) {
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

  return (
    <div className="min-h-screen bg-[#0f172a] flex flex-col">
      {/* ── 顶栏 ── */}
      <div className="px-6 py-4 border-b border-white/6 flex items-center justify-between shrink-0">
        <div className="min-w-0">
          <h2 className="text-base font-semibold text-slate-100 truncate">
            {resume?.filename ?? "加载中..."}
          </h2>
          {resume && (
            <p className="text-xs text-slate-500 mt-0.5">
              {resume.chunk_count} 个分块
            </p>
          )}
        </div>
        <Link
          to="/"
          className="text-xs text-slate-500 hover:text-indigo-400 transition-colors shrink-0 ml-4"
        >
          ← 返回列表
        </Link>
      </div>

      {/* ── 聊天区 ── */}
      <div className="flex-1 overflow-y-auto px-4 sm:px-6 py-6">
        <div className="max-w-3xl mx-auto">
          {chat.length === 0 ? (
            <EmptyChat />
          ) : (
            chat.map((msg) => <MessageBubble key={String(msg.id)} msg={msg} />)
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
      <div className="shrink-0 px-4 sm:px-6 py-4 border-t border-white/6">
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
            className="flex-1 px-5 py-3 rounded-2xl text-sm text-slate-200
              bg-white/5 border border-white/10
              placeholder:text-slate-500
              focus:outline-none focus:ring-2 focus:ring-indigo-500/40
              focus:border-indigo-500/50 focus:shadow-[0_0_15px_rgba(99,102,241,0.15)]
              disabled:opacity-50 transition-all duration-200"
          />
          {asking ? (
            <button
              type="button"
              onClick={handleCancel}
              className="px-5 py-3 rounded-2xl text-sm font-medium
                border border-white/10 text-slate-400
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
    </div>
  );
}
