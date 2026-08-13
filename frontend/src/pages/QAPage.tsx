import { useEffect, useState, useRef, useCallback, useMemo } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useAppChat } from "../context/AppChatContext";
import { useToast } from "../components/Toast";
// D1 工具审批门：决议经独立端点回传（SSE 单向流无法在流内回传）
import { api } from "../api/client";
import { BadgeCheck, Check, ChevronLeft, ClipboardPaste, History, Paintbrush, Pencil, Save, ScanSearch, Target, X } from "lucide-react";
import { AnimatePresence, motion } from "framer-motion";
import {
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
  injectToActiveTurn,
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
  type ResumeModule,
  type ResumeStyle,
  type ModuleType,
  type ResumeModuleInput,
} from "../api/builder";
import { confirmUnsavedChanges, registerUnsavedChangesGuard } from "../utils/unsavedChanges";
import { A4PreviewPanel } from "../components/builder/A4PreviewPanel";
import { ModuleCardEditor } from "../components/builder/ModuleCardEditor";
import ConfirmDialog from "../components/ConfirmDialog";
import { CompareSelectDialog } from "../components/CompareSelectDialog";
import { getToolLabel } from "../components/chat/AgentProcessPanel";
import MessageBubble from "../components/chat/MessageBubble";
import WelcomeState from "../components/chat/WelcomeState";
import ChatNavbar from "../components/chat/ChatNavbar";
import { type ChatMessage, normalizeHistorySources } from "../components/chat/ChatMessage";
import { type GuideCard } from "../components/chat/GuideCards";
import { useAgentStream, type ApprovalRequest } from "../components/chat/useAgentStream";
import { useChatScroll } from "../components/chat/useChatScroll";
import ResumeEditDiffDialog from "../components/ResumeEditDiffDialog";
import AtsAuditReport from "../components/AtsAuditReport";
import ChatInput from "../components/chat/ChatInput";
import VersionHistoryDialog from "../components/VersionHistoryDialog";
import PasteResumeDialog from "../components/builder/PasteResumeDialog";
import { StylePanel } from "../components/builder/StylePanel";

