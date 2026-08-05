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
  cancelFeedback,
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
import { listResumes, uploadResume, auditResume, type ResumeItem, type AtsAuditResult } from "../api/resumes";
import {
  getBuilderResume,
  saveDraft,
  saveComplete,
  acquireEditLock,
  renewEditLock,
  releaseEditLock,
  createBuilderResume,
  type ResumeModule,
  type ResumeStyle,
  type ModuleType,
  type ResumeModuleInput,
} from "../api/builder";
import { A4PreviewPanel } from "../components/builder/A4PreviewPanel";
import { ModuleCardEditor } from "../components/builder/ModuleCardEditor";
import ConfirmDialog from "../components/ConfirmDialog";
import { CompareSelectDialog } from "../components/CompareSelectDialog";
import MarkdownRenderer from "../components/MarkdownRenderer";
import AgentProcessPanel from "../components/AgentProcessPanel";
// E1: 简历诊断结构化卡片（四维评分 + 诊断结论 + 可溯源来源）
import DiagnosisCard, { isDiagnosisMessage } from "../components/DiagnosisCard";
import type { DiagnosisSource } from "../components/DiagnosisCard";
// P1-C: 工具卡片通用分发（JDMatchReport 等）
import AgentCardRouter from "../components/AgentCardRouter";
import ResumeEditDiffDialog from "../components/ResumeEditDiffDialog";
import AtsAuditReport from "../components/AtsAuditReport";
import ChatInput from "../components/ChatInput";
import VersionHistoryDialog from "../components/VersionHistoryDialog";
import PasteResumeDialog from "../components/builder/PasteResumeDialog";
import { StylePanel } from "../components/builder/StylePanel";

interface ChatMessage {
  id: number | string;
  question: string;
  answer: string;
  streaming: boolean;
  /** Task 5.1: 质量反馈状态 */
  feedback?: "positive" | "negative" | null;
  /** 创建时间，用于排序和显示 */
  created_at?: string;
  /** Token 消耗 */
  token_usage?: { total: number; prompt: number; completion: number };
  /** T18: Agent 推理步骤 */
  agent_steps?: AgentStep[];
  /** E1: 结构化引用来源（text / section / start_char / end_char） */
  sources?: DiagnosisSource[];
}

