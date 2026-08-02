import { useEffect, useState, useRef, useCallback, memo } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useAppChat } from "../context/AppChatContext";
import {
  ChatCircleDots,
  MagnifyingGlass,
  Trash,
  ThumbsUp,
  ThumbsDown,
  X,
  FileText,
  Target,
  PencilSimple,
  Swap,
  FilePlus,
  Briefcase,
  GraduationCap,
  MapTrifold,
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
import { getBuilderResume, type ResumeModule } from "../api/builder";
import ConfirmDialog from "../components/ConfirmDialog";
import { CompareSelectDialog } from "../components/CompareSelectDialog";
import MarkdownRenderer from "../components/MarkdownRenderer";
import AgentProcessPanel from "../components/AgentProcessPanel";
import ResumeEditDiffDialog from "../components/ResumeEditDiffDialog";
import ChatInput from "../components/ChatInput";

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

// 空状态功能卡片（参考 UP简历：1 大卡 + 4 小卡 不对称网格）
// 大卡片 span 跨 2 列；question 点击发送问题，navigate 点击跳转路由
interface GuideCard {
  icon: typeof FileText;
  label: string;
  description: string;
  primary?: boolean;
  span?: boolean;
  question?: string;
  navigate?: string;
}

const GUIDE_CARDS: GuideCard[] = [
  {
    icon: MagnifyingGlass,
    label: "简历诊断",
    description: "从招聘者的视角分析简历问题",
    question: "请全面诊断这份简历的优点和不足",
    primary: true,
    span: true,
  },
  {
    icon: FilePlus,
    label: "创建简历",
    description: "快速开始一份新的简历",
    navigate: "/resumes",
  },
  {
    icon: Briefcase,
    label: "校招推荐",
    description: "筛选全网校招信息",
    question: "请根据我的简历推荐合适的校招机会",
  },
  {
    icon: GraduationCap,
    label: "面试准备",
    description: "面试真题量身定制",
    question: "请根据这份简历模拟一场面试",
  },
  {
    icon: MapTrifold,
    label: "职业规划",
    description: "行业大牛手把手指导",
    question: "请帮我分析我的职业发展方向",
  },
];

// ── 来源引用组件 ────────────────────────────────────────

const SOURCE_TRUNCATE_LIMIT = 220;

function SourceCard({ index, text }: { index: number; text: string }) {
  const [expanded, setExpanded] = useState(false);
  const isLong = text.length > SOURCE_TRUNCATE_LIMIT;

  return (
    <div className="p-3 rounded-xl bg-brand/5 border border-brand/10 text-xs text-[var(--color-text-secondary)] leading-relaxed">
      <span className="text-brand font-semibold mr-2">[{index}]</span>
      {isLong && !expanded ? text.slice(0, SOURCE_TRUNCATE_LIMIT) + "..." : text}
      {isLong && (
        <button
          onClick={() => setExpanded((v) => !v)}
          className="ml-1 text-brand hover:text-brand-hover underline-offset-2 hover:underline cursor-pointer"
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
          hover:text-brand hover:bg-brand/10 px-2 py-1 rounded-md
          transition-all duration-300 cursor-pointer"
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
    <span className="inline-block w-0.5 h-4 bg-brand ml-0.5 align-middle animate-cursor-blink" />
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
  onGuideClick,
}: {
  searching: boolean;
  asking: boolean;
  onGuideClick: (card: GuideCard) => void;
}) {
  if (searching) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center py-16">
        <div className="w-16 h-16 rounded-2xl bg-brand/10 border border-brand/15
          flex items-center justify-center text-brand mb-5">
          <ChatCircleDots size={28} weight="duotone" aria-hidden="true" />
        </div>
        <p className="text-base text-[var(--color-text-secondary)] mb-1.5">没有匹配的问答</p>
        <p className="text-sm text-[var(--color-text-muted)]">换个关键词试试</p>
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col items-center justify-center py-10 px-6">
      {/* 顶部 tagline（截图3） */}
      <p className="text-sm text-[var(--color-text-muted)] text-center mb-8 max-w-lg leading-relaxed">
        从简历打磨到面试准备，陪你从简历到 Offer，每一步都不孤单。
      </p>

      {/* 不对称功能卡片网格：大卡跨 2 列 + 4 张小卡（截图3） */}
      <div className="w-full max-w-3xl grid grid-cols-1 sm:grid-cols-3 gap-4">
        {GUIDE_CARDS.map((card) => {
          const Icon = card.icon;
          const isPrimary = !!card.primary;
          return (
            <button
              key={card.label}
              onClick={() => onGuideClick(card)}
              disabled={asking}
              className={`group flex items-center gap-3.5 p-4 rounded-2xl border text-left
                transition-all duration-300 cursor-pointer
                hover:-translate-y-1 hover:shadow-xl hover:shadow-black/5
                active:scale-[0.98] motion-reduce:active:scale-100
                disabled:opacity-40 disabled:cursor-not-allowed
                ${card.span ? "sm:col-span-2" : ""}
                ${isPrimary
                  ? "bg-brand/10 border-brand/15 hover:border-brand/30"
                  : "bg-white/80 border-[var(--color-border)] hover:border-brand/25"
                }`}
              aria-label={card.label}
            >
              <div className={`shrink-0 flex items-center justify-center
                ${isPrimary
                  ? "w-11 h-11 rounded-xl bg-brand text-white shadow-sm shadow-brand/25"
                  : "w-10 h-10 rounded-[10px] bg-[var(--color-bg-secondary)] text-[var(--color-text-secondary)]"
                }`}>
                <Icon size={isPrimary ? 20 : 18} weight="bold" aria-hidden="true" />
              </div>
              <div className="min-w-0">
                <p className={`text-sm font-semibold ${isPrimary ? "text-brand" : "text-[var(--color-text)]"}`}>
                  {card.label}
                </p>
                <p className="text-xs text-[var(--color-text-muted)] mt-0.5 truncate">
                  {card.description}
                </p>
              </div>
            </button>
          );
        })}
      </div>
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
        <div className="max-w-[75%] px-4 py-3 bg-brand
          text-white text-sm leading-relaxed rounded-2xl rounded-br-md">
          {msg.question}
        </div>
      </div>

      {/* AI 回答 */}
      <div className="flex justify-start mb-4">
        <div className="max-w-[82%]">
          <div className="px-4 py-3.5 rounded-2xl rounded-bl-md leading-relaxed text-sm
            bg-[var(--color-bg-secondary)] border border-[var(--color-border)]">
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
                          ? "text-brand bg-brand/10"
                          : "text-[var(--color-text-muted)] hover:text-brand hover:bg-brand/10"
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
                          ? "text-red-500 bg-red-500/10"
                          : "text-[var(--color-text-muted)] hover:text-red-500 hover:bg-red-500/10"
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
                      hover:text-red-500 hover:bg-red-500/10
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
  const location = useLocation();
  const {
    setResumeId: setCtxResumeId,
    setConversations: setCtxConversations,
    setActiveConversationId: setCtxActiveConvId,
    setConversationLoading: setCtxConvLoading,
  } = useAppChat();

  // 自动选择简历：QAPage 在 / 路由下无 URL 参数，需自动选取第一份简历
  const [resumeId, setResumeId] = useState<number>(0);

  const [resume, setResume] = useState<ResumeItem | null>(null);
  const [chat, setChat] = useState<ChatMessage[]>([]);
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState("");

  // 对话会话状态
  const [conversations, setConversations] = useState<ConversationItem[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<number | null>(null);
  const [conversationLoading, setConversationLoading] = useState(true);
  const [renameOpen, setRenameOpen] = useState(false);
  const [renameValue, setRenameValue] = useState("");
  const [renameTargetId] = useState<number | null>(null);
  const [deleteConvOpen, setDeleteConvOpen] = useState(false);
  const [deleteConvTargetId] = useState<number | null>(null);
  const [deletingConv, setDeletingConv] = useState(false);
  const [creatingConv] = useState(false);

  // sendQuestion ref — 供 location.state effect 调用
  const sendQuestionRef = useRef<((q: string) => void) | null>(null);

  // Task 4：搜索 + 删除相关状态
  const [keyword, setKeyword] = useState("");
  const [debouncedKeyword, setDebouncedKeyword] = useState("");
  const [historyLoading, setHistoryLoading] = useState(false);
  const [clearConfirmOpen, setClearConfirmOpen] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [deletingId, setDeletingId] = useState<number | string | null>(null);

  // T19: 对比弹窗 + JD 输入 + 附件上传
  const [compareOpen, setCompareOpen] = useState(false);
  const [compareIds, setCompareIds] = useState<number[]>([]);
  const [jdOpen, setJdOpen] = useState(false);
  const [jdText, setJdText] = useState("");
  const [uploading, setUploading] = useState(false);

  // ── AI 修改简历实时 diff 弹窗 ──
  // Agent 开始前快照当前模块（before），tool_result 到达后拉取最新模块（after）
  const beforeModulesRef = useRef<ResumeModule[] | null>(null);
  const [diffDialogOpen, setDiffDialogOpen] = useState(false);
  const [diffBeforeModules, setDiffBeforeModules] = useState<ResumeModule[] | null>(null);
  const [diffAfterModules, setDiffAfterModules] = useState<ResumeModule[] | null>(null);
  const [diffToolName, setDiffToolName] = useState("");
  const [diffLoading, setDiffLoading] = useState(false);

  // 打开分屏时加载预览 HTML
  // ── 自动选择简历 ──
  // QAPage 在 / 路由下无 URL 参数，需自动选取第一份简历
  useEffect(() => {
    if (resumeId > 0) return;
    let cancelled = false;
    listResumes(50, 0).then((data) => {
      if (cancelled) return;
      if (data.items.length > 0) {
        // 优先选择 ready/partial 状态的简历，否则选第一份
        const ready = data.items.find((r) => r.status === "ready" || r.status === "partial");
        setResumeId((ready ?? data.items[0]).id);
      }
    }).catch(() => {});
    return () => { cancelled = true; };
  }, [resumeId]);

  // ── 同步状态到 AppChatContext（供 Sidebar 读取） ──
  useEffect(() => { setCtxResumeId(resumeId || null); }, [resumeId, setCtxResumeId]);
  useEffect(() => { setCtxConversations(conversations); }, [conversations, setCtxConversations]);
  useEffect(() => { setCtxActiveConvId(activeConversationId); }, [activeConversationId, setCtxActiveConvId]);
  useEffect(() => { setCtxConvLoading(conversationLoading); }, [conversationLoading, setCtxConvLoading]);

  // ── 监听 Sidebar 发出的对话操作事件 ──
  useEffect(() => {
    const handleSelect = (e: Event) => {
      const { conversationId } = (e as CustomEvent).detail;
      if (conversationId && conversationId !== activeConversationId) {
        setActiveConversationId(conversationId);
        setChat([]);
        setKeyword("");
        setDebouncedKeyword("");
      }
    };
    const handleCreate = () => {
      if (!resumeId || creatingConv) return;
      createConversation(resumeId).then((conv) => {
        setConversations((prev) => [conv, ...prev]);
        setActiveConversationId(conv.id);
        setChat([]);
        setKeyword("");
        setDebouncedKeyword("");
      }).catch((e) => {
        setError(e instanceof Error ? e.message : "新建对话失败");
      });
    };
    const handleDelete = (e: Event) => {
      const { conversationId } = (e as CustomEvent).detail;
      deleteConversation(conversationId).then(() => {
        setConversations((prev) => {
          const remaining = prev.filter((c) => c.id !== conversationId);
          if (conversationId === activeConversationId) {
            setActiveConversationId(remaining.length > 0 ? remaining[0].id : null);
            setChat([]);
            setKeyword("");
            setDebouncedKeyword("");
          }
          return remaining;
        });
      }).catch((e) => {
        setError(e instanceof Error ? e.message : "删除对话失败");
      });
    };
    const handleRename = (e: Event) => {
      const { conversationId, title } = (e as CustomEvent).detail;
      renameConversation(conversationId, title).then((updated) => {
        setConversations((prev) => prev.map((c) => (c.id === updated.id ? updated : c)));
      }).catch((e) => {
        setError(e instanceof Error ? e.message : "重命名失败");
      });
    };

    window.addEventListener("chat:select-conversation", handleSelect as EventListener);
    window.addEventListener("chat:create-conversation", handleCreate as EventListener);
    window.addEventListener("chat:delete-conversation", handleDelete as EventListener);
    window.addEventListener("chat:rename-conversation", handleRename as EventListener);
    return () => {
      window.removeEventListener("chat:select-conversation", handleSelect as EventListener);
      window.removeEventListener("chat:create-conversation", handleCreate as EventListener);
      window.removeEventListener("chat:delete-conversation", handleDelete as EventListener);
      window.removeEventListener("chat:rename-conversation", handleRename as EventListener);
    };
  }, [resumeId, activeConversationId, creatingConv]);

  // ── 接收来自 FloatingAIPanel 的导航问题 ──
  useEffect(() => {
    const state = location.state as { question?: string } | null;
    if (state?.question && !asking && resumeId > 0) {
      sendQuestionRef.current?.(state.question);
      // 清除 state 防止重复触发
      window.history.replaceState({}, "");
    }
  }, [location.state, asking, resumeId]);


  // Token 限额状态
  const [quota, setQuota] = useState<QuotaResponse | null>(null);

  const chatEndRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<(() => void) | null>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ── 流式步骤 rAF 节流（性能优化） ──
  // agent_thought / tool_* 事件高频到达，若每段都 setChat 会触发整页重渲染。
  // 改为累积到 pendingStepsRef，由 requestAnimationFrame 每帧批量刷新一次。
  const pendingStepsRef = useRef<AgentStep[]>([]);
  const rafRef = useRef<number | null>(null);

  const applyPendingSteps = useCallback(
    (targetId: string) => {
      const steps = pendingStepsRef.current;
      pendingStepsRef.current = [];
      if (steps.length === 0) return;
      setChat((prev) =>
        prev.map((m) =>
          m.id === targetId
            ? { ...m, agent_steps: [...(m.agent_steps ?? []), ...steps] }
            : m
        )
      );
    },
    []
  );

  /** 调度下一次 rAF 批量刷新（同帧内多次事件只刷新一次） */
  const scheduleStreamingFlush = useCallback(
    (targetId: string) => {
      if (rafRef.current != null) return;
      rafRef.current = requestAnimationFrame(() => {
        rafRef.current = null;
        applyPendingSteps(targetId);
      });
    },
    [applyPendingSteps]
  );

  /** 立即应用待刷新的步骤（agent_done/error/取消等终态事件前调用，保证不丢步骤） */
  const flushStreamingNow = useCallback(
    (targetId: string) => {
      if (rafRef.current != null) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
      applyPendingSteps(targetId);
    },
    [applyPendingSteps]
  );

  /** 追加一段 agent_thought（与最后一个 thought step 合并，避免碎片化） */
  const appendThought = useCallback((content: string) => {
    const steps = pendingStepsRef.current;
    const last = steps[steps.length - 1];
    if (last && last.type === "agent_thought") {
      steps[steps.length - 1] = {
        ...last,
        detail: (last.detail ?? "") + content,
      };
    } else {
      steps.push({ type: "agent_thought", name: "思考", detail: content });
    }
  }, []);

  // 卸载时取消挂起的 rAF
  useEffect(() => {
    return () => {
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current);
    };
  }, []);

  // 加载历史（封装成函数，便于搜索时复用）。conversationId 为空则加载该简历全部历史。
  const loadHistory = useCallback(
    async (kw: string, conversationId: number | null) => {
      if (!resumeId) return;
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
    if (!resumeId) return;
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

      // ── 快照当前模块（before），用于 diff 弹窗 ──
      // 非阻塞：失败则 beforeModulesRef 保持 null，diff 弹窗不弹出
      if (resumeId > 0) {
        getBuilderResume(resumeId)
          .then((data) => { beforeModulesRef.current = data.modules; })
          .catch(() => { beforeModulesRef.current = null; });
      }

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
            // Spec A#7: LLM 推理过程内容，流式分段 emit。
            // 性能优化：追加到 pendingStepsRef，rAF 批量刷新，避免每段触发整页重渲染。
            appendThought(event.content ?? "");
            scheduleStreamingFlush(tempId);
          } else if (event.type === "tool_call") {
            pendingStepsRef.current.push({
              type: "tool_call" as const,
              name: event.tool_name ?? "",
              detail: event.args,
              id: event.id,
            });
            scheduleStreamingFlush(tempId);
          } else if (event.type === "tool_result") {
            pendingStepsRef.current.push({
              type: "tool_result" as const,
              name: event.tool_name ?? "",
              detail: event.summary,
              id: event.id,
            });
            scheduleStreamingFlush(tempId);

            // ── 检测改写类工具完成 → 实时弹出 diff 对比 ──
            // rewrite_star / translate 会全量替换模块并写入数据库
            // tool_result 到达时 DB 已提交，可安全拉取最新模块
            const MODIFYING_TOOLS = ["rewrite_star", "translate", "modify_module", "generate_module", "rewrite_resume"];
            const toolName = event.tool_name ?? "";
            if (MODIFYING_TOOLS.includes(toolName) && beforeModulesRef.current && resumeId > 0) {
              setDiffBeforeModules(beforeModulesRef.current);
              setDiffToolName(toolName);
              setDiffLoading(true);
              setDiffDialogOpen(true);
              // 延迟 500ms 等待 DB 提交完成（与 refreshModules 修复同模式）
              setTimeout(() => {
                getBuilderResume(resumeId)
                  .then((data) => {
                    setDiffAfterModules(data.modules);
                    // 更新 before 快照为当前状态，支持后续多次修改
                    beforeModulesRef.current = data.modules;
                  })
                  .catch(() => {
                    setDiffAfterModules(null);
                  })
                  .finally(() => {
                    setDiffLoading(false);
                  });
              }, 500);
            }
          } else if (event.type === "tool_error") {
            pendingStepsRef.current.push({
              type: "tool_error" as const,
              name: event.tool_name ?? "",
              detail: event.error,
              id: event.id,
            });
            scheduleStreamingFlush(tempId);
          } else if (event.type === "agent_done") {
            // 先立即应用挂起的步骤，再写入最终答案
            flushStreamingNow(tempId);
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
            // QA 改写类工具（rewrite_star/translate）写库后：通知编辑页/侧栏同步
            const wroteModules = (event.process_trace?.tool_sequence ?? []).some(
              (t) => t === "rewrite_star" || t === "translate",
            );
            if (wroteModules) {
              window.dispatchEvent(new Event("resume:modules-refresh"));
              window.dispatchEvent(new Event("resume:list-refresh"));
            }
          } else if (event.type === "quota_exceeded") {
            flushStreamingNow(tempId);
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
            flushStreamingNow(tempId);
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
          flushStreamingNow(tempId);
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
          flushStreamingNow(tempId);
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
    [resumeId, compareIds, activeConversationId, appendThought, scheduleStreamingFlush, flushStreamingNow]
  );

  // 同步 sendQuestion 到 ref，供 location.state effect 调用
  useEffect(() => {
    sendQuestionRef.current = sendQuestion;
  }, [sendQuestion]);

  // ChatInput 提交回调：trim 后触发发送（asking 时忽略）
  const handleSendText = useCallback(
    (text: string) => {
      const q = text.trim();
      if (!q || asking) return;
      sendQuestion(q);
    },
    [asking, sendQuestion]
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
  const navigate = useNavigate();

  const handleGuideClick = useCallback(
    (card: Pick<GuideCard, "navigate" | "question">) => {
      if (asking) return;
      if (card.navigate) {
        navigate(card.navigate);
        return;
      }
      if (card.question === "__JD__") {
        setJdOpen(true);
      } else if (card.question === "__COMPARE__") {
        setCompareOpen(true);
      } else if (card.question) {
        sendQuestion(card.question);
      }
    },
    [asking, sendQuestion, navigate]
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

  // 附件上传简历
  const handleUploadFile = async (file: File) => {
    const validTypes = ["application/pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"];
    const ext = file.name.split(".").pop()?.toLowerCase();
    if (!validTypes.includes(file.type) && ext !== "pdf" && ext !== "docx") return;
    if (file.size > 10 * 1024 * 1024) return;
    setUploading(true);
    try {
      await uploadResume(file);
    } catch {
      // 静默失败，用户可在简历管理页查看
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="flex-1 flex flex-col bg-[var(--color-bg)] overflow-hidden relative">
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

            {/* 当前对话名称（对话切换已移至左侧 Sidebar） */}
            {!conversationLoading && activeConversationId && (
              <div className="mt-1">
                <span className="text-[10px] text-[var(--color-text-muted)]">
                  {conversations.find((c) => c.id === activeConversationId)?.title ?? "新对话"}
                </span>
              </div>
            )}
          </div>

          {/* T19: 对比已选指示器 */}
          {compareIds.length > 0 && (
            <span className="shrink-0 inline-flex items-center gap-1 px-2 py-1 rounded-md
              text-[10px] bg-brand/10 text-brand border border-brand/20">
              <Swap size={10} weight="bold" aria-hidden="true" />
              已选 {compareIds.length} 份对比
            </span>
          )}

          {/* Token 限额显示 */}
          {quota?.enabled && (
            <div className="shrink-0 px-3 py-1.5 rounded-lg text-xs
              bg-[var(--color-bg-secondary)] border border-[var(--color-border)]
              flex items-center gap-2">
              <span className="text-[var(--color-text-muted)]">今日额度</span>
              <span className={`font-mono tabular-nums ${
                quota.remaining < quota.limit * 0.1
                  ? "text-red-500"
                  : quota.remaining < quota.limit * 0.3
                  ? "text-yellow-600"
                  : "text-brand"
              }`}>
                {quota.used}/{quota.limit}
              </span>
              {quota.remaining < quota.limit * 0.1 && (
                <span className="text-red-500 text-[10px]">额度不足</span>
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
              className="w-40 sm:w-56 pl-8 pr-8 py-1.5 rounded-xl text-xs text-[var(--color-text)]
                bg-[#F2F2F7] border border-transparent
                placeholder:text-[var(--color-text-muted)]
                focus:outline-none focus:ring-2 focus:ring-brand/40
                focus:border-brand/50 focus:bg-white
                disabled:opacity-50 transition-all duration-200"
            />
            {keyword && (
              <button
                onClick={() => setKeyword("")}
                aria-label="清除搜索"
                className="absolute right-2 top-1/2 -translate-y-1/2 p-0.5 rounded
                  text-[var(--color-text-muted)] hover:text-[var(--color-text)] hover:bg-black/5
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
            className="shrink-0 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full
              text-xs font-medium border border-[var(--color-border)] text-[var(--color-text-secondary)]
              hover:text-red-500 hover:border-red-500/30 hover:bg-red-500/10
              active:scale-[0.98] motion-reduce:active:scale-100
              transition-all duration-300 cursor-pointer
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
                  className="inline-block w-6 h-6 rounded-full border-2 border-brand border-t-transparent animate-spin"
                  aria-hidden="true"
                />
                <p className="text-xs text-[var(--color-text-muted)] mt-3">加载历史中...</p>
              </div>
            ) : chat.length === 0 ? (
              <EmptyState
                searching={debouncedKeyword.length > 0}
                asking={asking}
                onGuideClick={handleGuideClick}
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
                bg-red-500/10 border border-red-500/20 text-red-500 text-sm animate-shake">
                {error}
              </div>
            )}

            <div ref={chatEndRef} />
          </div>
        </div>
      </div>

      {/* ── 输入区（独立组件，本地管理输入状态避免整页重渲染） ── */}
      <ChatInput
        asking={asking}
        uploading={uploading}
        onSend={handleSendText}
        onCancel={handleCancel}
        onQuickTag={(q) => {
          if (!asking) sendQuestion(q);
        }}
        onFile={handleUploadFile}
      />

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
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 backdrop-blur-sm motion-reduce:backdrop-blur-none"
          role="dialog"
          aria-modal="true"
          aria-label="重命名对话"
          onClick={() => setRenameOpen(false)}
        >
          <div
            className="glass-card w-full max-w-sm mx-4 p-6 shadow-2xl shadow-black/10 animate-fade-in-up motion-reduce:animate-none"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <div className="p-1.5 rounded-lg bg-brand/10 text-brand">
                  <PencilSimple size={18} weight="bold" aria-hidden="true" />
                </div>
                <h3 className="text-base font-semibold text-[var(--color-text)]">
                  重命名对话
                </h3>
              </div>
              <button
                onClick={() => setRenameOpen(false)}
                aria-label="关闭"
                className="p-1.5 rounded-lg text-[var(--color-text-secondary)] hover:text-[var(--color-text)] hover:bg-black/5 active:scale-[0.95] motion-reduce:active:scale-100 transition-all cursor-pointer"
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
                bg-[#F2F2F7] border border-transparent
                placeholder:text-[var(--color-text-muted)]
                focus:outline-none focus:ring-2 focus:ring-brand/40 focus:border-brand/50 focus:bg-white
                transition-all duration-200"
            />
            <div className="flex justify-end gap-2 mt-4">
              <button
                onClick={() => setRenameOpen(false)}
                className="px-3.5 py-1.5 text-sm font-medium rounded-full bg-[#E5E5EA] text-[var(--color-text)] hover:bg-[#D9D9DE] active:scale-[0.98] motion-reduce:active:scale-100 transition-all duration-300 cursor-pointer"
              >
                取消
              </button>
              <button
                onClick={handleRenameConfirm}
                disabled={!renameValue.trim()}
                className="px-3.5 py-1.5 text-sm font-medium rounded-full bg-brand text-white hover:bg-brand-hover hover:scale-[1.02] active:scale-[0.98] motion-reduce:active:scale-100 transition-all duration-300 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
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
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 backdrop-blur-sm motion-reduce:backdrop-blur-none"
          role="dialog"
          aria-modal="true"
          aria-label="粘贴岗位描述"
          onClick={() => setJdOpen(false)}
        >
          <div
            className="glass-card w-full max-w-lg mx-4 p-6 shadow-2xl shadow-black/10 animate-fade-in-up motion-reduce:animate-none"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <div className="p-1.5 rounded-lg bg-brand/10 text-brand">
                  <Target size={18} weight="bold" aria-hidden="true" />
                </div>
                <h3 className="text-base font-semibold text-[var(--color-text)]">
                  粘贴岗位描述
                </h3>
              </div>
              <button
                onClick={() => setJdOpen(false)}
                aria-label="关闭"
                className="p-1.5 rounded-lg text-[var(--color-text-secondary)] hover:text-[var(--color-text)] hover:bg-black/5 active:scale-[0.95] motion-reduce:active:scale-100 transition-all cursor-pointer"
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
                bg-[#F2F2F7] border border-transparent
                placeholder:text-[var(--color-text-muted)]
                focus:outline-none focus:ring-2 focus:ring-brand/40 focus:border-brand/50 focus:bg-white
                resize-none transition-all duration-200"
            />
            <div className="flex justify-end gap-2 mt-4">
              <button
                onClick={() => setJdOpen(false)}
                className="px-3.5 py-1.5 text-sm font-medium rounded-full bg-[#E5E5EA] text-[var(--color-text)] hover:bg-[#D9D9DE] active:scale-[0.98] motion-reduce:active:scale-100 transition-all duration-300 cursor-pointer"
              >
                取消
              </button>
              <button
                onClick={handleJdConfirm}
                disabled={!jdText.trim()}
                className="px-3.5 py-1.5 text-sm font-medium rounded-full bg-brand text-white hover:bg-brand-hover hover:scale-[1.02] active:scale-[0.98] motion-reduce:active:scale-100 transition-all duration-300 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
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

      {/* ── AI 修改简历实时 diff 弹窗 ── */}
      <ResumeEditDiffDialog
        open={diffDialogOpen}
        onClose={() => setDiffDialogOpen(false)}
        beforeModules={diffBeforeModules}
        afterModules={diffAfterModules}
        toolName={diffToolName}
        loading={diffLoading}
      />
    </div>
  );
}