export default function QAPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const {
    resumeId: ctxResumeId,
    setResumeId: setCtxResumeId,
    setConversations: setCtxConversations,
    setActiveConversationId: setCtxActiveConvId,
    setConversationLoading: setCtxConvLoading,
  } = useAppChat();

  // 自动选择简历：QAPage 在 / 路由下无 URL 参数，需自动选取第一份简历
  const [resumeId, setResumeId] = useState<number>(0);

  // ── AI 能力入口 / 快捷操作：location.state 携带的待触发问题 ──
  // pendingTriggerQuestion：resumeId 就绪后由 effect 统一发送一次（发送后置空，防重复）
  // consumedStateRef：标记已消费的 location.state 引用，防 effect 因 asking/resumeId 变化重入
  const [pendingTriggerQuestion, setPendingTriggerQuestion] = useState<string | null>(null);
  const [pendingNewTask, setPendingNewTask] = useState(false);
  const taskConversationPromiseRef = useRef<Promise<void> | null>(null);
  const [pendingToolHint, setPendingToolHint] = useState<string | null>(null);
  const consumedStateRef = useRef<unknown>(null);
  // 侧边栏跳转带来的"待选会话"：对话加载完成后优先选中（仅在列表中存在时）
  const pendingConversationIdRef = useRef<number | null>(null);

  const [resume, setResume] = useState<ResumeItem | null>(null);
  // 简历列表（顶栏切换简历/会话用；多简历时对话按简历隔离，可在此切换）
  const [resumeOptions, setResumeOptions] = useState<ResumeItem[]>([]);
  const [chat, setChat] = useState<ChatMessage[]>([]);
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState("");
  const [qaInitState, setQaInitState] = useState<"empty" | "creating" | "loading" | "ready" | "error">("empty");
  const [builderReadyId, setBuilderReadyId] = useState(0);
  const [qaInitRetry, setQaInitRetry] = useState(0);

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

  // Task 4：搜索 + 删除相关状态
  const [keyword, setKeyword] = useState("");
  const [debouncedKeyword, setDebouncedKeyword] = useState("");
  const [historyLoading, setHistoryLoading] = useState(false);
  const [clearConfirmOpen, setClearConfirmOpen] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [deletingId, setDeletingId] = useState<number | string | null>(null);

  // D1: 工具审批弹窗状态（收到 approval_request 事件触发，复用 ConfirmDialog）
  const [approvalRequest, setApprovalRequest] = useState<ApprovalRequest | null>(null);

  // T19: 对比弹窗 + JD 输入 + 附件上传
  const [compareOpen, setCompareOpen] = useState(false);
  const [compareIds, setCompareIds] = useState<number[]>([]);
  const [jdOpen, setJdOpen] = useState(false);
  const [jdText, setJdText] = useState("");

  // v2: 简历预览面板（右侧抽屉，默认隐藏，点击展开）
  const [showPreview, setShowPreview] = useState(false);
  const [previewCollapsed, setPreviewCollapsed] = useState(false);
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
  // 保存并完成后的确认弹窗（用户反馈：保存后无任何反馈/弹窗）
  const [showSaveCompleteDialog, setShowSaveCompleteDialog] = useState(false);
  const toast = useToast();

  // P0-A: ATS 审计弹窗
  const [showAtsAudit, setShowAtsAudit] = useState(false);
  const [atsAuditResult, setAtsAuditResult] = useState<AtsAuditResult | null>(null);
  const [atsAuditLoading, setAtsAuditLoading] = useState(false);
  const lockTokenRef = useRef<string | null>(null);
  const modulesRefreshTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const diffFetchTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const diffOwnerTokenRef = useRef(0);
  const modulesRef = useRef(previewModules);
  const styleRef = useRef(previewStyle);
  const [isDirty, setIsDirty] = useState(false);
  const dirtyRef = useRef(false);
  const editRevisionRef = useRef(0);
  const activeResumeIdRef = useRef(resumeId);
  const manualSaveTokenRef = useRef(0);
  const manualSaveOwnerRef = useRef<{ token: number; resumeId: number } | null>(null);
  useEffect(() => { modulesRef.current = previewModules; }, [previewModules]);
  useEffect(() => { styleRef.current = previewStyle; }, [previewStyle]);

  const markDirty = useCallback(() => {
    editRevisionRef.current += 1;
    dirtyRef.current = true;
    setIsDirty(true);
  }, []);

  const clearDirty = useCallback((savedResumeId: number, savedRevision?: number) => {
    if (activeResumeIdRef.current !== savedResumeId) return false;
    if (savedRevision !== undefined && editRevisionRef.current !== savedRevision) return false;
    dirtyRef.current = false;
    setIsDirty(false);
    return true;
  }, []);

  useEffect(() => registerUnsavedChangesGuard(
    () => !dirtyRef.current || window.confirm("当前简历有未保存的修改，确定离开并放弃这些修改吗？"),
  ), []);

  useEffect(() => {
    const handleBeforeUnload = (event: BeforeUnloadEvent) => {
      if (!dirtyRef.current) return;
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, []);

  // 切换简历立即废弃旧草稿状态和 timer；异步回调还会用 activeResumeIdRef 二次校验。
  useEffect(() => {
    activeResumeIdRef.current = resumeId;
    diffOwnerTokenRef.current += 1;
    if (diffFetchTimerRef.current) {
      clearTimeout(diffFetchTimerRef.current);
      diffFetchTimerRef.current = null;
    }
    manualSaveTokenRef.current += 1;
    manualSaveOwnerRef.current = null;
    editRevisionRef.current = 0;
    dirtyRef.current = false;
    setIsDirty(false);
    setSaving(false);
    setSaveStatus("idle");
    return () => {
      diffOwnerTokenRef.current += 1;
      if (diffFetchTimerRef.current) {
        clearTimeout(diffFetchTimerRef.current);
        diffFetchTimerRef.current = null;
      }
    };
  }, [resumeId]);
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
  const [diffResumeId, setDiffResumeId] = useState(0);
  const diffOwnerRef = useRef<{ resumeId: number; revision: number } | null>(null);

  const ownsCurrentDiff = useCallback(() => {
    const owner = diffOwnerRef.current;
    return owner !== null
      && owner.resumeId === activeResumeIdRef.current
      && owner.revision === editRevisionRef.current;
  }, []);

  const setOwnedDiffBeforeModules = useCallback((modules: ResumeModule[] | null) => {
    const owner = {
      resumeId: activeResumeIdRef.current,
      revision: editRevisionRef.current,
    };
    diffOwnerRef.current = owner;
    setDiffResumeId(owner.resumeId);
    setDiffBeforeModules(modules);
  }, []);
  const setOwnedDiffAfterModules = useCallback((modules: ResumeModule[] | null) => {
    if (ownsCurrentDiff()) setDiffAfterModules(modules);
  }, [ownsCurrentDiff]);
  const setOwnedDiffToolName = useCallback((toolName: string) => {
    if (ownsCurrentDiff()) setDiffToolName(toolName);
  }, [ownsCurrentDiff]);
  const setOwnedDiffLoading = useCallback((loading: boolean) => {
    if (ownsCurrentDiff()) setDiffLoading(loading);
  }, [ownsCurrentDiff]);
  const setOwnedDiffDialogOpen = useCallback((open: boolean) => {
    if (!open || ownsCurrentDiff()) setDiffDialogOpen(open);
  }, [ownsCurrentDiff]);

  useEffect(() => {
    diffOwnerRef.current = null;
    setDiffDialogOpen(false);
    setDiffLoading(false);
  }, [resumeId]);

  // G 功能：diff 弹窗里逐条还原后保存，落库结果回填预览模块 + before 快照
  const handleDiffModulesSaved = useCallback((modules: ResumeModule[]) => {
    const owner = diffOwnerRef.current;
    if (!owner || owner.resumeId !== activeResumeIdRef.current || owner.revision !== editRevisionRef.current) return;
    setPreviewModules(modules);
    modulesRef.current = modules;
    setDiffAfterModules(modules);
    beforeModulesRef.current = modules;
    clearDirty(owner.resumeId, owner.revision);
  }, [clearDirty]);

  // ── A4PreviewPanel props 稳定化（配合组件 memo） ──
  // agent_thought / tool_stream 高频刷新时 chat 变化触发 QAPage 重渲染，
  // 但 previewModules/previewStyle 未变时预览面板（简历渲染很重）不应跟着重渲染。
  // 必须保证 modulesData 与回调引用稳定，否则 memo 失效。
  const previewModulesData = useMemo(
    () => ({
      modules: previewModules.map((m) => ({
        module_type: m.module_type,
        content: m.content,
        sort_order: m.sort_order,
      })),
      style: previewStyle ?? ({} as ResumeStyle),
    }),
    [previewModules, previewStyle],
  );
  const handleClosePreview = useCallback(() => {
    setShowPreview(false);
    setPreviewCollapsed(false);
    setEditingModule(null);
    setExpandedType(null);
  }, []);
  const handleOpenPreview = useCallback(() => {
    setShowPreview(true);
    setPreviewCollapsed(false);
  }, []);
  const handleSelectSection = useCallback((moduleType: ModuleType) => {
    setEditingModule(moduleType);
    setExpandedType(moduleType);
  }, []);

  // 打开分屏时加载预览 HTML
  // ── 自动选择简历 ──
  // QAPage 在 / 路由下无 URL 参数，需自动选取一份简历。
  // 优先沿用 context 中已选中的简历（用户上次在 QA / 侧边栏的选择），
  // 否则拉取列表选第一份 ready/partial 简历。
  useEffect(() => {
    if (resumeId > 0) return;
    // 简历管理页点击带过来的 resumeId 最优先（否则会被 ctx 或自动选取覆盖，
    // 表现为"点击简历不会自动切换"）
    const stateResumeId = (location.state as { resumeId?: number } | null)?.resumeId;
    if (stateResumeId && stateResumeId > 0) {
      setResumeId(stateResumeId);
      return;
    }
    if (ctxResumeId && ctxResumeId > 0) {
      setResumeId(ctxResumeId);
      return;
    }
    let cancelled = false;
    listResumes(50, 0).then((data) => {
      if (cancelled) return;
      if (data.items.length > 0) {
        // 优先选择 ready/partial 状态的简历，否则选第一份
        const ready = data.items.find((r) => r.status === "ready" || r.status === "partial");
        // 守卫：resumeId 已被 state/ctx 设置时不再覆盖（异步返回晚于挂载）
        setResumeId((prev) => (prev > 0 ? prev : (ready ?? data.items[0]).id));
      }
    }).catch(() => {
      if (activeResumeIdRef.current === resumeId) {
        setQaInitState("error");
        setPendingAiCreateQuestion(null);
        setError("简历加载失败，请重试");
      }
    });
    return () => { cancelled = true; };
  }, [resumeId, ctxResumeId, location.state]);

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

  // ── 改写类工具（rewrite_star/translate/rewrite_resume）写库后：QAPage 自身也刷新 ──
  // 本页是 dispatch 方（agent_done 时），但内嵌编辑面板（previewModules）不监听
  // 刷新事件 → 「整份改写不回填表单」根因。监听后延迟拉取最新模块回填预览面板。
  useEffect(() => {
    const syncPreview = () => {
      if (!resumeId || resumeId <= 0) return;
      const requestRevision = editRevisionRef.current;
      // 延迟 500ms 等待 DB 提交完成（与 dispatch 侧注释同模式）
      if (modulesRefreshTimerRef.current) clearTimeout(modulesRefreshTimerRef.current);
      modulesRefreshTimerRef.current = setTimeout(() => {
        modulesRefreshTimerRef.current = null;
        getBuilderResume(resumeId)
          .then((data) => {
            if (activeResumeIdRef.current !== resumeId || editRevisionRef.current !== requestRevision) return;
            const mods = data.modules ?? [];
            setPreviewModules(mods);
            modulesRef.current = mods;
            setPreviewStyle(data.style ?? null);
            styleRef.current = data.style ?? null;
            setVersion(data.version);
            clearDirty(resumeId);
          })
          .catch(() => {});
      }, 500);
    };
    window.addEventListener("resume:modules-refresh", syncPreview);
    return () => {
      window.removeEventListener("resume:modules-refresh", syncPreview);
      if (modulesRefreshTimerRef.current) {
        clearTimeout(modulesRefreshTimerRef.current);
        modulesRefreshTimerRef.current = null;
      }
    };
  }, [resumeId, clearDirty]);

  // ── 接收来自简历列表 / AI 能力入口 / 侧边栏会话的导航状态（resumeId / question / conversationId） ──
  useEffect(() => {
    const state = location.state as {
      resumeId?: number;
      question?: string;
      conversationId?: number;
      openPreview?: boolean;
      toolHint?: string;
      newTask?: boolean;
    } | null;
    if (!state?.resumeId && !state?.question && !state?.conversationId) return;
    // 防重入：同一份 location.state 只消费一次（否则因 asking/resumeId 变化重复触发 → 死循环）
    if (consumedStateRef.current === location.state) return;
    consumedStateRef.current = location.state;

    if (state.resumeId) {
      setResumeId(state.resumeId);
      if (state.openPreview) setShowPreview(true);
    }
    // 侧边栏会话跳转：标记待选会话（对话加载完成后优先选中，防被 list[0] 覆盖）
    if (state.conversationId) {
      pendingConversationIdRef.current = state.conversationId;
      setActiveConversationId(state.conversationId);
    }
    // 缓存待触发问题，等 resumeId 就绪后由发送 effect 统一消费一次
    if (state.question) {
      setPendingTriggerQuestion(state.question);
      setPendingToolHint(state.toolHint ?? null);
      setPendingNewTask(Boolean(state.newTask));
    }
    // 正确清除 location.state（React Router 中 window.history.replaceState 无效，
    // 必须走 navigate 同路径 replace，否则 state.question 会一直残留触发重复发送）
    navigate(location.pathname, { replace: true, state: null });
  }, [location.state, location.pathname, navigate]);

  // 离开 QA（例如进入用户反馈）时结束加载态，避免 Sidebar 保持 spinner，
  // 同时保留 AppChatContext 中已加载的对话列表。
  useEffect(() => {
    return () => setCtxConvLoading(false);
  }, [setCtxConvLoading]);


  // Token 限额状态
  const [quota, setQuota] = useState<QuotaResponse | null>(null);

  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ── 实时滚动：useChatScroll 管理（chat 变化触发自动滚动到底部）──
  const { chatEndRef, scrollContainerRef, isNearBottomRef, checkNearBottom, scrollToBottom, scrolled } = useChatScroll(chat);

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
          // 顺序必须：历史（旧）在前，正在流式的新消息（新）在后。
          // 若反过来，从 AI 能力入口自动发送时新问题会插到历史前面显示在顶部。
          return [...historyItems, ...streamingMsgs];
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
    setBuilderReadyId(0);
    setQaInitState("loading");
    const requestRevision = editRevisionRef.current;
    listResumes().then((data) => {
      if (activeResumeIdRef.current !== resumeId) return;
      setResumeOptions(data.items);
      const r = data.items.find((item) => item.id === resumeId);
      if (r) setResume(r);
    });
    // v2: 加载预览模块数据
    getBuilderResume(resumeId).then((data) => {
      if (activeResumeIdRef.current !== resumeId || editRevisionRef.current !== requestRevision) return;
      const modules = data.modules ?? [];
      const style = data.style ?? null;
      setPreviewModules(modules);
      modulesRef.current = modules;
      setPreviewStyle(style);
      styleRef.current = style;
      setVersion(data.version);
      setBuilderReadyId(resumeId);
      clearDirty(resumeId);
    }).catch((err) => {
      if (activeResumeIdRef.current === resumeId) {
        setQaInitState("error");
        setError(err instanceof Error ? err.message : "加载简历失败");
      }
    });
  }, [resumeId, qaInitRetry, clearDirty]);

  useEffect(() => {
    if (qaInitState === "error" || qaInitState === "creating") return;
    if (resumeId <= 0) {
      setQaInitState("empty");
    } else if (builderReadyId === resumeId && !conversationLoading && activeConversationId != null) {
      setQaInitState("ready");
    } else {
      setQaInitState("loading");
    }
  }, [resumeId, builderReadyId, conversationLoading, activeConversationId, qaInitState]);

  // 顶栏切换简历：切换后 useEffect [resumeId] 重载该简历的对话/预览/锁
  // （对话按简历隔离，切换即切换会话；ctxResumeId 由下方 useEffect 自动同步）
  const handleSwitchResume = useCallback(
    (id: number) => {
      if (!id || id === resumeId) return;
      if (!confirmUnsavedChanges()) return;
      const r = resumeOptions.find((x) => x.id === id);
      if (!r) return;
      setResumeId(id);
      setResume(r);
      setChat([]); // 清当前消息，等待该简历对话重载
    },
    [resumeId, resumeOptions, setChat],
  );

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
    const savingResumeId = resumeId;
    const savingRevision = editRevisionRef.current;
    const requestToken = ++manualSaveTokenRef.current;
    manualSaveOwnerRef.current = { token: requestToken, resumeId: savingResumeId };
    const ownsRequest = () => manualSaveOwnerRef.current?.token === requestToken
      && manualSaveOwnerRef.current.resumeId === savingResumeId
      && activeResumeIdRef.current === savingResumeId;
    const ownsSavedRevision = () => ownsRequest() && editRevisionRef.current === savingRevision;
    setSaving(true);
    try {
      const result = await saveDraft(savingResumeId, {
        filename: resume.filename,
        modules: modulesRef.current.map((m) => ({
          module_type: m.module_type,
          content: m.content,
          sort_order: m.sort_order,
        })),
        style: styleRef.current ?? undefined,
      });
      if (!ownsSavedRevision()) return;
      setVersion(result.version);
      setSaveStatus("saved");
      setLastSaveMode("draft");
      if (clearDirty(savingResumeId, savingRevision)) {
        setResume((current) => current?.id === savingResumeId ? { ...current, status: "draft" } : current);
        setResumeOptions((items) => items.map((item) => item.id === savingResumeId ? { ...item, status: "draft" } : item));
      }
      toast.success("草稿已保存"); // 用户反馈：保存无任何反馈
    } catch (e) {
      if (!ownsRequest()) return;
      setSaveStatus("error");
      toast.error(e instanceof Error ? e.message : "保存草稿失败");
    } finally {
      if (ownsRequest()) {
        manualSaveOwnerRef.current = null;
        setSaving(false);
      }
    }
  }, [resume, resumeId, toast, clearDirty]);

  // v2: 保存并完成
  const handleSaveComplete = useCallback(async () => {
    if (!resume) return;
    const savingResumeId = resumeId;
    const savingRevision = editRevisionRef.current;
    const requestToken = ++manualSaveTokenRef.current;
    manualSaveOwnerRef.current = { token: requestToken, resumeId: savingResumeId };
    const ownsRequest = () => manualSaveOwnerRef.current?.token === requestToken
      && manualSaveOwnerRef.current.resumeId === savingResumeId
      && activeResumeIdRef.current === savingResumeId;
    const ownsSavedRevision = () => ownsRequest() && editRevisionRef.current === savingRevision;
    setSaving(true);
    try {
      const result = await saveComplete(savingResumeId, version, {
        filename: resume.filename,
        modules: modulesRef.current.map((m) => ({
          module_type: m.module_type,
          content: m.content,
          sort_order: m.sort_order,
        })),
        style: styleRef.current ?? undefined,
      });
      if (!ownsSavedRevision()) return;
      setVersion(result.version);
      setSaveStatus("saved");
      setLastSaveMode("complete");
      clearDirty(savingResumeId, savingRevision);
      setResume((current) => current?.id === savingResumeId ? { ...current, status: "ready" } : current);
      setResumeOptions((items) => items.map((item) => item.id === savingResumeId ? { ...item, status: "ready" } : item));
      toast.success("已保存并完成，可开始问答/检索");
      // 完成弹窗：确认保存成功 + 引导下一步（用户反馈：完成后应有弹窗）
      setShowSaveCompleteDialog(true);
    } catch (e) {
      if (!ownsRequest()) return;
      setSaveStatus("error");
      toast.error(e instanceof Error ? e.message : "保存失败");
    } finally {
      if (ownsRequest()) {
        manualSaveOwnerRef.current = null;
        setSaving(false);
      }
    }
  }, [resume, resumeId, version, toast, clearDirty]);

  // v2: 粘贴简历回调
  const handlePasteParsed = useCallback((parsedModules: ResumeModuleInput[], parsedFilename?: string) => {
    const newModules: ResumeModule[] = parsedModules.map((m, i) => ({
      id: -Date.now() - i,
      resume_id: resumeId,
      module_type: m.module_type,
      content: m.content,
      sort_order: m.sort_order,
      created_at: new Date().toISOString(),
    }));
    setPreviewModules(newModules);
    modulesRef.current = newModules;
    if (parsedFilename) {
      setResume((current) => current ? { ...current, filename: parsedFilename } : current);
      setResumeOptions((items) => items.map((item) =>
        item.id === resumeId ? { ...item, filename: parsedFilename } : item,
      ));
    }
    markDirty();
  }, [resumeId, markDirty]);

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
        // 侧边栏跳转带来的"待选会话"优先：仅在列表中存在时才选中，否则回退默认
        if (pendingConversationIdRef.current != null) {
          const target = list.find((c) => c.id === pendingConversationIdRef.current);
          pendingConversationIdRef.current = null;
          if (target) {
            setConversations(list);
            setActiveConversationId(target.id);
            return;
          }
        }
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
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "加载对话列表失败");
          setQaInitState("error");
        }
      })
      .finally(() => {
        if (!cancelled) setConversationLoading(false);
      });
    return () => { cancelled = true; };
  }, [resumeId, qaInitRetry]);

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

  // ── SSE 流式状态机：useAgentStream（G1 handlers / rAF 节流 / sendQuestion 收敛于 hook）──
  // 依赖快照每渲染刷新（getDeps），sendQuestion 稳定引用，行为与旧实现完全一致。
  const { sendQuestion, abortRef } = useAgentStream(() => ({
    resumeId,
    activeConversationId,
    compareIds,
    aiCreateMode,
    setAiCreateMode,
    navigate,
    setResumeId,
    setPendingAiCreateQuestion,
    setQaInitState,
    setChat,
    setAsking,
    setError,
    setApprovalRequest,
    setConversations,
    setQuota,
    beforeModulesRef,
    activeResumeIdRef,
    editRevisionRef,
    diffOwnerTokenRef,
    diffFetchTimerRef,
    setDiffBeforeModules: setOwnedDiffBeforeModules,
    setDiffAfterModules: setOwnedDiffAfterModules,
    setDiffToolName: setOwnedDiffToolName,
    setDiffLoading: setOwnedDiffLoading,
    setDiffDialogOpen: setOwnedDiffDialogOpen,
    isNearBottomRef,
    scrollToBottom,
  }));

  // ── AI 能力入口 / 快捷操作：待触发问题在 resumeId + 会话就绪后自动发送一次 ──
  // 发送后立即清空 pendingTriggerQuestion，配合 location.state 的正确清除，
  // 彻底避免 asking 变化导致的重复发送死循环（只发一次，不随 asking 往返重入）。
  // activeConversationId 条件：等对话加载自动创建/选中第一个会话后再发，
  // 确保这条问答的历史存入该会话（否则 conversation_id 为空导致历史不落库）。
  useEffect(() => {
    if (resumeId <= 0 || !pendingTriggerQuestion || asking) return;
    if (qaInitState !== "ready" || builderReadyId !== resumeId) return;
    if (activeConversationId == null) return; // 会话未就绪，等待
    if (pendingNewTask) {
      if (taskConversationPromiseRef.current) return;
      taskConversationPromiseRef.current = createConversation(resumeId)
        .then((conv) => {
          if (activeResumeIdRef.current !== resumeId) return;
          setConversations((prev) => [conv, ...prev]);
          setActiveConversationId(conv.id);
          setChat([]);
          setKeyword("");
          setDebouncedKeyword("");
          setPendingNewTask(false);
        })
        .catch((err) => {
          setPendingTriggerQuestion(null);
          setPendingToolHint(null);
          setPendingNewTask(false);
          setError(err instanceof Error ? err.message : "创建任务对话失败");
        })
        .finally(() => {
          taskConversationPromiseRef.current = null;
        });
      return;
    }
    const q = pendingTriggerQuestion;
    const toolHint = pendingToolHint;
    setPendingTriggerQuestion(null);
    setPendingToolHint(null);
    // 特殊指令拦截：__COMPARE__ → 打开「多选简历」选择器，而非发给 Agent
    // （用户反馈：简历对比不应要求输入简历 id）
    if (q === "__COMPARE__") {
      setCompareOpen(true);
      return;
    }
    sendQuestion(q, toolHint ? { toolHint } : undefined);
  }, [resumeId, pendingTriggerQuestion, pendingToolHint, pendingNewTask, asking, activeConversationId, builderReadyId, qaInitState, sendQuestion]);

  // ── AI 创建简历：resumeId 更新后发送待发送的问题 ──
  useEffect(() => {
    if (resumeId > 0 && pendingAiCreateQuestion && builderReadyId === resumeId && !conversationLoading && activeConversationId != null && qaInitState === "ready") {
      const q = pendingAiCreateQuestion;
      setPendingAiCreateQuestion(null);
      // 延迟一点确保 state 更新完成
      sendQuestion(q);
    }
  }, [resumeId, pendingAiCreateQuestion, builderReadyId, conversationLoading, activeConversationId, qaInitState, sendQuestion]);

  // ChatInput 提交回调：trim 后触发发送（asking 时忽略）
  const handleSendText = useCallback(
    (text: string) => {
      const q = text.trim();
      if (!q || asking) return;
      if (qaInitState === "error") {
        if (resumeId <= 0) {
          sendQuestion(q);
          return;
        }
        setQaInitState("loading");
        setQaInitRetry((v) => v + 1);
        setPendingTriggerQuestion(q);
        return;
      }
      sendQuestion(q);
    },
    [asking, qaInitState, resumeId, sendQuestion]
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

  // D1: 提交工具审批决议（approved / denied）→ POST 独立端点回传后端
  const handleApprovalDecision = useCallback(
    (decision: "approved" | "denied") => {
      const current = approvalRequest;
      if (!current) return;
      setApprovalRequest(null); // 立即关闭弹窗，等待后端 tool_result/tool_error
      api.post("/api/v1/qa/approval", {
        approval_id: current.approvalId,
        decision,
      }).catch((e) => {
        setError(e instanceof Error ? e.message : "审批决议提交失败，请重试");
      });
    },
    [approvalRequest]
  );

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

  // G2: 重新生成 — 重新发送该消息的问题触发新一轮回答（复用现有 sendQuestion 重发逻辑）
  const handleRegenerate = useCallback(
    (msg: ChatMessage) => {
      if (asking) return;
      sendQuestion(msg.question);
    },
    [asking, sendQuestion]
  );

  // ── P1-2: asking 期间补充信息 → 注入当前活跃回合（而非排队新回合） ──
  const handleInjectMessage = useCallback(
    (text: string) => {
      if (!resumeId || resumeId <= 0) return;
      const content = text.trim();
      if (!content) return;
      injectToActiveTurn(resumeId, content, activeConversationId ?? undefined)
        .then((result) => {
          if (result.status === "restarting") {
            toast.success("已收到，正在重答");
          } else if (result.status === "queued") {
            toast.success("已收到，将在下一轮处理");
          } else if (result.status === "accepted") {
            toast.success("已生效");
          } else {
            toast.error("补充信息未生效");
          }
        })
        .catch((e) => {
          toast.error(e instanceof Error ? e.message : "补充信息失败");
        });
    },
    [resumeId, activeConversationId, toast]
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
  const handleGuideClick = useCallback(
    (card: Pick<GuideCard, "navigate" | "question">) => {
      if (asking) return;
      if (card.navigate) {
        if (!confirmUnsavedChanges()) return;
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
    const allIds = [resumeId, ...selectedIds.filter((id) => id !== resumeId)];
    setCompareIds(allIds);
    setCompareOpen(false);
    sendQuestion("请以当前简历为基准，对比我选中的其他简历，分析各自的优劣势", { compareIds: allIds });
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
      {/* ── 顶栏（ChatNavbar：Open WebUI Navbar 风格，滚动渐变背景） ── */}
      <ChatNavbar
        scrolled={scrolled}
        resumeId={resumeId}
        resumeOptions={resumeOptions}
        resume={resume}
        onSwitchResume={handleSwitchResume}
        conversationTitle={
          !conversationLoading && activeConversationId
            ? conversations.find((c) => c.id === activeConversationId)?.title ?? "新对话"
            : undefined
        }
        compareCount={compareIds.length}
        onCompareClick={() => setCompareOpen(true)}
        quota={quota}
        keyword={keyword}
        onKeywordChange={setKeyword}
        onClearKeyword={() => setKeyword("")}
        searchDisabled={asking}
        chatCount={chat.length}
        clearing={clearing}
        asking={asking}
        onClearHistory={() => setClearConfirmOpen(true)}
        canPreview={resumeId > 0 && previewModules.length > 0}
        showPreview={showPreview}
        onTogglePreview={() => (showPreview ? handleClosePreview() : handleOpenPreview())}
      />


      {/* ── 主体：聊天区（全宽；预览走右侧抽屉，不再占用聊天空间） ── */}
      <div className="flex-1 flex flex-col overflow-hidden">
        <div
          ref={scrollContainerRef}
          onScroll={checkNearBottom}
          className="flex-1 overflow-y-auto px-4 sm:px-6 py-6"
        >
          <div className="max-w-[58rem] mx-auto">
            {historyLoading && chat.length === 0 && resumeId > 0 ? (
              <div className="flex flex-col items-center justify-center py-16">
                <span className="inline-block w-6 h-6 rounded-full border-2 border-brand border-t-transparent animate-spin" />
                <p className="text-xs text-[var(--color-text-muted)] mt-3">加载历史中...</p>
              </div>
            ) : chat.length === 0 ? (
              <WelcomeState
                searching={debouncedKeyword.length > 0}
                asking={asking}
                onGuideClick={handleGuideClick}
                hasResume={resumeId > 0}
              />
            ) : (
              chat.map((msg, idx) => (
                <MessageBubble
                  key={String(msg.id)}
                  msg={msg}
                  deleting={deletingId === msg.id}
                  onDelete={handleDeleteMessage}
                  onFeedback={handleFeedback}
                  onRegenerate={handleRegenerate}
                  asking={asking}
                  searchTerm={debouncedKeyword}
                  isLast={idx === chat.length - 1}
                />
              ))
            )}
            {error && (
              <div className="max-w-[58rem] mx-auto mb-4 p-3 rounded-list bg-danger-soft border border-danger/30 text-danger text-sm animate-shake">
                {error}
              </div>
            )}
            <div ref={chatEndRef} />
          </div>
        </div>
        {/* 聊天输入框 */}
        <div className="shrink-0 border-t border-[var(--color-border)]">
          <ChatInput
            asking={asking}
            uploading={uploading}
              disabled={!resumeId || resumeId === 0 || qaInitState === "creating" || qaInitState === "loading"}
            onSend={handleSendText}
            onInject={handleInjectMessage}
            onCancel={handleCancel}
            onQuickTag={(q) => {
              if (!asking) sendQuestion(q);
            }}
            onFile={handleUploadFile}
          />
        </div>
      </div>

      {/* ── 简历预览抽屉（右侧，默认隐藏） ── */}
      <AnimatePresence>
        {showPreview && resumeId > 0 && (
          <>
            <div
              className="fixed inset-0 z-40 bg-black/20 backdrop-blur-sm"
              onClick={handleClosePreview}
              aria-hidden="true"
            />
            <motion.aside
              initial={{ x: "100%" }}
              animate={{ x: 0 }}
              exit={{ x: "100%" }}
              transition={{ type: "spring", stiffness: 260, damping: 30 }}
              className={`fixed top-0 right-0 z-50 h-full ${previewCollapsed ? "w-12" : "w-[min(720px,90vw)]"}
                border-l border-[var(--color-border)] bg-[var(--color-bg)] shadow-2xl flex flex-col`}
              aria-label="简历预览"
            >
              {/* 抽屉头部 */}
              <div className={`${previewCollapsed ? "hidden" : ""} shrink-0 px-4 py-3 border-b border-[var(--color-border)]
                flex items-center justify-between gap-2`}>
                <div className="min-w-0 flex items-center gap-2">
                  {editingModule && (
                    <button
                      onClick={() => setEditingModule(null)}
                      className="shrink-0 inline-flex items-center gap-1 text-xs text-brand hover:text-brand/80 font-medium cursor-pointer"
                    >
                      <ChevronLeft size={14} strokeWidth={2.25} aria-hidden="true" />
                      返回预览
                    </button>
                  )}
                  <span className="text-sm font-semibold text-[var(--color-text)] truncate">
                    {editingModule ? `编辑 ${editingModule}` : "简历预览"}
                  </span>
                </div>
                <button
                  onClick={handleClosePreview}
                  aria-label="关闭预览"
                  className="shrink-0 p-1.5 rounded-action text-[var(--color-text-secondary)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-secondary)] active:scale-95 motion-reduce:active:scale-100 transition-all cursor-pointer"
                >
                  <X size={16} strokeWidth={2.25} aria-hidden="true" />
                </button>
              </div>

              {/* 内容：模块编辑 或 预览 */}
              <div className="flex-1 overflow-y-auto">
                {editingModule ? (
                  <ModuleCardEditor
                    resumeId={resumeId}
                    modules={previewModules}
                    expandedType={expandedType}
                    onToggleExpand={(type) => setExpandedType((cur) => cur === type ? null : type)}
                    onChange={(type, content) => {
                      setPreviewModules((prev) =>
                        prev.map((m) => (m.module_type === type ? { ...m, content } : m))
                      );
                      markDirty();
                      setPreviewKey((k) => k + 1);
                    }}
                    onReorder={(ordered) => {
                      setPreviewModules((prev) =>
                        prev.map((m) => ({
                          ...m,
                          sort_order: ordered.indexOf(m.module_type),
                        }))
                      );
                      markDirty();
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
                      markDirty();
                    }}
                    onRemove={(type) => {
                      setPreviewModules((prev) => prev.filter((m) => m.module_type !== type));
                      markDirty();
                    }}
                  />
                ) : (
                  <A4PreviewPanel
                    resumeId={resumeId}
                    previewKey={previewKey}
                    collapsed={previewCollapsed}
                    onToggleCollapse={handleClosePreview}
                    modulesData={previewModulesData}
                    onSelectSection={handleSelectSection}
                  />
                )}
              </div>

              {/* 抽屉底部：工具 + 保存操作条 */}
              <div className={`${previewCollapsed ? "hidden" : ""} shrink-0 border-t border-[var(--color-border)] px-4 py-3 flex items-center justify-between gap-2 flex-wrap`}>
                <div className="flex items-center gap-1">
                  <button
                    onClick={() => setShowPasteDialog(true)}
                    title="粘贴导入"
                    aria-label="粘贴导入"
                    className="p-2 rounded-action text-[var(--color-text-muted)] hover:text-brand hover:bg-brand/10 transition-all cursor-pointer"
                  >
                    <ClipboardPaste size={17} aria-hidden="true" />
                  </button>
                  <button
                    onClick={() => setShowStylePanel(true)}
                    title="样式"
                    aria-label="样式"
                    className="p-2 rounded-action text-[var(--color-text-muted)] hover:text-brand hover:bg-brand/10 transition-all cursor-pointer"
                  >
                    <Paintbrush size={17} aria-hidden="true" />
                  </button>
                  <button
                    onClick={() => setShowVersionHistory(true)}
                    title="版本历史"
                    aria-label="版本历史"
                    className="p-2 rounded-action text-[var(--color-text-muted)] hover:text-brand hover:bg-brand/10 transition-all cursor-pointer"
                  >
                    <History size={17} aria-hidden="true" />
                  </button>
                  <button
                    onClick={handleAtsAudit}
                    title="ATS 审计"
                    aria-label="ATS 审计"
                    className="p-2 rounded-action text-[var(--color-text-muted)] hover:text-brand hover:bg-brand/10 transition-all cursor-pointer"
                  >
                    <ScanSearch size={17} aria-hidden="true" />
                  </button>
                </div>
                <div className="flex items-center gap-2">
                  {isDirty && !saving && (
                    <span className="text-xs font-medium text-warning" role="status">
                      未保存
                    </span>
                  )}
                  {saving && (
                    <span className="text-xs text-[var(--color-text-muted)]" role="status">
                      保存中…
                    </span>
                  )}
                  <button
                    onClick={handleSaveDraft}
                    disabled={saving}
                    className="shrink-0 inline-flex items-center gap-1.5 px-4 py-2 rounded-full text-sm font-medium border border-[var(--color-border)] text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-secondary)] disabled:opacity-50 transition-all cursor-pointer"
                  >
                    <Save size={15} aria-hidden="true" />
                    保存草稿
                  </button>
                  <button
                    onClick={handleSaveComplete}
                    disabled={saving}
                    className="shrink-0 inline-flex items-center gap-1.5 px-4 py-2 rounded-full text-sm font-semibold bg-brand text-white hover:bg-brand/90 disabled:opacity-50 transition-all cursor-pointer"
                  >
                    <BadgeCheck size={15} aria-hidden="true" />
                    保存并完成
                  </button>
                </div>
              </div>
            </motion.aside>
          </>
        )}
      </AnimatePresence>

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

      {/* ── D1: 工具审批确认弹窗（Agent 请求执行写类工具前征求用户同意） ── */}
      <ConfirmDialog
        open={Boolean(approvalRequest)}
        title={`确认执行：${getToolLabel(approvalRequest?.toolName ?? "")}`}
        description={approvalRequest
          ? `系统准备执行“${getToolLabel(approvalRequest.toolName)}”。该操作可能更新当前简历或创建业务记录；确认后才会执行，你也可以暂不执行并继续对话。`
          : ""}
        confirmText="确认执行"
        cancelText="暂不执行"
        onConfirm={() => handleApprovalDecision("approved")}
        onCancel={() => handleApprovalDecision("denied")}
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
                <div className="p-1.5 rounded-action bg-brand/10 text-brand">
                  <Pencil size={18} strokeWidth={2.25} aria-hidden="true" />
                </div>
                <h3 className="text-base font-semibold text-[var(--color-text)]">
                  重命名对话
                </h3>
              </div>
              <button
                onClick={() => setRenameOpen(false)}
                aria-label="关闭"
                className="p-1.5 rounded-action text-[var(--color-text-secondary)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-secondary)] active:scale-[0.95] motion-reduce:active:scale-100 transition-all cursor-pointer"
              >
                <X size={16} strokeWidth={2.25} aria-hidden="true" />
              </button>
            </div>
            <input
              value={renameValue}
              onChange={(e) => setRenameValue(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") handleRenameConfirm(); }}
              placeholder="输入对话标题"
              maxLength={100}
              autoFocus
              className="w-full px-4 py-3 rounded-list text-sm text-[var(--color-text)]
                bg-[#F2F2F7] border border-transparent
                placeholder:text-[var(--color-text-muted)]
                focus:outline-none focus:ring-2 focus:ring-brand/40 focus:border-brand/50 focus:bg-white
                transition-all duration-200"
            />
            <div className="flex justify-end gap-2 mt-4">
              <button
                onClick={() => setRenameOpen(false)}
                className="px-3.5 py-1.5 text-sm font-medium rounded-full bg-[#E5E5EA] text-[var(--color-text)] hover:bg-[var(--color-bg-secondary)] active:scale-[0.98] motion-reduce:active:scale-100 transition-all duration-300 cursor-pointer"
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
                <div className="p-1.5 rounded-action bg-brand/10 text-brand">
                  <Target size={18} strokeWidth={2.25} aria-hidden="true" />
                </div>
                <h3 className="text-base font-semibold text-[var(--color-text)]">
                  粘贴岗位描述
                </h3>
              </div>
              <button
                onClick={() => setJdOpen(false)}
                aria-label="关闭"
                className="p-1.5 rounded-action text-[var(--color-text-secondary)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-secondary)] active:scale-[0.95] motion-reduce:active:scale-100 transition-all cursor-pointer"
              >
                <X size={16} strokeWidth={2.25} aria-hidden="true" />
              </button>
            </div>
            <textarea
              value={jdText}
              onChange={(e) => setJdText(e.target.value)}
              placeholder="粘贴目标岗位的 JD（Job Description），AI 将分析简历与岗位的匹配度..."
              rows={8}
              autoFocus
              className="w-full px-4 py-3 rounded-list text-sm text-[var(--color-text)]
                bg-[#F2F2F7] border border-transparent
                placeholder:text-[var(--color-text-muted)]
                focus:outline-none focus:ring-2 focus:ring-brand/40 focus:border-brand/50 focus:bg-white
                resize-none transition-all duration-200"
            />
            <div className="flex justify-end gap-2 mt-4">
              <button
                onClick={() => setJdOpen(false)}
                className="px-3.5 py-1.5 text-sm font-medium rounded-full bg-[#E5E5EA] text-[var(--color-text)] hover:bg-[var(--color-bg-secondary)] active:scale-[0.98] motion-reduce:active:scale-100 transition-all duration-300 cursor-pointer"
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
        onClose={() => setOwnedDiffDialogOpen(false)}
        resumeId={diffResumeId}
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
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
          onClick={() => setShowAtsAudit(false)}
        >
          <div
            className="bg-[var(--color-bg)] rounded-list shadow-2xl w-full max-w-lg max-h-[80vh] overflow-y-auto p-6 relative"
            onClick={(e) => e.stopPropagation()}
          >
            {/* 右上角 X 关闭（对齐其他弹窗交互） */}
            <button
              onClick={() => setShowAtsAudit(false)}
              aria-label="关闭 ATS 审计"
              className="absolute top-3 right-3 p-1.5 rounded-action text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-secondary)] transition-colors cursor-pointer"
            >
              <X size={16} strokeWidth={2.25} />
            </button>
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
                <div className="text-sm text-danger">
                  ATS 审计失败，请稍后重试
                </div>
                <button
                  onClick={() => setShowAtsAudit(false)}
                  className="mt-4 px-4 py-2 rounded-action bg-[var(--color-bg-secondary)] text-[var(--color-text-secondary)] text-sm hover:bg-[var(--color-bg-tertiary)]"
                >
                  关闭
                </button>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── 保存并完成确认弹窗 ── */}
      {showSaveCompleteDialog && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
          onClick={() => setShowSaveCompleteDialog(false)}
        >
          <div
            className="bg-[var(--color-bg)] rounded-list shadow-2xl w-full max-w-sm p-6"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="text-center">
              <div className="w-12 h-12 mx-auto rounded-full bg-success/10 flex items-center justify-center mb-3">
                <Check size={24} strokeWidth={2.25} className="text-success" />
              </div>
              <div className="text-base font-semibold text-[var(--color-text)]">
                简历已保存并完成
              </div>
              <div className="text-xs text-[var(--color-text-secondary)] mt-1.5 leading-relaxed">
                内容已合并并重建索引，Agent 问答与检索将使用最新简历内容。
              </div>
            </div>
            <div className="flex items-center gap-2 mt-5">
              <button
                onClick={() => setShowSaveCompleteDialog(false)}
                className="flex-1 px-4 py-2 rounded-action bg-[var(--color-bg-secondary)] text-[var(--color-text-secondary)] text-sm hover:bg-[var(--color-bg-tertiary)] transition-colors cursor-pointer"
              >
                继续编辑
              </button>
              <button
                onClick={() => {
                  setShowSaveCompleteDialog(false);
                  setShowPreview(false);
                  setEditingModule(null);
                  setExpandedType(null);
                }}
                className="flex-1 px-4 py-2 rounded-action bg-brand text-white text-sm hover:bg-brand-hover transition-colors cursor-pointer"
              >
                去问答
              </button>
            </div>
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
              markDirty();
              setPreviewKey((k) => k + 1);
            }}
            show={showStylePanel}
            onToggle={() => setShowStylePanel(false)}
          />
        </div>
      )}
    </div>
  );
}
