import { useEffect, useState, useRef, useCallback, memo, type FormEvent } from "react";
import { useParams } from "react-router-dom";
import {
  ChatCircleDots,
  MagnifyingGlass,
  Trash,
  ThumbsUp,
  ThumbsDown,
  X,
  Upload,
  Columns,
  FileText,
  Target,
  PencilSimple,
  Microphone,
  Translate,
  Swap,
  Plus,
  CaretDown,
} from "@phosphor-icons/react";
import {
  askAgentStream,
  getHistory,
  clearHistory,
  deleteQa,
  submitFeedback,
  getQuota,
  getConversations,
  createConversation,
  renameConversation,
  deleteConversation,
  type AgentSSEEvent,
  type AgentStep,
  type QuotaResponse,
  type ConversationItem,
} from "../api/qa";
import { listResumes, uploadResume, type ResumeItem } from "../api/resumes";
import { fetchPreviewHtml } from "../api/builder";
import ConfirmDialog from "../components/ConfirmDialog";
import { CompareSelectDialog } from "../components/CompareSelectDialog";
import MarkdownRenderer from "../components/MarkdownRenderer";
import AgentProcessPanel from "../components/AgentProcessPanel";

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
  /** T18: Agent 推理步骤 */
  agent_steps?: AgentStep[];
}

// T19: 预设提问（3 个）
const PRESET_QUESTIONS = [
  "这份简历的亮点是什么？",
  "适合什么岗位？",
  "技能匹配度如何？",
];

// T19: 功能引导卡（6 个）
const GUIDE_CARDS = [
  { icon: FileText, label: "诊断简历", question: "请全面诊断这份简历的优点和不足" },
  { icon: Target, label: "匹配 JD", question: "__JD__" }, // 特殊标记：弹粘贴框
  { icon: PencilSimple, label: "改写段落", question: "请帮我改写简历中较弱的部分" },
  { icon: Microphone, label: "模拟面试", question: "请根据这份简历模拟一场面试" },
  { icon: Translate, label: "翻译简历", question: "请将这份简历翻译为英文" },
  { icon: Swap, label: "对比简历", question: "__COMPARE__" }, // 特殊标记：弹勾选
] as const;

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