/** E1: 历史 sources 兼容两种格式（后端并行升级中：string[] → SourceItem[]） */
function normalizeHistorySources(raw: unknown): DiagnosisSource[] | undefined {
  if (!Array.isArray(raw)) return undefined;
  return raw.map((s) =>
    typeof s === "string" ? { text: s } : (s as DiagnosisSource)
  );
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
    question: "请帮我创建一份简历",
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
  hasResume,
}: {
  searching: boolean;
  asking: boolean;
  onGuideClick: (card: GuideCard) => void;
  hasResume: boolean;
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
          // 无简历时禁用需要简历的卡片，但"创建简历"卡片始终可点击
          const isCreateCard = card.label === "创建简历";
          const needsResume = Boolean(card.question) && !card.navigate && !isCreateCard;
          const disabled = asking || Boolean(needsResume && !hasResume);
          return (
            <button
              key={card.label}
              onClick={() => onGuideClick(card)}
              disabled={disabled}
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
  /** current 为当前反馈状态，用于判断点同按钮=取消、点异按钮=切换 */
  onFeedback: (
    id: number | string,
    rating: "positive" | "negative",
    current?: "positive" | "negative" | null
  ) => void;
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
            ) : !msg.streaming && isDiagnosisMessage(msg) ? (
              /* E1: 简历诊断回答 → 结构化卡片（评分提取失败自动回退纯 markdown） */
              <DiagnosisCard answer={msg.answer} sources={msg.sources} />
            ) : !msg.streaming && msg.agent_steps && msg.agent_steps.length > 0 ? (
              /* P1-C: 有 Agent 步骤时 → 卡片通用分发（JDMatchReport 等，无匹配则 markdown） */
              <AgentCardRouter steps={msg.agent_steps} answer={msg.answer} streaming={msg.streaming} />
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
                  </span>
                )}
                {/* Token 消耗 */}
                {msg.token_usage?.total ? (
                  <span
                    data-testid="message-token-usage"
                    className="inline-flex items-center gap-1 mt-1 px-1.5 py-0.5 text-[10px] font-mono tabular-nums text-[var(--color-text-muted)] bg-[var(--color-bg-secondary)] rounded-md"
                  >
                    <svg className="w-2.5 h-2.5 opacity-50" viewBox="0 0 16 16" fill="currentColor">
                      <path d="M8 1a7 7 0 100 14A7 7 0 008 1zm0 12.5a5.5 5.5 0 110-11 5.5 5.5 0 010 11zM8 4a.75.75 0 01.75.75v2.5h2.5a.75.75 0 010 1.5h-2.5v2.5a.75.75 0 01-1.5 0v-2.5h-2.5a.75.75 0 010-1.5h2.5v-2.5A.75.75 0 018 4z"/>
                    </svg>
                    {msg.token_usage.total.toLocaleString()} tokens
                    {msg.token_usage.prompt != null && msg.token_usage.completion != null && (
                      <span className="opacity-60">
                        （↑{msg.token_usage.prompt.toLocaleString()} ↓{msg.token_usage.completion.toLocaleString()}）
                      </span>
                    )}
                  </span>
                ) : null}
              </div>
              <div className="shrink-0 flex items-center gap-1 mt-2">
                {/* Task 5.1: 质量反馈按钮（点同按钮=取消，点异按钮=切换） */}
                {canFeedback && (
                  <>
                    <button
                      onClick={() => onFeedback(msg.id, "positive", msg.feedback)}
                      aria-label="有帮助"
                      title={msg.feedback === "positive" ? "取消反馈" : "标记为有帮助"}
                      className={`inline-flex items-center gap-0.5 px-1.5 py-1
                        rounded-md text-xs transition-all cursor-pointer
                        ${msg.feedback === "positive"
                          ? "text-brand bg-brand/10"
                          : "text-[var(--color-text-muted)] hover:text-brand hover:bg-brand/10"
                        }`}
                    >
                      <ThumbsUp size={12} weight={msg.feedback === "positive" ? "fill" : "regular"} aria-hidden="true" />
                    </button>
                    <button
                      onClick={() => onFeedback(msg.id, "negative", msg.feedback)}
                      aria-label="没帮助"
                      title={msg.feedback === "negative" ? "取消反馈" : "标记为没帮助"}
                      className={`inline-flex items-center gap-0.5 px-1.5 py-1
                        rounded-md text-xs transition-all cursor-pointer
                        ${msg.feedback === "negative"
                          ? "text-red-500 bg-red-500/10"
                          : "text-[var(--color-text-muted)] hover:text-red-500 hover:bg-red-500/10"
                        }`}
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

  // v2: 简历预览面板（点击简历时右侧弹出）
  const [showPreview, setShowPreview] = useState(false);
  const [previewModules, setPreviewModules] = useState<ResumeModule[]>([]);
  const [previewStyle, setPreviewStyle] = useState<ResumeStyle | null>(null);
  const [editingModule, setEditingModule] = useState<string | null>(null);
  const [expandedType, setExpandedType] = useState<ModuleType | null>(null);
  const [previewKey, setPreviewKey] = useState(0);
  // v2: BuilderPage 迁移 — 编辑锁 + 保存 + 版本
  const [version, setVersion] = useState(0);
  const [saving, setSaving] = useState(false);
  const [, setSaveStatus] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [, setLastSaveMode] = useState<"draft" | "complete" | null>(null);
  const [showVersionHistory, setShowVersionHistory] = useState(false);
  const [showPasteDialog, setShowPasteDialog] = useState(false);
  const [showStylePanel, setShowStylePanel] = useState(false);

  // P0-A: ATS 审计弹窗
  const [showAtsAudit, setShowAtsAudit] = useState(false);
  const [atsAuditResult, setAtsAuditResult] = useState<AtsAuditResult | null>(null);
  const [atsAuditLoading, setAtsAuditLoading] = useState(false);
  const lockTokenRef = useRef<string | null>(null);
  const autoSaveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const modulesRef = useRef(previewModules);
  const styleRef = useRef(previewStyle);
  useEffect(() => { modulesRef.current = previewModules; }, [previewModules]);
  useEffect(() => { styleRef.current = previewStyle; }, [previewStyle]);
  const [uploading, setUploading] = useState(false);

  // ── 无简历引导状态 ──
  const [aiCreateMode, setAiCreateMode] = useState(false);
  const [pendingAiCreateQuestion, setPendingAiCreateQuestion] = useState<string | null>(null);

  // ── AI 修改简历实时 diff 弹窗 ──
  // Agent 开始前快照当前模块（before），tool_result 到达后拉取最新模块（after）
  const beforeModulesRef = useRef<ResumeModule[] | null>(null);
  const [diffDialogOpen, setDiffDialogOpen] = useState(false);
  const [diffBeforeModules, setDiffBeforeModules] = useState<ResumeModule[] | null>(null);
  const [diffAfterModules, setDiffAfterModules] = useState<ResumeModule[] | null>(null);
  const [diffToolName, setDiffToolName] = useState("");
  const [diffLoading, setDiffLoading] = useState(false);

  // G 功能：diff 弹窗里逐条还原后保存，落库结果回填预览模块 + before 快照
  const handleDiffModulesSaved = useCallback((modules: ResumeModule[]) => {
    setPreviewModules(modules);
    setDiffAfterModules(modules);
    beforeModulesRef.current = modules;
  }, []);

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

  // ── 接收来自简历列表的 resumeId（v2: 点击简历跳转 QA） ──
  useEffect(() => {
    const state = location.state as { resumeId?: number; question?: string } | null;
    if (state?.resumeId && state.resumeId !== resumeId) {
      setResumeId(state.resumeId);
      setShowPreview(true); // 立即显示预览
    }
    if (state?.question && !asking && resumeId > 0) {
      sendQuestionRef.current?.(state.question);
    }
    // 清除 state 防止重复触发
    if (state?.resumeId || state?.question) {
      window.history.replaceState({}, "");
    }
  }, [location.state, asking, resumeId]);


  // Token 限额状态
  const [quota, setQuota] = useState<QuotaResponse | null>(null);

  const chatEndRef = useRef<HTMLDivElement>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<(() => void) | null>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ── 实时滚动：跟踪用户是否在底部 ──
  // 用户上滚时暂停自动滚动，下滚回底部时恢复
  const isNearBottomRef = useRef(true);

  /** 检测滚动容器是否在底部附近（距底部 80px 以内视为"在底部"） */
  const checkNearBottom = useCallback(() => {
    const el = scrollContainerRef.current;
    if (!el) return;
    const threshold = 80;
    isNearBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < threshold;
  }, []);

  /** 滚动到底部（smooth） */
  const scrollToBottom = useCallback((smooth = true) => {
    const el = scrollContainerRef.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior: smooth ? "smooth" : "instant" });
  }, []);

  // ── 流式步骤 rAF 节流（性能优化） ──
  // agent_thought / tool_* 事件高频到达，若每段都 setChat 会触发整页重渲染。
  // 改为累积到 pendingStepsRef，由 requestAnimationFrame 每帧批量刷新一次。
  // flush 后自动滚动到底部，实现实时滚动体验。
  const pendingStepsRef = useRef<AgentStep[]>([]);
  const rafRef = useRef<number | null>(null);
  // P1-C: 记录每个 tool_call 的开始时间，用于计算 durationMs
  const stepStartRef = useRef<Map<string, number>>(new Map());

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
      // rAF 刷新后立即滚动到底部（仅在用户未上滚时）
      requestAnimationFrame(() => {
        if (isNearBottomRef.current) scrollToBottom(false);
      });
    },
    [scrollToBottom]
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
          streaming: false,
          created_at: it.created_at,
          token_usage: it.token_usage,
          // E1: 历史记录来源（后端返回 string[] 或结构化 SourceItem[]）
          sources: normalizeHistorySources(it.sources),
          // 回显当前用户对该条已点的赞/踩（history 接口附带）
          feedback: it.feedback ?? null,
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

  // 加载简历元信息 + 预览数据
  useEffect(() => {
    if (!resumeId) return;
    listResumes().then((data) => {
      const r = data.items.find((item) => item.id === resumeId);
      if (r) setResume(r);
    });
    // v2: 加载预览模块数据
    getBuilderResume(resumeId).then((data) => {
      setPreviewModules(data.modules ?? []);
      setPreviewStyle(data.style ?? null);
      setVersion(data.version);
      setShowPreview(true);
    }).catch(() => {});
  }, [resumeId]);

  // v2: 编辑锁生命周期
  useEffect(() => {
    if (!resumeId) return;
    acquireEditLock(resumeId)
      .then((res) => { if (res.locked && res.lock_token) lockTokenRef.current = res.lock_token; })
      .catch(() => {});
    const heartbeat = setInterval(() => {
      if (lockTokenRef.current) renewEditLock(resumeId, lockTokenRef.current).catch(() => {});
    }, 60000);
    return () => {
      clearInterval(heartbeat);
      if (lockTokenRef.current) releaseEditLock(resumeId, lockTokenRef.current).catch(() => {});
    };
  }, [resumeId]);

  // v2: 自动保存草稿（5s 防抖）
  const doSaveDraft = useCallback(async () => {
    if (!resume) return;
    setSaveStatus("saving");
    try {
      const result = await saveDraft(resumeId, {
        modules: modulesRef.current.map((m) => ({
          module_type: m.module_type,
          content: m.content,
          sort_order: m.sort_order,
        })),
        style: styleRef.current ?? undefined,
      });
      setVersion(result.version);
      setSaveStatus("saved");
      setLastSaveMode("draft");
    } catch {
      setSaveStatus("error");
    }
  }, [resume, resumeId]);

  useEffect(() => {
    if (!resume || previewModules.length === 0) return;
    if (autoSaveTimerRef.current) clearTimeout(autoSaveTimerRef.current);
    autoSaveTimerRef.current = setTimeout(() => { doSaveDraft(); }, 5000);
    return () => { if (autoSaveTimerRef.current) clearTimeout(autoSaveTimerRef.current); };
  }, [previewModules, previewStyle, resume, doSaveDraft]);

  // P0-A: ATS 审计
  const handleAtsAudit = useCallback(async () => {
    if (!resume) return;
    setAtsAuditLoading(true);
    setAtsAuditResult(null);
    setShowAtsAudit(true);
    try {
      const result = await auditResume(resume.id);
      setAtsAuditResult(result);
    } catch {
      setAtsAuditResult(null);
    } finally {
      setAtsAuditLoading(false);
    }
  }, [resume]);

  // v2: 手动保存草稿
  const handleSaveDraft = useCallback(async () => {
    if (!resume) return;
    setSaving(true);
    try {
      const result = await saveDraft(resumeId, {
        modules: modulesRef.current.map((m) => ({
          module_type: m.module_type,
          content: m.content,
          sort_order: m.sort_order,
        })),
        style: styleRef.current ?? undefined,
      });
      setVersion(result.version);
      setSaveStatus("saved");
      setLastSaveMode("draft");
    } catch {
      setSaveStatus("error");
    } finally {
      setSaving(false);
    }
  }, [resume, resumeId]);

  // v2: 保存并完成
  const handleSaveComplete = useCallback(async () => {
    if (!resume) return;
    setSaving(true);
    try {
      const result = await saveComplete(resumeId, version, {
        modules: modulesRef.current.map((m) => ({
          module_type: m.module_type,
          content: m.content,
          sort_order: m.sort_order,
        })),
        style: styleRef.current ?? undefined,
      });
      setVersion(result.version);
      setSaveStatus("saved");
      setLastSaveMode("complete");
    } catch {
      setSaveStatus("error");
    } finally {
      setSaving(false);
    }
  }, [resume, resumeId, version]);

  // v2: 粘贴简历回调
  const handlePasteParsed = useCallback((parsedModules: ResumeModuleInput[]) => {
    const newModules: ResumeModule[] = parsedModules.map((m, i) => ({
      id: -Date.now() - i,
      resume_id: resumeId,
      module_type: m.module_type,
      content: m.content,
      sort_order: m.sort_order,
      created_at: new Date().toISOString(),
    }));
    setPreviewModules(newModules);
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

  useEffect(() => {
    return () => abortRef.current?.();
  }, []);

  // T19: 统一走 Agent 模式（去模式切换），支持 compare_ids
  // v2: 支持 toolMode="builder" 触发后端 builder 意图直达（模块编辑器 AI 操作走此路径）
  const sendQuestion = useCallback(
    (q: string, options?: { toolMode?: string; moduleType?: string; entryId?: string; action?: string }) => {
      setError("");

      // ── 无简历时：先创建空简历，再启动 AI 创建流程 ──
      if (!resumeId || resumeId === 0) {
        setAiCreateMode(true);
        // 先创建一个空的 builder 简历
        createBuilderResume({ filename: "未命名简历" }).then((resume) => {
          setResumeId(resume.id);
          // 设置待发送的问题，等 resumeId 更新后自动发送
          setPendingAiCreateQuestion(q);
        }).catch((err) => {
          setError(err instanceof Error ? err.message : "创建简历失败");
          setAiCreateMode(false);
        });
        return;
      }

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
        streaming: true,
      };
      setChat((prev) => [...prev, newMsg]);

      // 发送新消息后强制滚动到底部（无论用户之前是否上滚）
      isNearBottomRef.current = true;
      requestAnimationFrame(() => scrollToBottom(false));

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
            // P1-C: 记录开始时间 + 填充结构化字段
            const stepId = event.id ?? `tc-${Date.now()}`;
            if (event.id) stepStartRef.current.set(event.id, Date.now());
            let parsedArgs: Record<string, unknown> | undefined;
            if (event.args) {
              try { parsedArgs = JSON.parse(event.args); } catch { /* not JSON */ }
            }
            pendingStepsRef.current.push({
              type: "tool_call" as const,
              name: event.tool_name ?? "",
              detail: event.args,
              id: stepId,
              args: parsedArgs,
              argsText: event.args,
              status: "running",
              startedAt: Date.now(),
            });
            scheduleStreamingFlush(tempId);
          } else if (event.type === "tool_result") {
            // P1-C: 计算 durationMs + 填充 result 字段
            const durationMs = event.id
              ? (Date.now() - (stepStartRef.current.get(event.id) ?? Date.now()))
              : undefined;
            if (event.id) stepStartRef.current.delete(event.id);
            pendingStepsRef.current.push({
              type: "tool_result" as const,
              name: event.tool_name ?? "",
              detail: event.summary,
              id: event.id,
              result: event.detail,
              status: "done",
              durationMs: durationMs != null && durationMs > 0 ? durationMs : undefined,
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
            // P1-C: 计算 durationMs + status=error
            const errorDurationMs = event.id
              ? (Date.now() - (stepStartRef.current.get(event.id) ?? Date.now()))
              : undefined;
            if (event.id) stepStartRef.current.delete(event.id);
            pendingStepsRef.current.push({
              type: "tool_error" as const,
              name: event.tool_name ?? "",
              detail: event.error,
              id: event.id,
              status: "error",
              durationMs: errorDurationMs != null && errorDurationMs > 0 ? errorDurationMs : undefined,
            });
            scheduleStreamingFlush(tempId);
          } else if (event.type === "tool_stream") {
            // P1-C: 工具内部 LLM 流式 token → copy-on-write 追加到最后一个同工具 tool_stream step
            // 从 BuilderAIChat 移植：高频事件直接 setChat，避免 pending buffer 无法合并
            setChat((prev) =>
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
                    detail: (lastStep.detail ?? "") + (event.content ?? ""),
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
          } else if (event.type === "usage") {
            // 实时更新 token 消耗（每轮 LLM 调用后推送）
            if (event.total) {
              setChat((prev) =>
                prev.map((m) =>
                  m.id === tempId
                    ? {
                        ...m,
                        token_usage: {
                          total:
                            (event.total?.prompt_tokens ?? 0) +
                            (event.total?.completion_tokens ?? 0),
                          prompt: event.total?.prompt_tokens ?? 0,
                          completion: event.total?.completion_tokens ?? 0,
                        },
                      }
                    : m
                )
              );
            }
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
                      // E1: agent_done.sources 携带可溯源来源（text/section/start_char/end_char）
                      sources: event.sources as DiagnosisSource[] | undefined,
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
            // QA 改写类工具（rewrite_star/translate/rewrite_resume）写库后：通知编辑页/侧栏同步
            const wroteModules = (event.process_trace?.tool_sequence ?? []).some(
              (t) => t === "rewrite_star" || t === "translate" || t === "rewrite_resume",
            );
            if (wroteModules) {
              window.dispatchEvent(new Event("resume:modules-refresh"));
              window.dispatchEvent(new Event("resume:list-refresh"));
            }

            // 新增：AI 创建简历完成后自动跳转到编辑器
            if (aiCreateMode && event.process_trace?.tool_sequence?.includes("rewrite_resume")) {
              // 等待 500ms 确保数据写入完成
              setTimeout(() => {
                navigate(`/resumes/${resumeId}/edit`);
              }, 500);
              setAiCreateMode(false);
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
          toolMode: options?.toolMode,
          moduleType: options?.moduleType,
          entryId: options?.entryId,
          action: options?.action,
        },
      );
    },
    [resumeId, compareIds, activeConversationId, appendThought, scheduleStreamingFlush, flushStreamingNow]
  );

  // 同步 sendQuestion 到 ref，供 location.state effect 调用
  useEffect(() => {
    sendQuestionRef.current = sendQuestion;
  }, [sendQuestion]);

  // ── AI 创建简历：resumeId 更新后发送待发送的问题 ──
  useEffect(() => {
    if (resumeId > 0 && pendingAiCreateQuestion) {
      const q = pendingAiCreateQuestion;
      setPendingAiCreateQuestion(null);
      // 延迟一点确保 state 更新完成
      setTimeout(() => {
        sendQuestion(q);
      }, 100);
    }
  }, [resumeId, pendingAiCreateQuestion, sendQuestion]);

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

  // Task 5.1：质量反馈（点同按钮=取消，点异按钮=切换）
  const handleFeedback = useCallback(
    async (
      msgId: number | string,
      rating: "positive" | "negative",
      current: "positive" | "negative" | null | undefined,
    ) => {
      if (typeof msgId !== "number") return;
      const prev = current ?? null;
      const next = prev === rating ? null : rating;
      // 乐观更新 UI
      setChat((msgs) =>
        msgs.map((m) => (m.id === msgId ? { ...m, feedback: next } : m))
      );
      try {
        if (next === null) {
          await cancelFeedback(msgId);
        } else {
          await submitFeedback(msgId, next);
        }
      } catch {
        // 失败时回滚反馈状态
        setChat((msgs) =>
          msgs.map((m) => (m.id === msgId ? { ...m, feedback: prev } : m))
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

          {/* v2: 预览面板切换 */}
          {resumeId > 0 && (
            <button
              onClick={() => setShowPreview((v) => !v)}
              className={`shrink-0 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full
                text-xs font-medium border transition-all duration-300 cursor-pointer ${
                showPreview
                  ? "border-brand/30 bg-brand/10 text-brand"
                  : "border-[var(--color-border)] text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-secondary)]"
              }`}
              title={showPreview ? "关闭预览" : "打开简历预览"}
            >
              📄 {showPreview ? "关闭预览" : "预览简历"}
            </button>
          )}

          {/* v2: 保存按钮 */}
          {resumeId > 0 && showPreview && (
            <>
              <button
                onClick={() => setShowPasteDialog(true)}
                className="shrink-0 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full
                  text-xs font-medium border border-[var(--color-border)] text-[var(--color-text-secondary)]
                  hover:bg-[var(--color-bg-secondary)] transition-all cursor-pointer"
              >
                📋 粘贴导入
              </button>
              <button
                onClick={() => setShowStylePanel(true)}
                className="shrink-0 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full
                  text-xs font-medium border border-[var(--color-border)] text-[var(--color-text-secondary)]
                  hover:bg-[var(--color-bg-secondary)] transition-all cursor-pointer"
              >
                🖌️ 样式
              </button>
              <button
                onClick={() => setShowVersionHistory(true)}
                className="shrink-0 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full
                  text-xs font-medium border border-[var(--color-border)] text-[var(--color-text-secondary)]
                  hover:bg-[var(--color-bg-secondary)] transition-all cursor-pointer"
                title="查看检索索引版本历史"
              >
                📑 版本历史
              </button>
              <button
                onClick={handleAtsAudit}
                className="shrink-0 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full
                  text-xs font-medium border border-[var(--color-border)] text-[var(--color-text-secondary)]
                  hover:bg-[var(--color-bg-secondary)] transition-all cursor-pointer"
                title="模拟 ATS 解析，检测简历可读性问题"
              >
                🔍 ATS
              </button>
              <button
                onClick={handleSaveDraft}
                disabled={saving}
                className="shrink-0 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full
                  text-xs font-medium border border-[var(--color-border)] text-[var(--color-text-secondary)]
                  hover:bg-[var(--color-bg-secondary)] disabled:opacity-50 transition-all cursor-pointer"
              >
                💾 保存草稿
              </button>
              <button
                onClick={handleSaveComplete}
                disabled={saving}
                className="shrink-0 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full
                  text-xs font-semibold bg-brand text-white
                  hover:bg-brand/90 disabled:opacity-50 transition-all cursor-pointer"
              >
                ✅ 保存并完成
              </button>
            </>
          )}
        </div>
      </div>

      {/* ── 左右各 50%：聊天/编辑器 | 预览 ── */}
      <div className="flex-1 flex overflow-hidden">
        {/* 左侧 50%：聊天 或 模块编辑器（点击预览模块时覆盖聊天） */}
        <div
          ref={scrollContainerRef}
          className={`${showPreview ? "w-1/2" : "flex-1"} overflow-y-auto transition-all duration-300`}
          onScroll={!editingModule ? checkNearBottom : undefined}
        >
          {/* Agent 聊天模式（无模块编辑时显示） */}
          {!editingModule ? (
            <div className="flex flex-col h-full">
              <div className="flex-1 overflow-y-auto px-4 sm:px-6 py-6">
                <div className="max-w-3xl mx-auto">
                  {historyLoading && chat.length === 0 && resumeId > 0 ? (
                    <div className="flex flex-col items-center justify-center py-16">
                      <span className="inline-block w-6 h-6 rounded-full border-2 border-brand border-t-transparent animate-spin" />
                      <p className="text-xs text-[var(--color-text-muted)] mt-3">加载历史中...</p>
                    </div>
                  ) : chat.length === 0 ? (
                    <EmptyState
                      searching={debouncedKeyword.length > 0}
                      asking={asking}
                      onGuideClick={handleGuideClick}
                      hasResume={resumeId > 0}
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
                  {error && (
                    <div className="max-w-3xl mx-auto mb-4 p-3 rounded-xl bg-red-500/10 border border-red-500/20 text-red-500 text-sm animate-shake">
                      {error}
                    </div>
                  )}
                  <div ref={chatEndRef} />
                </div>
              </div>
              {/* 聊天输入框（只在聊天模式下显示） */}
              <div className="shrink-0 border-t border-[var(--color-border)]">
                <ChatInput
                  asking={asking}
                  uploading={uploading}
                  disabled={!resumeId || resumeId === 0}
                  onSend={handleSendText}
                  onCancel={handleCancel}
                  onQuickTag={(q) => {
                    if (!asking) sendQuestion(q);
                  }}
                  onFile={handleUploadFile}
                />
              </div>
            </div>
          ) : editingModule && resumeId > 0 ? (
            /* 模块编辑器（点击预览模块时覆盖聊天） */
            <div className="h-full flex flex-col">
              <div className="shrink-0 px-4 py-2 border-b border-[var(--color-border)] bg-white/80 backdrop-blur-xl flex items-center gap-2">
                <button
                  onClick={() => setEditingModule(null)}
                  className="text-xs text-brand hover:text-brand/80 font-medium cursor-pointer"
                >
                  ← 返回聊天
                </button>
                <span className="text-xs text-[var(--color-text-muted)]">
                  正在编辑：{editingModule}
                </span>
              </div>
              <div className="flex-1 overflow-y-auto">
                <ModuleCardEditor
                  resumeId={resumeId}
                  modules={previewModules}
                  expandedType={expandedType}
                  onToggleExpand={(type) => setExpandedType((cur) => cur === type ? null : type)}
                  onChange={(type, content) => {
                    setPreviewModules((prev) =>
                      prev.map((m) => (m.module_type === type ? { ...m, content } : m))
                    );
                    setPreviewKey((k) => k + 1);
                  }}
                  onReorder={(ordered) => {
                    setPreviewModules((prev) =>
                      prev.map((m) => ({
                        ...m,
                        sort_order: ordered.indexOf(m.module_type),
                      }))
                    );
                  }}
                  onAdd={(type) => {
                    setPreviewModules((prev) => {
                      const maxOrder = prev.reduce((max, m) => Math.max(max, m.sort_order), -1);
                      return [...prev, {
                        id: -Date.now(),
                        resume_id: resumeId,
                        module_type: type,
                        content: {},
                        sort_order: maxOrder + 1,
                        created_at: new Date().toISOString(),
                      }];
                    });
                  }}
                  onRemove={(type) => {
                    setPreviewModules((prev) => prev.filter((m) => m.module_type !== type));
                  }}
                />
              </div>
            </div>
          ) : null}
        </div>

        {/* 右侧 50%：简历预览面板 */}
        {showPreview && resumeId > 0 && (
          <div className="w-1/2 border-l border-[var(--color-border)] overflow-hidden transition-all duration-300">
            <A4PreviewPanel
              resumeId={resumeId}
              previewKey={previewKey}
              collapsed={false}
              onToggleCollapse={() => setShowPreview(false)}
              modulesData={{
                modules: previewModules.map((m) => ({
                  module_type: m.module_type,
                  content: m.content,
                  sort_order: m.sort_order,
                })),
                style: previewStyle ?? ({} as ResumeStyle),
              }}
              onSelectSection={(moduleType) => {
                setEditingModule(moduleType);
                setExpandedType(moduleType);
              }}
            />
          </div>
        )}
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
        resumeId={resumeId}
        beforeModules={diffBeforeModules}
        afterModules={diffAfterModules}
        toolName={diffToolName}
        loading={diffLoading}
        onModulesSaved={handleDiffModulesSaved}
      />

      {/* ── v2: 版本历史弹窗 ── */}
      {showVersionHistory && resumeId > 0 && (
        <VersionHistoryDialog
          open={showVersionHistory}
          onClose={() => setShowVersionHistory(false)}
          resumeId={resumeId}
          resumeFilename={resume?.filename ?? "简历"}
        />
      )}

      {/* ── v2: 粘贴简历弹窗 ── */}
      {showPasteDialog && resumeId > 0 && (
        <PasteResumeDialog
          open={showPasteDialog}
          onClose={() => setShowPasteDialog(false)}
          onParsed={handlePasteParsed}
        />
      )}

      {/* ── P0-A: ATS 审计弹窗 ── */}
      {showAtsAudit && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
          <div className="bg-[var(--color-bg)] rounded-xl shadow-2xl w-full max-w-lg max-h-[80vh] overflow-y-auto p-6">
            {atsAuditLoading ? (
              <div className="text-center py-12">
                <div className="animate-spin w-8 h-8 border-2 border-[var(--color-accent)] border-t-transparent rounded-full mx-auto mb-4" />
                <div className="text-sm text-[var(--color-text-secondary)]">
                  正在执行 ATS 审计...
                </div>
              </div>
            ) : atsAuditResult ? (
              <AtsAuditReport
                result={atsAuditResult}
                onClose={() => setShowAtsAudit(false)}
              />
            ) : (
              <div className="text-center py-12">
                <div className="text-sm text-red-400">
                  ATS 审计失败，请稍后重试
                </div>
                <button
                  onClick={() => setShowAtsAudit(false)}
                  className="mt-4 px-4 py-2 rounded-lg bg-[var(--color-bg-secondary)] text-[var(--color-text-secondary)] text-sm hover:bg-[var(--color-bg-tertiary)]"
                >
                  关闭
                </button>
              </div>
            )}
          </div>
        </div>
      )}


      {/* ── v2: 样式面板（浮动覆盖在左侧） ── */}
      {showStylePanel && (
        <div className="absolute inset-y-0 left-0 z-40 shadow-2xl">
          <StylePanel
            style={previewStyle ?? ({} as ResumeStyle)}
            onChange={(newStyle) => {
              setPreviewStyle(newStyle);
              setPreviewKey((k) => k + 1);
            }}
            show={showStylePanel}
            onToggle={() => setShowStylePanel(false)}
            modules={previewModules}
            onReorderModules={(orderedTypes) => {
              setPreviewModules((prev) =>
                prev.map((m) => ({
                  ...m,
                  sort_order: orderedTypes.indexOf(m.module_type),
                }))
              );
              setPreviewKey((k) => k + 1);
            }}
          />
        </div>
      )}
    </div>
  );
}