function EmptyState({
  searching,
  asking,
  onPresetClick,
  onGuideClick,
  onUploadClick,
}: {
  searching: boolean;
  asking: boolean;
  onPresetClick: (q: string) => void;
  onGuideClick: (card: { label: string; question: string }) => void;
  onUploadClick: () => void;
}) {
  if (searching) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center py-16">
        <div className="w-16 h-16 rounded-2xl bg-indigo-500/10 border border-indigo-500/15
          flex items-center justify-center text-indigo-400 mb-5">
          <ChatCircleDots size={28} weight="duotone" aria-hidden="true" />
        </div>
        <p className="text-base text-[var(--color-text-secondary)] mb-1.5">没有匹配的问答</p>
        <p className="text-sm text-[var(--color-text-muted)]">换个关键词试试</p>
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col items-center justify-center py-10">
      <div className="w-16 h-16 rounded-2xl bg-indigo-500/10 border border-indigo-500/15
        flex items-center justify-center text-indigo-400 mb-5">
        <ChatCircleDots size={28} weight="duotone" aria-hidden="true" />
      </div>
      <p className="text-base text-[var(--color-text-secondary)] mb-1.5">开始提问</p>
      <p className="text-sm text-[var(--color-text-muted)] mb-5">AI Agent 为你全方位分析简历</p>

      {/* 3 问答预设 */}
      <div className="flex flex-wrap justify-center gap-2 mb-6">
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

      {/* 6 功能引导卡 */}
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 max-w-lg w-full mb-6">
        {GUIDE_CARDS.map((card) => {
          const Icon = card.icon;
          return (
            <button
              key={card.label}
              onClick={() => onGuideClick(card)}
              disabled={asking}
              className="flex flex-col items-center gap-2 p-4 rounded-xl
                bg-white/5 border border-[var(--color-border)]
                hover:border-indigo-500/40 hover:bg-indigo-500/8
                hover:text-indigo-300
                active:scale-[0.97] motion-reduce:active:scale-100
                transition-all cursor-pointer
                disabled:opacity-40 disabled:cursor-not-allowed"
              aria-label={card.label}
            >
              <Icon size={20} weight="duotone" className="text-indigo-400" aria-hidden="true" />
              <span className="text-xs font-medium text-[var(--color-text-secondary)]">{card.label}</span>
            </button>
          );
        })}
      </div>

      {/* 上传入口 */}
      <button
        onClick={onUploadClick}
        disabled={asking}
        className="inline-flex items-center gap-2 px-4 py-2 rounded-xl text-xs
          text-[var(--color-text-muted)] border border-dashed border-[var(--color-border)]
          hover:text-indigo-400 hover:border-indigo-500/40
          active:scale-[0.97] motion-reduce:active:scale-100
          transition-all cursor-pointer
          disabled:opacity-40 disabled:cursor-not-allowed"
        aria-label="上传新简历"
      >
        <Upload size={14} weight="regular" aria-hidden="true" />
        上传新简历
      </button>
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

const MessageBubble = memo(function MessageBubble({ msg, deleting, onDelete, onFeedback }: MessageBubbleProps) {
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
            {/* T18: Agent 推理过程面板（#11: streaming 开始即显示占位，用户立即看到反馈） */}
            {msg.streaming || (msg.agent_steps && msg.agent_steps.length > 0) ? (
              <AgentProcessPanel steps={msg.agent_steps ?? []} streaming={msg.streaming} />
            ) : null}
            {msg.streaming && !msg.answer && !(msg.agent_steps && msg.agent_steps.length > 0) ? (
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
});

// ── 主组件 ──────────────────────────────────────────────

export default function QAPage() {
  const { id } = useParams<{ id: string }>();
  const resumeId = Number(id);

  const [resume, setResume] = useState<ResumeItem | null>(null);
  const [chat, setChat] = useState<ChatMessage[]>([]);
  const [question, setQuestion] = useState("");
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState("");

  // 对话会话状态
  const [conversations, setConversations] = useState<ConversationItem[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<number | null>(null);
  const [conversationMenuOpen, setConversationMenuOpen] = useState(false);
  const [conversationLoading, setConversationLoading] = useState(true);
  const [renameOpen, setRenameOpen] = useState(false);
  const [renameValue, setRenameValue] = useState("");
  const [renameTargetId, setRenameTargetId] = useState<number | null>(null);
  const [deleteConvOpen, setDeleteConvOpen] = useState(false);
  const [deleteConvTargetId, setDeleteConvTargetId] = useState<number | null>(null);
  const [deletingConv, setDeletingConv] = useState(false);
  const [creatingConv, setCreatingConv] = useState(false);

  // Task 4：搜索 + 删除相关状态
  const [keyword, setKeyword] = useState("");
  const [debouncedKeyword, setDebouncedKeyword] = useState("");
  const [historyLoading, setHistoryLoading] = useState(false);
  const [clearConfirmOpen, setClearConfirmOpen] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [deletingId, setDeletingId] = useState<number | string | null>(null);

  // T19: 对比弹窗 + JD 输入 + 上传 + 分屏
  const [compareOpen, setCompareOpen] = useState(false);
  const [compareIds, setCompareIds] = useState<number[]>([]);
  const [jdOpen, setJdOpen] = useState(false);
  const [jdText, setJdText] = useState("");
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState("");
  const [splitOpen, setSplitOpen] = useState(false);
  // T19: 分屏预览 HTML（fetch 带 Authorization header → srcDoc，避免 iframe src 无法带 header 而 401）
  const [splitHtml, setSplitHtml] = useState("");
  const [splitLoading, setSplitLoading] = useState(false);
  // agent 改写类工具写库后递增，触发分屏预览重取最新模块
  const [splitRefreshKey, setSplitRefreshKey] = useState(0);

  // 打开分屏时加载预览 HTML
  useEffect(() => {
    if (!splitOpen) return;
    let cancelled = false;
    setSplitLoading(true);
    fetchPreviewHtml(resumeId)
      .then((html) => { if (!cancelled) setSplitHtml(html); })
      .catch(() => { if (!cancelled) setSplitHtml(""); })
      .finally(() => { if (!cancelled) setSplitLoading(false); });
    return () => { cancelled = true; };
  }, [splitOpen, resumeId, splitRefreshKey]);

  const fileInputRef = useRef<HTMLInputElement>(null);

  // Token 限额状态
  const [quota, setQuota] = useState<QuotaResponse | null>(null);

  const chatEndRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<(() => void) | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // 加载历史（封装成函数，便于搜索时复用）。conversationId 为空则加载该简历全部历史。
  const loadHistory = useCallback(
    async (kw: string, conversationId: number | null) => {
      setHistoryLoading(true);
      setError("");
      try {
        const data = await getHistory(
          resumeId, 20, 0, kw || undefined,
          conversationId ?? undefined,
        );
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

  // 首次加载简历下的对话列表：有则选中最近活跃的，无则自动创建一个默认对话
  useEffect(() => {
    let cancelled = false;
    setConversationLoading(true);
    getConversations(resumeId)
      .then(async (list) => {
        if (cancelled) return;
        if (list.length > 0) {
          setConversations(list);
          // 默认选中最近活跃的对话（列表已按 updated_at 降序）
          setActiveConversationId(list[0].id);
          return;
        }
        // 无任何对话 → 自动创建一个
        const conv = await createConversation(resumeId);
        if (cancelled) return;
        setConversations([conv]);
        setActiveConversationId(conv.id);
      })
      .catch(() => {
        if (!cancelled) setError("加载对话列表失败");
      })
      .finally(() => {
        if (!cancelled) setConversationLoading(false);
      });
    return () => { cancelled = true; };
  }, [resumeId]);

  // debouncedKeyword / activeConversationId 变化时重新加载历史（含初次加载）
  useEffect(() => {
    loadHistory(debouncedKeyword, activeConversationId);
  }, [debouncedKeyword, activeConversationId, loadHistory]);

  // 滚动到底部：仅在新消息添加或流式回答增长时触发，避免每个 token 都 smooth scroll
  const prevChatLenRef = useRef(0);
  const prevLastAnswerRef = useRef("");
  useEffect(() => {
    const len = chat.length;
    const lastMsg = chat[len - 1];
    const lastAnswer = lastMsg?.answer ?? "";
    // 新消息加入 OR 流式回答内容增长 → 滚动
    if (len > prevChatLenRef.current ||
        (lastMsg?.streaming && lastAnswer !== prevLastAnswerRef.current)) {
      chatEndRef.current?.scrollIntoView({ behavior: "auto" });
    }
    prevChatLenRef.current = len;
    prevLastAnswerRef.current = lastAnswer;
  }, [chat]);

  useEffect(() => {
    return () => abortRef.current?.();
  }, []);

  // T19: 统一走 Agent 模式（去模式切换），支持 compare_ids
  const sendQuestion = useCallback(
    (q: string) => {
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

      abortRef.current = askAgentStream(
        resumeId,
        q,
        (event: AgentSSEEvent) => {
          if (event.type === "agent_start") {
            setChat((prev) =>
              prev.map((m) =>
                m.id === tempId ? { ...m, agent_steps: [] } : m
              )
            );
          } else if (event.type === "agent_thought") {
            // Spec A#7: LLM 推理过程内容，作为推理步骤展示
            setChat((prev) =>
              prev.map((m) =>
                m.id === tempId
                  ? {
                      ...m,
                      agent_steps: [
                        ...(m.agent_steps ?? []),
                        {
                          type: "agent_thought" as const,
                          name: "思考",
                          detail: event.content,
                        },
                      ],
                    }
                  : m
              )
            );
          } else if (event.type === "tool_call") {
            setChat((prev) =>
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
                  : m
              )
            );
          } else if (event.type === "tool_result") {
            setChat((prev) =>
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
                  : m
              )
            );
          } else if (event.type === "tool_error") {
            setChat((prev) =>
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
                  : m
              )
            );
          } else if (event.type === "agent_done") {
            setChat((prev) =>
              prev.map((m) =>
                m.id === tempId
                  ? {
                      ...m,
                      id: event.qa_id ?? tempId,
                      answer: event.answer ?? "",
                      streaming: false,
                      token_usage: event.token_usage
                        ? {
                            total:
                              event.token_usage.prompt_tokens +
                              event.token_usage.completion_tokens,
                            prompt: event.token_usage.prompt_tokens,
                            completion: event.token_usage.completion_tokens,
                          }
                        : undefined,
                      // Spec: process_trace 是紧凑摘要（rounds/tool_sequence/duration_ms），
                      // 不是 AgentStep[]，不能覆盖 agent_steps
                      // agent_steps 保留实时累积的步骤
                      sources: event.sources?.map((s) => s.text) ?? [],
                    }
                  : m
              )
            );
            setAsking(false);
            window.dispatchEvent(new CustomEvent("quota:refresh"));
            // 问答完成 → 递增当前会话的消息数
            if (activeConversationId != null && event.qa_id != null) {
              setConversations((prev) =>
                prev.map((c) =>
                  c.id === activeConversationId
                    ? { ...c, message_count: c.message_count + 1 }
                    : c
                )
              );
            }
            // QA 改写类工具（rewrite_star/translate）写库后：刷新分屏预览 + 通知编辑页/侧栏同步
            const wroteModules = (event.process_trace?.tool_sequence ?? []).some(
              (t) => t === "rewrite_star" || t === "translate",
            );
            if (wroteModules) {
              setSplitRefreshKey((k) => k + 1);
              window.dispatchEvent(new Event("resume:modules-refresh"));
              window.dispatchEvent(new Event("resume:list-refresh"));
            }
          } else if (event.type === "quota_exceeded") {
            setChat((prev) =>
              prev.map((m) =>
                m.id === tempId
                  ? {
                      ...m,
                      answer: event.message ?? "今日额度已用完",
                      streaming: false,
                    }
                  : m
              )
            );
            setAsking(false);
            getQuota().then(setQuota).catch(() => {});
          } else if (event.type === "error") {
            setChat((prev) =>
              prev.map((m) =>
                m.id === tempId
                  ? {
                      ...m,
                      answer: event.message ?? "Agent 处理失败",
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
        {
          compareIds: compareIds.length > 0 ? compareIds : undefined,
          conversationId: activeConversationId ?? undefined,
        },
      );
    },
    [resumeId, compareIds, activeConversationId]
  );

  const handleAsk = useCallback(
    (e: FormEvent) => {
      e.preventDefault();
      const q = question.trim();
      if (!q || asking) return;
      setQuestion("");
      sendQuestion(q);
    },
    [question, asking, sendQuestion]
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

  // Task 4：清空当前对话的问答历史（对话维度）
  const handleConfirmClear = async () => {
    setClearing(true);
    setError("");
    try {
      await clearHistory(resumeId, activeConversationId ?? undefined);
      setChat([]);
      setKeyword("");
      setDebouncedKeyword("");
      setClearConfirmOpen(false);
      // 刷新对话消息数
      if (activeConversationId != null) {
        setConversations((prev) =>
          prev.map((c) =>
            c.id === activeConversationId ? { ...c, message_count: 0 } : c
          )
        );
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "清空失败");
    } finally {
      setClearing(false);
    }
  };

  // Task 4：删单条问答
  const handleDeleteMessage = useCallback(async (msgId: number | string) => {
    if (typeof msgId !== "number") return;
    setDeletingId(msgId);
    setError("");
    try {
      await deleteQa(msgId);
      setChat((prev) => prev.filter((m) => m.id !== msgId));
      // 递减当前会话消息数
      if (activeConversationId != null) {
        setConversations((prev) =>
          prev.map((c) =>
            c.id === activeConversationId
              ? { ...c, message_count: Math.max(0, c.message_count - 1) }
              : c
          )
        );
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "删除失败");
    } finally {
      setDeletingId(null);
    }
  }, [activeConversationId]);

  // Task 5.1：预设提问 — 直接发送预设问题
  const handlePresetAsk = useCallback(
    (q: string) => {
      if (asking || !q.trim()) return;
      sendQuestion(q.trim());
    },
    [asking, sendQuestion]
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

  // ── 对话会话操作 ──────────────────────────────────────────

  // 新建对话
  const handleCreateConversation = async () => {
    if (creatingConv) return;
    setCreatingConv(true);
    setError("");
    try {
      const conv = await createConversation(resumeId);
      setConversations((prev) => [conv, ...prev]);
      setActiveConversationId(conv.id);
      setChat([]);
      setKeyword("");
      setDebouncedKeyword("");
      setConversationMenuOpen(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "新建对话失败");
    } finally {
      setCreatingConv(false);
    }
  };

  // 切换对话
  const handleSwitchConversation = (convId: number) => {
    if (convId === activeConversationId) return;
    setActiveConversationId(convId);
    setChat([]);
    setKeyword("");
    setDebouncedKeyword("");
    setConversationMenuOpen(false);
  };

  // 打开重命名弹窗
  const handleRenameOpen = (convId: number) => {
    const conv = conversations.find((c) => c.id === convId);
    setRenameTargetId(convId);
    setRenameValue(conv?.title ?? "");
    setRenameOpen(true);
    setConversationMenuOpen(false);
  };

  // 确认重命名
  const handleRenameConfirm = async () => {
    const title = renameValue.trim();
    if (!title || renameTargetId == null) return;
    try {
      const updated = await renameConversation(renameTargetId, title);
      setConversations((prev) =>
        prev.map((c) => (c.id === updated.id ? updated : c))
      );
      setRenameOpen(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "重命名失败");
    }
  };

  // 打开删除确认
  const handleDeleteConvOpen = (convId: number) => {
    setDeleteConvTargetId(convId);
    setDeleteConvOpen(true);
    setConversationMenuOpen(false);
  };

  // 确认删除对话
  const handleDeleteConvConfirm = async () => {
    if (deleteConvTargetId == null) return;
    setDeletingConv(true);
    setError("");
    try {
      await deleteConversation(deleteConvTargetId);
      const remaining = conversations.filter((c) => c.id !== deleteConvTargetId);
      setConversations(remaining);
      if (deleteConvTargetId === activeConversationId) {
        // 当前对话被删 → 切到剩余对话（最近活跃）或清空
        if (remaining.length > 0) {
          setActiveConversationId(remaining[0].id);
        } else {
          setActiveConversationId(null);
        }
        setChat([]);
        setKeyword("");
        setDebouncedKeyword("");
      }
      setDeleteConvOpen(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "删除对话失败");
    } finally {
      setDeletingConv(false);
    }
  };

  // T19: 功能引导卡点击 — 根据卡片类型分流
  const handleGuideClick = useCallback(
    (card: { label: string; question: string }) => {
      if (asking) return;
      if (card.question === "__JD__") {
        setJdOpen(true);
      } else if (card.question === "__COMPARE__") {
        setCompareOpen(true);
      } else {
        sendQuestion(card.question);
      }
    },
    [asking, sendQuestion]
  );

  // T19: JD 粘贴框确认
  const handleJdConfirm = () => {
    const jd = jdText.trim();
    if (!jd) return;
    setJdOpen(false);
    sendQuestion(`请分析这份简历与以下岗位描述的匹配度：\n\n${jd}`);
    setJdText("");
  };

  // T19: 对比确认 — 设置 compareIds 并发送
  const handleCompareConfirm = (selectedIds: number[]) => {
    setCompareIds(selectedIds);
    setCompareOpen(false);
    sendQuestion("请对比我选中的简历，分析各自的优劣势");
  };

  // T19: 上传简历
  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    e.target.value = "";

    // 文件校验
    const validTypes = [
      "application/pdf",
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ];
    const ext = file.name.split(".").pop()?.toLowerCase();
    if (!validTypes.includes(file.type) && ext !== "pdf" && ext !== "docx") {
      setUploadError("仅支持 PDF / DOCX 格式");
      return;
    }
    if (file.size > 10 * 1024 * 1024) {
      setUploadError("文件大小不能超过 10MB");
      return;
    }

    setUploading(true);
    setUploadError("");
    try {
      await uploadResume(file);
      // 上传成功后刷新简历列表（让用户可以在对比中选到新简历）
      listResumes().then(() => {}).catch(() => {});
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : "上传失败");
    } finally {
      setUploading(false);
    }
  };

  return (
    <div
      className="flex-1 flex flex-col bg-[var(--color-bg)] overflow-hidden"
      onClick={() => setConversationMenuOpen(false)}
    >
      {/* ── 顶栏 ── */}
      <div className="shrink-0 z-30 bg-[var(--color-bg)] px-6 py-4 border-b border-[var(--color-border)]">
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

            {/* 对话会话选择器 */}
            {!conversationLoading && (
              <div className="relative mt-2 inline-block">
                <button
                  onClick={(e) => { e.stopPropagation(); setConversationMenuOpen((v) => !v); }}
                  className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs
                    bg-white/5 border border-[var(--color-border)]
                    text-[var(--color-text-secondary)]
                    hover:text-indigo-400 hover:border-indigo-500/30 hover:bg-indigo-500/8
                    active:scale-[0.98] motion-reduce:active:scale-100
                    transition-all cursor-pointer"
                  aria-label="切换对话"
                  aria-expanded={conversationMenuOpen}
                >
                  <span className="max-w-[180px] truncate">
                    {conversations.find((c) => c.id === activeConversationId)?.title ?? "新对话"}
                  </span>
                  <CaretDown size={12} weight="bold" aria-hidden="true" />
                </button>

                {conversationMenuOpen && (
                  <div
                    onClick={(e) => e.stopPropagation()}
                    className="absolute left-0 top-full mt-1 w-64 rounded-xl z-50
                    bg-[var(--color-bg-secondary)] border border-[var(--color-border)] shadow-2xl
                    animate-fade-in-up"
                  >
                    <div className="py-1.5">
                      {conversations.length === 0 ? (
                        <p className="px-3 py-2 text-xs text-[var(--color-text-muted)]">暂无对话</p>
                      ) : (
                        conversations.map((conv) => {
                          const active = conv.id === activeConversationId;
                          return (
                            <div
                              key={conv.id}
                              onClick={() => handleSwitchConversation(conv.id)}
                              className={`group flex items-center gap-2 px-3 py-2 mx-1 rounded-lg text-xs
                                transition-all cursor-pointer
                                ${active
                                  ? "bg-indigo-500/10 text-indigo-300"
                                  : "text-[var(--color-text-secondary)] hover:bg-white/5 hover:text-[var(--color-text)]"
                                }`}
                            >
                              <span className="flex-1 min-w-0 truncate">{conv.title}</span>
                              <span className="shrink-0 text-[10px] text-[var(--color-text-muted)] tabular-nums">
                                {conv.message_count} 条
                              </span>
                              <span
                                role="button"
                                aria-label="重命名对话"
                                onClick={(e) => { e.stopPropagation(); handleRenameOpen(conv.id); }}
                                className="shrink-0 p-1 rounded-md text-[var(--color-text-muted)]
                                  opacity-0 group-hover:opacity-100 hover:text-indigo-400 hover:bg-white/8 transition-all cursor-pointer"
                              >
                                <PencilSimple size={12} weight="regular" aria-hidden="true" />
                              </span>
                              <span
                                role="button"
                                aria-label="删除对话"
                                onClick={(e) => { e.stopPropagation(); handleDeleteConvOpen(conv.id); }}
                                className="shrink-0 p-1 rounded-md text-[var(--color-text-muted)]
                                  opacity-0 group-hover:opacity-100 hover:text-red-400 hover:bg-red-500/10 transition-all cursor-pointer"
                              >
                                <Trash size={12} weight="regular" aria-hidden="true" />
                              </span>
                            </div>
                          );
                        })
                      )}
                    </div>
                    <div className="border-t border-[var(--color-border)] px-2 py-1.5">
                      <button
                        onClick={handleCreateConversation}
                        disabled={creatingConv}
                        className="w-full inline-flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-lg
                          text-xs font-medium border border-dashed border-[var(--color-border)]
                          text-[var(--color-text-muted)]
                          hover:text-indigo-400 hover:border-indigo-500/40 hover:bg-indigo-500/8
                          active:scale-[0.98] motion-reduce:active:scale-100
                          transition-all cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        {creatingConv ? (
                          <span className="inline-block w-3 h-3 rounded-full border-2 border-current border-t-transparent animate-spin" aria-hidden="true" />
                        ) : (
                          <Plus size={12} weight="bold" aria-hidden="true" />
                        )}
                        新建对话
                      </button>
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* T19: 上传 + 分屏按钮 */}
          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            onChange={handleUpload}
            className="hidden"
          />
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading || asking}
            className="shrink-0 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg
              text-xs font-medium border border-[var(--color-border)] text-[var(--color-text-secondary)]
              hover:text-indigo-400 hover:border-indigo-500/30 hover:bg-indigo-500/8
              active:scale-[0.98] motion-reduce:active:scale-100
              transition-all cursor-pointer
              disabled:opacity-40 disabled:cursor-not-allowed"
            aria-label="上传简历"
          >
            {uploading ? (
              <span className="inline-block w-3.5 h-3.5 rounded-full border-2 border-current border-t-transparent animate-spin" aria-hidden="true" />
            ) : (
              <Upload size={14} weight="regular" aria-hidden="true" />
            )}
            上传
          </button>
          <button
            onClick={() => setSplitOpen((v) => !v)}
            className={`shrink-0 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg
              text-xs font-medium border transition-all cursor-pointer
              ${splitOpen
                ? "bg-indigo-500/20 text-indigo-300 border-indigo-500/40"
                : "border-[var(--color-border)] text-[var(--color-text-secondary)] hover:text-indigo-400 hover:border-indigo-500/30 hover:bg-indigo-500/8"
              }`}
            aria-label="切换分屏"
          >
            <Columns size={14} weight="regular" aria-hidden="true" />
            分屏
          </button>

          {/* T19: 对比已选指示器 */}
          {compareIds.length > 0 && (
            <span className="shrink-0 inline-flex items-center gap-1 px-2 py-1 rounded-md
              text-[10px] bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
              <Swap size={10} weight="bold" aria-hidden="true" />
              已选 {compareIds.length} 份对比
            </span>
          )}

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
        </div>
      </div>

      {/* ── 聊天区（T19: 支持分屏） ── */}
      <div className="flex-1 flex overflow-hidden">
        {/* 左侧：聊天主区 */}
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
              <EmptyState
                searching={debouncedKeyword.length > 0}
                asking={asking}
                onPresetClick={handlePresetAsk}
                onGuideClick={handleGuideClick}
                onUploadClick={() => fileInputRef.current?.click()}
              />
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

            {/* T19: 上传错误提示 */}
            {uploadError && (
              <div className="max-w-3xl mx-auto mb-4 p-3 rounded-xl
                bg-red-500/10 border border-red-500/20 text-red-400 text-sm
                flex items-center justify-between gap-2">
                <span>{uploadError}</span>
                <button
                  onClick={() => setUploadError("")}
                  aria-label="关闭错误提示"
                  className="shrink-0 text-red-400 hover:text-red-300 cursor-pointer"
                >
                  <X size={14} weight="bold" aria-hidden="true" />
                </button>
              </div>
            )}

            <div ref={chatEndRef} />
          </div>
        </div>

        {/* T19: 右侧 — 分屏简历预览（iframe 占位，preview 待 T27） */}
        {splitOpen && (
          <div className="w-2/5 border-l border-[var(--color-border)] bg-[var(--color-bg-secondary)] flex flex-col">
            <div className="shrink-0 px-4 py-3 border-b border-[var(--color-border)] flex items-center justify-between">
              <div className="flex items-center gap-2">
                <FileText size={14} weight="duotone" className="text-indigo-400" aria-hidden="true" />
                <span className="text-xs font-medium text-[var(--color-text-secondary)]">简历预览</span>
              </div>
              <button
                onClick={() => setSplitOpen(false)}
                aria-label="关闭分屏"
                className="p-1 rounded-md text-[var(--color-text-muted)] hover:text-[var(--color-text)] hover:bg-white/8 transition-all cursor-pointer"
              >
                <X size={14} weight="bold" aria-hidden="true" />
              </button>
            </div>
            <div className="flex-1 overflow-hidden">
              {splitLoading && (
                <div className="h-full flex items-center justify-center text-xs text-[var(--color-text-muted)]">
                  加载预览...
                </div>
              )}
              <iframe
                srcDoc={splitHtml || "<html><body style='background:#fff'></body></html>"}
                className="w-full h-full border-0"
                sandbox="allow-scripts"
                title="简历预览"
              />
            </div>
          </div>
        )}
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
        description={`将删除当前对话下的所有问答记录，共 ${chat.length} 条，操作不可恢复。`}
        confirmText="清空"
        cancelText="取消"
        danger
        loading={clearing}
        onConfirm={handleConfirmClear}
        onCancel={() => setClearConfirmOpen(false)}
      />

      {/* ── 删除对话确认 ── */}
      <ConfirmDialog
        open={deleteConvOpen}
        title="删除对话？"
        description="将删除该对话及其下所有问答记录，操作不可恢复。"
        confirmText="删除"
        cancelText="取消"
        danger
        loading={deletingConv}
        onConfirm={handleDeleteConvConfirm}
        onCancel={() => setDeleteConvOpen(false)}
      />

      {/* ── 重命名对话弹窗 ── */}
      {renameOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm motion-reduce:backdrop-blur-none"
          role="dialog"
          aria-modal="true"
          aria-label="重命名对话"
          onClick={() => setRenameOpen(false)}
        >
          <div
            className="w-full max-w-sm mx-4 p-6 rounded-2xl bg-[var(--color-bg-secondary)] border border-[var(--color-border)] shadow-2xl animate-fade-in-up motion-reduce:animate-none"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <div className="p-1.5 rounded-lg bg-indigo-500/15 text-indigo-400">
                  <PencilSimple size={18} weight="bold" aria-hidden="true" />
                </div>
                <h3 className="text-base font-semibold text-[var(--color-text)]">
                  重命名对话
                </h3>
              </div>
              <button
                onClick={() => setRenameOpen(false)}
                aria-label="关闭"
                className="p-1.5 rounded-lg text-[var(--color-text-secondary)] hover:text-[var(--color-text)] hover:bg-white/8 active:scale-[0.95] motion-reduce:active:scale-100 transition-all cursor-pointer"
              >
                <X size={16} weight="bold" aria-hidden="true" />
              </button>
            </div>
            <input
              value={renameValue}
              onChange={(e) => setRenameValue(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") handleRenameConfirm(); }}
              placeholder="输入对话标题"
              maxLength={100}
              autoFocus
              className="w-full px-4 py-3 rounded-xl text-sm text-[var(--color-text)]
                bg-white/5 border border-[var(--color-border)]
                placeholder:text-[var(--color-text-muted)]
                focus:outline-none focus:ring-2 focus:ring-indigo-500/40 focus:border-indigo-500/50
                transition-all duration-200"
            />
            <div className="flex justify-end gap-2 mt-4">
              <button
                onClick={() => setRenameOpen(false)}
                className="px-3.5 py-1.5 text-sm font-medium rounded-lg border border-[var(--color-border)] text-[var(--color-text-secondary)] hover:text-[var(--color-text)] hover:bg-white/8 active:scale-[0.98] motion-reduce:active:scale-100 transition-all cursor-pointer"
              >
                取消
              </button>
              <button
                onClick={handleRenameConfirm}
                disabled={!renameValue.trim()}
                className="px-3.5 py-1.5 text-sm font-medium rounded-lg bg-linear-to-br from-indigo-500 to-purple-600 text-white active:scale-[0.98] motion-reduce:active:scale-100 transition-all cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
              >
                保存
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── T19: JD 粘贴弹窗 ── */}
      {jdOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm motion-reduce:backdrop-blur-none"
          role="dialog"
          aria-modal="true"
          aria-label="粘贴岗位描述"
          onClick={() => setJdOpen(false)}
        >
          <div
            className="w-full max-w-lg mx-4 p-6 rounded-2xl bg-[var(--color-bg-secondary)] border border-[var(--color-border)] shadow-2xl animate-fade-in-up motion-reduce:animate-none"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <div className="p-1.5 rounded-lg bg-indigo-500/15 text-indigo-400">
                  <Target size={18} weight="bold" aria-hidden="true" />
                </div>
                <h3 className="text-base font-semibold text-[var(--color-text)]">
                  粘贴岗位描述
                </h3>
              </div>
              <button
                onClick={() => setJdOpen(false)}
                aria-label="关闭"
                className="p-1.5 rounded-lg text-[var(--color-text-secondary)] hover:text-[var(--color-text)] hover:bg-white/8 active:scale-[0.95] motion-reduce:active:scale-100 transition-all cursor-pointer"
              >
                <X size={16} weight="bold" aria-hidden="true" />
              </button>
            </div>
            <textarea
              value={jdText}
              onChange={(e) => setJdText(e.target.value)}
              placeholder="粘贴目标岗位的 JD（Job Description），AI 将分析简历与岗位的匹配度..."
              rows={8}
              autoFocus
              className="w-full px-4 py-3 rounded-xl text-sm text-[var(--color-text)]
                bg-white/5 border border-[var(--color-border)]
                placeholder:text-[var(--color-text-muted)]
                focus:outline-none focus:ring-2 focus:ring-indigo-500/40 focus:border-indigo-500/50
                resize-none transition-all duration-200"
            />
            <div className="flex justify-end gap-2 mt-4">
              <button
                onClick={() => setJdOpen(false)}
                className="px-3.5 py-1.5 text-sm font-medium rounded-lg border border-[var(--color-border)] text-[var(--color-text-secondary)] hover:text-[var(--color-text)] hover:bg-white/8 active:scale-[0.98] motion-reduce:active:scale-100 transition-all cursor-pointer"
              >
                取消
              </button>
              <button
                onClick={handleJdConfirm}
                disabled={!jdText.trim()}
                className="px-3.5 py-1.5 text-sm font-medium rounded-lg bg-linear-to-br from-indigo-500 to-purple-600 text-white active:scale-[0.98] motion-reduce:active:scale-100 transition-all cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
              >
                分析匹配度
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── T19: 对比简历选择弹窗 ── */}
      <CompareSelectDialog
        open={compareOpen}
        currentResumeId={resumeId}
        onConfirm={handleCompareConfirm}
        onCancel={() => setCompareOpen(false)}
      />
    </div>
  );
}
