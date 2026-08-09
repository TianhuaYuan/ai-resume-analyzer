import {
  useEffect, useState, useRef, useCallback, useMemo, memo,
  type Dispatch, type SetStateAction, type MutableRefObject,
} from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useAppChat } from "../context/AppChatContext";
import { useToast } from "../components/Toast";
// D1 工具审批门：决议经独立端点回传（SSE 单向流无法在流内回传）
import { api } from "../api/client";
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
  Copy,
  ArrowsClockwise,
  Check,
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
  injectToActiveTurn,
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
import HighlightedText from "../components/HighlightedText";
import TokenBar from "../components/TokenBar";
import { ROLE_STYLES } from "../components/roleStyles";
import AgentProcessPanel, { getToolLabel } from "../components/AgentProcessPanel";
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
  /** P1: 流式期间答案分块（每 rAF 帧追加一段，用于 token 淡入动画） */
  answerChunks?: string[];
}

/** E1: 历史 sources 兼容两种格式（后端并行升级中：string[] → SourceItem[]） */
function normalizeHistorySources(raw: unknown): DiagnosisSource[] | undefined {
  if (!Array.isArray(raw)) return undefined;
  return raw.map((s) =>
    typeof s === "string" ? { text: s } : (s as DiagnosisSource)
  );
}

// ── G1: SSE 事件驱动流式状态机 ──────────────────────────────
// 借鉴 agent-ui useAIStreamHandler 的事件分派思路：
// 将 sendQuestion 内散落的 if/else 链，重构为「按事件类型分派」的处理器集合。
// 每个事件类型一个独立 handler（模块级纯函数，仅依赖 ctx 上下文），
// 由集中的 dispatchStreamEvent 负责路由，未知事件安全忽略（向后兼容）。

/** D1: 工具审批请求（approval_request → ConfirmDialog 弹窗状态） */
interface ApprovalRequest {
  approvalId: string;
  toolName: string;
  summary: string;
}

/**
 * 单个流式消息的处理器上下文。
 * sendQuestion 每次调用组装一次（闭包依赖收敛于此），dispatchStreamEvent 按需读取。
 */
interface StreamCtx {
  tempId: string;
  setChat: Dispatch<SetStateAction<ChatMessage[]>>;
  setAsking: (v: boolean) => void;
  setError: (v: string) => void;
  // D1 审批门：必须是 useState setter（Dispatch<SetStateAction>），
  // handleApprovalDecision 以 updater 函数形式关闭对应弹窗
  setApprovalRequest: Dispatch<SetStateAction<ApprovalRequest | null>>;
  setConversations: Dispatch<SetStateAction<ConversationItem[]>>;
  setQuota: (v: QuotaResponse | null) => void;
  navigate: (to: string) => void;
  aiCreateMode: boolean;
  setAiCreateMode: (v: boolean) => void;
  activeConversationId: number | null;
  resumeId: number;
  pendingStepsRef: MutableRefObject<AgentStep[]>;
  scheduleStreamingFlush: (targetId: string) => void;
  flushStreamingNow: (targetId: string) => void;
  appendThought: (content: string) => void;
  stepStartRef: MutableRefObject<Map<string, number>>;
  beforeModulesRef: MutableRefObject<ResumeModule[] | null>;
  setDiffBeforeModules: (v: ResumeModule[] | null) => void;
  setDiffAfterModules: (v: ResumeModule[] | null) => void;
  setDiffToolName: (v: string) => void;
  setDiffLoading: (v: boolean) => void;
  setDiffDialogOpen: (v: boolean) => void;
  // answer_token：最终轮答案分块累积缓冲 + rAF 句柄（打字机追加到 answer）
  answerBufferRef: MutableRefObject<Map<string, string>>;
  answerRafRef: MutableRefObject<number | null>;
}

/** handler: agent_start — 初始化 Agent 步骤列表 */
function handleAgentStart(_ev: AgentSSEEvent, ctx: StreamCtx): void {
  ctx.setChat((prev) =>
    prev.map((m) =>
      m.id === ctx.tempId ? { ...m, agent_steps: [] } : m
    )
  );
}

/** handler: agent_thought — LLM 推理过程（Spec A#7），追加到 pending 缓冲 rAF 批量刷新 */
function handleAgentThought(ev: AgentSSEEvent, ctx: StreamCtx): void {
  ctx.appendThought(ev.content ?? "");
  ctx.scheduleStreamingFlush(ctx.tempId);
}

/** handler: tool_call（规范名 tool_start）— 记录开始时间 + 填充结构化字段 */
function handleToolCall(ev: AgentSSEEvent, ctx: StreamCtx): void {
  const stepId = ev.id ?? `tc-${Date.now()}`;
  if (ev.id) ctx.stepStartRef.current.set(ev.id, Date.now());
  let parsedArgs: Record<string, unknown> | undefined;
  if (ev.args) {
    try { parsedArgs = JSON.parse(ev.args); } catch { /* not JSON */ }
  }
  ctx.pendingStepsRef.current.push({
    type: "tool_call" as const,
    name: ev.tool_name ?? "",
    detail: ev.args,
    id: stepId,
    args: parsedArgs,
    argsText: ev.args,
    status: "running",
    startedAt: Date.now(),
  });
  ctx.scheduleStreamingFlush(ctx.tempId);
}

/**
 * handler: tool_result（规范名 tool_done）— 计算耗时 + 填充 result。
 * 改写类工具完成 → 实时弹出 diff 对比弹窗（DB 已提交，延迟拉取最新模块）。
 */
function handleToolResult(ev: AgentSSEEvent, ctx: StreamCtx): void {
  const durationMs = ev.id
    ? (Date.now() - (ctx.stepStartRef.current.get(ev.id) ?? Date.now()))
    : undefined;
  if (ev.id) ctx.stepStartRef.current.delete(ev.id);
  ctx.pendingStepsRef.current.push({
    type: "tool_result" as const,
    name: ev.tool_name ?? "",
    detail: ev.summary,
    id: ev.id,
    result: ev.detail,
    status: "done",
    durationMs: durationMs != null && durationMs > 0 ? durationMs : undefined,
  });
  ctx.scheduleStreamingFlush(ctx.tempId);

  // ── 检测改写类工具完成 → 实时弹出 diff 对比 ──
  // rewrite_star / translate 会全量替换模块并写入数据库
  // tool_result 到达时 DB 已提交，可安全拉取最新模块
  const MODIFYING_TOOLS = ["rewrite_star", "translate", "modify_module", "generate_module", "rewrite_resume"];
  const toolName = ev.tool_name ?? "";
  if (MODIFYING_TOOLS.includes(toolName) && ctx.beforeModulesRef.current && ctx.resumeId > 0) {
    ctx.setDiffBeforeModules(ctx.beforeModulesRef.current);
    ctx.setDiffToolName(toolName);
    ctx.setDiffLoading(true);
    ctx.setDiffDialogOpen(true);
    // 延迟 500ms 等待 DB 提交完成（与 refreshModules 修复同模式）
    setTimeout(() => {
      getBuilderResume(ctx.resumeId)
        .then((data) => {
          ctx.setDiffAfterModules(data.modules);
          // 更新 before 快照为当前状态，支持后续多次修改
          ctx.beforeModulesRef.current = data.modules;
        })
        .catch(() => {
          ctx.setDiffAfterModules(null);
        })
        .finally(() => {
          ctx.setDiffLoading(false);
        });
    }, 500);
  }
}

/** handler: tool_error（规范名 tool_done 异常分支）— 计算耗时 + status=error */
function handleToolError(ev: AgentSSEEvent, ctx: StreamCtx): void {
  const durationMs = ev.id
    ? (Date.now() - (ctx.stepStartRef.current.get(ev.id) ?? Date.now()))
    : undefined;
  if (ev.id) ctx.stepStartRef.current.delete(ev.id);
  ctx.pendingStepsRef.current.push({
    type: "tool_error" as const,
    name: ev.tool_name ?? "",
    detail: ev.error,
    id: ev.id,
    status: "error",
    durationMs: durationMs != null && durationMs > 0 ? durationMs : undefined,
  });
  ctx.scheduleStreamingFlush(ctx.tempId);
}

/**
 * handler: tool_stream（规范名 content / reasoning）— 走 rAF 批量刷新，避免逐 token setChat。
 *
 * tool_stream 是工具内部 LLM 的逐 token 高频事件（见后端 loop.py：只透传前端不入 trace）。
 * 原实现每次 token 都 setChat → 整页 map + AgentProcessPanel 全量重渲染 → 主线程卡顿，
 * 拖慢 tool_result / agent_done 等后续事件的显示（表现为"工具结果/总结返回慢"）。
 * 改为与 appendThought 同模式：累积到 pendingStepsRef，由 rAF 每帧只刷新一次。
 */
function handleToolStream(ev: AgentSSEEvent, ctx: StreamCtx): void {
  const steps = ctx.pendingStepsRef.current;
  const last = steps[steps.length - 1];
  if (last && last.type === "tool_stream" && last.name === ev.tool_name) {
    steps[steps.length - 1] = {
      ...last,
      detail: (last.detail ?? "") + (ev.content ?? ""),
    };
  } else {
    steps.push({
      type: "tool_stream" as const,
      name: ev.tool_name ?? "",
      detail: ev.content ?? "",
    });
  }
  ctx.scheduleStreamingFlush(ctx.tempId);
}

/**
 * handler: answer_token — 最终轮答案分块实时追加到 answer（打字机效果）。
 *
 * 后端按字符/时间双阈值分块推送 answer_token（见 loop._stream_final_round），
 * 前端用 rAF 节流每帧一次性追加累积块到 msg.answer，避免逐 token setChat 全量渲染。
 * agent_done 到达时 answer 已完整（含残留块 flush 后的内容），此处只负责中途实时显示。
 */
function handleAnswerToken(ev: AgentSSEEvent, ctx: StreamCtx): void {
  const id = ctx.tempId;
  const buf = ctx.answerBufferRef.current.get(id) ?? "";
  ctx.answerBufferRef.current.set(id, buf + (ev.content ?? ""));
  if (ctx.answerRafRef.current != null) return;
  ctx.answerRafRef.current = requestAnimationFrame(() => {
    ctx.answerRafRef.current = null;
    const pending = ctx.answerBufferRef.current.get(id);
    if (!pending) return;
    ctx.answerBufferRef.current.delete(id);
    ctx.setChat((prev) =>
      prev.map((m) =>
        m.id === id
          ? {
              ...m,
              answer: (m.answer ?? "") + pending,
              answerChunks: [...(m.answerChunks ?? []), pending],
            }
          : m
      )
    );
  });
}

/** handler: usage — 实时更新 token 消耗 */
function handleUsage(ev: AgentSSEEvent, ctx: StreamCtx): void {
  if (ev.total) {
    ctx.setChat((prev) =>
      prev.map((m) =>
        m.id === ctx.tempId
          ? {
              ...m,
              token_usage: {
                total:
                  (ev.total?.prompt_tokens ?? 0) +
                  (ev.total?.completion_tokens ?? 0),
                prompt: ev.total?.prompt_tokens ?? 0,
                completion: ev.total?.completion_tokens ?? 0,
              },
            }
          : m
      )
    );
  }
}

/** handler: approval_request（D1 审批门）— 弹确认弹窗（复用 ConfirmDialog） */
function handleApprovalRequest(ev: AgentSSEEvent, ctx: StreamCtx): void {
  ctx.setApprovalRequest({
    approvalId: ev.approval_id ?? "",
    toolName: ev.tool_name ?? "",
    summary: ev.summary ?? "",
  });
}

/** handler: approval_decision（D1 审批门）— 后端已解析该审批 → 关闭对应弹窗 */
function handleApprovalDecision(ev: AgentSSEEvent, ctx: StreamCtx): void {
  ctx.setApprovalRequest((cur) =>
    cur && cur.approvalId === ev.approval_id ? null : cur
  );
}

/** handler: agent_done（规范名 done）— 终态：写入答案 + 复位 asking + 会话/写库同步 */
function handleAgentDone(ev: AgentSSEEvent, ctx: StreamCtx): void {
  // 先立即应用挂起的步骤，再写入最终答案
  ctx.flushStreamingNow(ctx.tempId);
  ctx.setChat((prev) =>
    prev.map((m) =>
      m.id === ctx.tempId
        ? {
            ...m,
            id: ev.qa_id ?? ctx.tempId,
            answer: ev.answer ?? "",
            streaming: false,
            // E1: agent_done.sources 携带可溯源来源（text/section/start_char/end_char）
            sources: ev.sources as DiagnosisSource[] | undefined,
            token_usage: ev.token_usage
              ? {
                  total:
                    ev.token_usage.prompt_tokens +
                    ev.token_usage.completion_tokens,
                  prompt: ev.token_usage.prompt_tokens,
                  completion: ev.token_usage.completion_tokens,
                }
              : undefined,
            // Spec: process_trace 是紧凑摘要（rounds/tool_sequence/duration_ms），
            // 不是 AgentStep[]，不能覆盖 agent_steps
            // agent_steps 保留实时累积的步骤
          }
        : m
    )
  );
  ctx.setAsking(false);
  window.dispatchEvent(new CustomEvent("quota:refresh"));
  // 问答完成 → 递增当前会话的消息数
  if (ctx.activeConversationId != null && ev.qa_id != null) {
    ctx.setConversations((prev) =>
      prev.map((c) =>
        c.id === ctx.activeConversationId
          ? { ...c, message_count: c.message_count + 1 }
          : c
      )
    );
  }
  // QA 改写类工具（rewrite_star/translate/rewrite_resume）写库后：通知编辑页/侧栏同步
  const wroteModules = (ev.process_trace?.tool_sequence ?? []).some(
    (t) => t === "rewrite_star" || t === "translate" || t === "rewrite_resume",
  );
  if (wroteModules) {
    window.dispatchEvent(new Event("resume:modules-refresh"));
    window.dispatchEvent(new Event("resume:list-refresh"));
  }
  // 新增：AI 创建简历完成后自动跳转到编辑器
  if (ctx.aiCreateMode && ev.process_trace?.tool_sequence?.includes("rewrite_resume")) {
    // 等待 500ms 确保数据写入完成
    setTimeout(() => {
      ctx.navigate(`/resumes/${ctx.resumeId}/edit`);
    }, 500);
    ctx.setAiCreateMode(false);
  }
}

/** handler: quota_exceeded — 额度用尽终态 */
function handleQuotaExceeded(ev: AgentSSEEvent, ctx: StreamCtx): void {
  ctx.flushStreamingNow(ctx.tempId);
  ctx.setChat((prev) =>
    prev.map((m) =>
      m.id === ctx.tempId
        ? {
            ...m,
            answer: ev.message ?? "今日额度已用完",
            streaming: false,
          }
        : m
    )
  );
  ctx.setAsking(false);
  getQuota().then(ctx.setQuota).catch(() => {});
}

/** handler: error（规范名 error）— 流式错误终态 */
function handleError(ev: AgentSSEEvent, ctx: StreamCtx): void {
  ctx.flushStreamingNow(ctx.tempId);
  ctx.setChat((prev) =>
    prev.map((m) =>
      m.id === ctx.tempId
        ? {
            ...m,
            answer: ev.message ?? "Agent 处理失败",
            streaming: false,
          }
        : m
    )
  );
  ctx.setAsking(false);
}

/**
 * G1: 集中式 SSE 事件分派 —— 按事件类型路由到独立 handler，替代散落的 if/else 链。
 *
 * 规范事件名 ↔ 实际 AgentSSEEvent.type 映射：
 *   tool_start         → tool_call
 *   tool_done          → tool_result（正常）/ tool_error（异常）
 *   content / reasoning → tool_stream（kind=token/reasoning）/ agent_thought
 *   done               → agent_done
 *   error              → error / quota_exceeded
 *   approval_request / approval_decision → D1 审批门（分支原样保留，不得破坏）
 *
 * 未识别事件类型走 default 安全忽略（后端新增事件不导致前端崩溃）。
 */
function dispatchStreamEvent(ev: AgentSSEEvent, ctx: StreamCtx): void {
  switch (ev.type) {
    case "agent_start": return handleAgentStart(ev, ctx);
    case "agent_thought": return handleAgentThought(ev, ctx);
    case "tool_call": return handleToolCall(ev, ctx);
    case "tool_result": return handleToolResult(ev, ctx);
    case "tool_error": return handleToolError(ev, ctx);
    case "tool_stream": return handleToolStream(ev, ctx);
    case "answer_token": return handleAnswerToken(ev, ctx);
    case "usage": return handleUsage(ev, ctx);
    case "approval_request": return handleApprovalRequest(ev, ctx);
    case "approval_decision": return handleApprovalDecision(ev, ctx);
    case "agent_done": return handleAgentDone(ev, ctx);
    case "quota_exceeded": return handleQuotaExceeded(ev, ctx);
    case "error": return handleError(ev, ctx);
    default: return; // 未知事件忽略（向后兼容）
  }
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
    description: "实时搜索全网校招/社招岗位",
    question: "请实时搜索最近的校招和社招岗位机会",
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
  /** G2: hover 消息动作栏 — 重新生成（重新发送该消息的问题） */
  onRegenerate: (msg: ChatMessage) => void;
  /** G2: 是否正在等待 AI 回复（流式期间禁用重新生成） */
  asking: boolean;
  /** P4-10: 历史搜索关键词（非空时高亮命中文本） */
  searchTerm?: string;
}

/** G2: 复制文本到剪贴板（Clipboard API + 非安全上下文降级 textarea 方案） */
async function copyToClipboard(text: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    // 非安全上下文（如 http 明文）降级：临时 textarea + execCommand
    try {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
    } catch { /* 忽略复制失败 */ }
  }
}

const MessageBubble = memo(function MessageBubble({ msg, deleting, onDelete, onFeedback, onRegenerate, asking, searchTerm }: MessageBubbleProps) {
  // 流式消息（id 仍是字符串 tempId）不显示删除按钮和反馈按钮
  const canDelete = !msg.streaming && typeof msg.id === "number";
  const canFeedback = !msg.streaming && typeof msg.id === "number";
  // 失败/中断消息：非流式且 id 仍是临时字符串（未落库）→ 红色提示 + 常显重试
  const isFailed = !msg.streaming && typeof msg.id === "string";
  // G2: 复制动作反馈（"已复制"短暂提示）
  const [copied, setCopied] = useState(false);
  const copyTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => {
    if (copyTimerRef.current) clearTimeout(copyTimerRef.current);
  }, []);
  const handleCopy = useCallback(async () => {
    await copyToClipboard(msg.answer || msg.question || "");
    setCopied(true);
    if (copyTimerRef.current) clearTimeout(copyTimerRef.current);
    copyTimerRef.current = setTimeout(() => setCopied(false), 2000);
  }, [msg.answer, msg.question]);
  return (
    <div className="group animate-fade-in-up">
      {/* 用户问题（P4-8 角色样式：右对齐 brand 底色） */}
      <div className="flex justify-end mb-4">
        <div className={`max-w-[75%] px-4 py-3 ${ROLE_STYLES.user.bg}
          ${ROLE_STYLES.user.text} text-sm leading-relaxed rounded-2xl rounded-br-md`}>
          {/* P4-10: 搜索词高亮（历史搜索命中时高亮） */}
          {searchTerm ? (
            <HighlightedText text={msg.question} terms={[searchTerm]} />
          ) : (
            msg.question
          )}
        </div>
      </div>

      {/* AI 回答 */}
      <div className="flex justify-start mb-4">
        <div className="relative max-w-[82%] group/bubble">
          {/* G2: 消息动作栏（hover 气泡出现）— 复制 + 重新生成 */}
          {!msg.streaming && (
            <div className="absolute -top-2.5 right-2 z-10 flex items-center gap-0.5
              px-1 py-0.5 rounded-lg bg-[var(--color-bg)] border border-[var(--color-border)]
              shadow-sm opacity-0 group-hover/bubble:opacity-100
              transition-opacity duration-200">
              <button
                onClick={handleCopy}
                aria-label={copied ? "已复制" : "复制内容"}
                title={copied ? "已复制" : "复制内容"}
                className="p-1 rounded text-[var(--color-text-muted)]
                  hover:text-brand hover:bg-brand/10 active:scale-95
                  motion-reduce:active:scale-100 transition-all cursor-pointer"
              >
                {copied
                  ? <Check size={11} weight="bold" aria-hidden="true" />
                  : <Copy size={11} weight="regular" aria-hidden="true" />}
              </button>
              <button
                onClick={() => onRegenerate(msg)}
                disabled={asking}
                aria-label="重新生成"
                title={asking ? "等待当前回答完成" : "重新生成回答"}
                className="p-1 rounded text-[var(--color-text-muted)]
                  hover:text-brand hover:bg-brand/10 active:scale-95
                  motion-reduce:active:scale-100 transition-all cursor-pointer
                  disabled:opacity-40 disabled:cursor-not-allowed"
              >
                <ArrowsClockwise size={11} weight="regular" aria-hidden="true" />
              </button>
            </div>
          )}
          <div className={`px-4 py-3.5 rounded-2xl rounded-bl-md leading-relaxed text-sm
            ${ROLE_STYLES.assistant.bg} ${ROLE_STYLES.assistant.text}`}>
            {/* T18: Agent 推理过程面板（#11: streaming 开始即显示占位，用户立即看到反馈） */}
            {msg.streaming || (msg.agent_steps && msg.agent_steps.length > 0) ? (
              <AgentProcessPanel steps={msg.agent_steps ?? []} streaming={msg.streaming} />
            ) : null}
            {msg.streaming && !msg.answer && !(msg.agent_steps && msg.agent_steps.length > 0) ? (
              /* P1: 打字指示器精化——两粒圆点 pulse + 上浮（1.5s），对齐 Open WebUI */
              <span
                className="inline-flex items-center gap-1 py-0.5 text-[var(--color-text-muted)]"
                role="status"
                aria-label="AI 思考中"
              >
                <span className="w-1.5 h-1.5 rounded-full bg-current animate-typing-dot" />
                <span className="w-1.5 h-1.5 rounded-full bg-current animate-typing-dot" style={{ animationDelay: "150ms" }} />
              </span>
            ) : !msg.streaming && isDiagnosisMessage(msg) ? (
              /* E1: 简历诊断回答 → 结构化卡片（评分提取失败自动回退纯 markdown） */
              <DiagnosisCard answer={msg.answer} sources={msg.sources} />
            ) : !msg.streaming && msg.agent_steps && msg.agent_steps.length > 0 ? (
              /* P1-C: 有 Agent 步骤时 → 卡片通用分发（JDMatchReport 等，无匹配则 markdown） */
              <AgentCardRouter steps={msg.agent_steps} answer={msg.answer} streaming={msg.streaming} />
            ) : msg.streaming ? (
              /* 流式期间纯文本渲染：answer_token 每帧追加，若走 MarkdownRenderer 会
                 每帧全量重新解析完整 markdown（react-markdown 无增量），CPU 密集卡顿。
                 完成后（agent_done）才解析 markdown 一次。 */
              /* P1: 流式期间 token 淡入——answerChunks 每帧追加一段，新段插入时淡入（100ms） */
              <div className="whitespace-pre-wrap break-words">
                {msg.answerChunks && msg.answerChunks.length > 0
                  ? msg.answerChunks.map((chunk, i) => (
                      <span key={i} className="inline animate-fade-in-token">{chunk}</span>
                    ))
                  : msg.answer}
              </div>
            ) : (
              /* 超长答案折叠：避免 agent_done 后一次性解析/渲染超大 markdown DOM
                 （这是"最后一次渲染慢"的卡点），>3000 字截断 + 展开全文 */
              <MarkdownRenderer maxChars={3000}>
                {msg.answer}
              </MarkdownRenderer>
            )}
            {msg.streaming && msg.answer && <StreamingCursor />}

            {/* 失败/中断消息：视觉区分 + 常显重试按钮（不依赖 hover） */}
            {isFailed && (
              <div className="mt-2 flex items-center gap-2">
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-danger-soft text-danger border border-danger/30 shrink-0">
                  未完成
                </span>
                <button
                  onClick={() => onRegenerate(msg)}
                  disabled={asking}
                  className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium
                    text-brand bg-brand/10 border border-brand/30 hover:brightness-125
                    disabled:opacity-40 disabled:cursor-not-allowed transition-all cursor-pointer"
                  aria-label="重试此问题"
                >
                  <ArrowsClockwise size={10} weight="bold" aria-hidden="true" />
                  重试
                </button>
              </div>
            )}
          </div>

          {/* 来源引用 + 反馈 + 删除按钮 */}
          {!msg.streaming && (
            <div className="flex items-start justify-between gap-2">
              <div className="flex-1 min-w-0">
                {msg.created_at && formatTimestamp(msg.created_at) && (
                  <span
                    data-testid="message-timestamp"
                    className="text-[11px] tabular-nums text-[var(--color-text-muted)] mt-1 block"
                  >
                    {formatTimestamp(msg.created_at)}
                  </span>
                )}
                {/* Token 消耗：文本徽标 + TokenBar 可视化（P4-11 借鉴 Hermes TokenBar） */}
                {msg.token_usage?.total ? (
                  <div
                    data-testid="message-token-usage"
                    className="mt-1 w-36 px-1.5 py-1 text-[10px] font-mono tabular-nums text-[var(--color-text-muted)] bg-[var(--color-bg-secondary)] rounded-md"
                  >
                    <div className="flex items-center justify-between">
                      <span className="inline-flex items-center gap-1">
                        <svg className="w-2.5 h-2.5 opacity-50" viewBox="0 0 16 16" fill="currentColor">
                          <path d="M8 1a7 7 0 100 14A7 7 0 008 1zm0 12.5a5.5 5.5 0 110-11 5.5 5.5 0 010 11zM8 4a.75.75 0 01.75.75v2.5h2.5a.75.75 0 010 1.5h-2.5v2.5a.75.75 0 01-1.5 0v-2.5h-2.5a.75.75 0 010-1.5h2.5v-2.5A.75.75 0 018 4z"/>
                        </svg>
                        {msg.token_usage.total.toLocaleString()} tokens
                      </span>
                    </div>
                    <TokenBar
                      total={msg.token_usage.total}
                      prompt={msg.token_usage.prompt ?? 0}
                      completion={msg.token_usage.completion ?? 0}
                      showLabels={false}
                      className="mt-1"
                    />
                  </div>
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
  const consumedStateRef = useRef<unknown>(null);
  // 侧边栏跳转带来的"待选会话"：对话加载完成后优先选中（仅在列表中存在时）
  const pendingConversationIdRef = useRef<number | null>(null);

  const [resume, setResume] = useState<ResumeItem | null>(null);
  // 简历列表（顶栏切换简历/会话用；多简历时对话按简历隔离，可在此切换）
  const [resumeOptions, setResumeOptions] = useState<ResumeItem[]>([]);
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

  // v2: 简历预览面板（点击简历时右侧弹出）
  const [showPreview, setShowPreview] = useState(false);
  // P2: 预览分栏可拖拽（宽度 30–70%，localStorage 持久化）
  const splitRef = useRef<HTMLDivElement>(null);
  const [splitPct, setSplitPct] = useState<number>(() => {
    const saved = Number(localStorage.getItem("qa-split-pct"));
    return saved >= 30 && saved <= 70 ? saved : 50;
  });
  const splitPctRef = useRef(splitPct);
  useEffect(() => { splitPctRef.current = splitPct; }, [splitPct]);
  const handleStartSplitDrag = (e: React.MouseEvent) => {
    if (!splitRef.current) return;
    e.preventDefault();
    const rect = splitRef.current.getBoundingClientRect();
    const onMove = (ev: MouseEvent) => {
      const pct = Math.min(70, Math.max(30, ((ev.clientX - rect.left) / rect.width) * 100));
      setSplitPct(pct);
    };
    const onUp = () => {
      localStorage.setItem("qa-split-pct", String(splitPctRef.current));
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  };
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
  const handleToggleCollapse = useCallback(() => {
    setShowPreview(false);
    // 关闭预览同时退出模块编辑态：不残留编辑板块，直接回到聊天（用户反馈）
    setEditingModule(null);
    setExpandedType(null);
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
    }).catch(() => {});
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
      // 延迟 500ms 等待 DB 提交完成（与 dispatch 侧注释同模式）
      setTimeout(() => {
        getBuilderResume(resumeId)
          .then((data) => {
            const mods = data.modules ?? [];
            setPreviewModules(mods);
            modulesRef.current = mods;
          })
          .catch(() => {});
      }, 500);
    };
    window.addEventListener("resume:modules-refresh", syncPreview);
    return () => window.removeEventListener("resume:modules-refresh", syncPreview);
  }, [resumeId]);

  // ── 接收来自简历列表 / AI 能力入口 / 侧边栏会话的导航状态（resumeId / question / conversationId） ──
  useEffect(() => {
    const state = location.state as {
      resumeId?: number;
      question?: string;
      conversationId?: number;
    } | null;
    if (!state?.resumeId && !state?.question && !state?.conversationId) return;
    // 防重入：同一份 location.state 只消费一次（否则因 asking/resumeId 变化重复触发 → 死循环）
    if (consumedStateRef.current === location.state) return;
    consumedStateRef.current = location.state;

    if (state.resumeId) {
      setResumeId(state.resumeId);
      setShowPreview(true); // 立即显示预览
    }
    // 侧边栏会话跳转：标记待选会话（对话加载完成后优先选中，防被 list[0] 覆盖）
    if (state.conversationId) {
      pendingConversationIdRef.current = state.conversationId;
      setActiveConversationId(state.conversationId);
    }
    // 缓存待触发问题，等 resumeId 就绪后由发送 effect 统一消费一次
    if (state.question) {
      setPendingTriggerQuestion(state.question);
    }
    // 正确清除 location.state（React Router 中 window.history.replaceState 无效，
    // 必须走 navigate 同路径 replace，否则 state.question 会一直残留触发重复发送）
    navigate(location.pathname, { replace: true, state: null });
  }, [location.state, location.pathname, navigate]);


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
  // answer_token：最终轮答案分块累积缓冲（tempId → 累积文本）+ rAF 句柄
  const answerBufferRef = useRef<Map<string, string>>(new Map());
  const answerRafRef = useRef<number | null>(null);

  const applyPendingSteps = useCallback(
    (targetId: string) => {
      const steps = pendingStepsRef.current;
      pendingStepsRef.current = [];
      if (steps.length === 0) return;
      setChat((prev) =>
        prev.map((m) => {
          if (m.id !== targetId) return m;
          const existing = m.agent_steps ?? [];
          // 追加时合并同工具 tool_stream：逐 token 事件经 rAF 分帧到达，
          // 若已渲染末步与待追加首步同为同名 tool_stream，累积到同一 step，
          // 避免同一工具的 token 被拆成碎片步骤（agent_thought 由 mergeThoughtSteps 兜底）
          const next = [...existing];
          for (const step of steps) {
            const last = next[next.length - 1];
            if (
              last &&
              last.type === "tool_stream" &&
              step.type === "tool_stream" &&
              last.name === step.name
            ) {
              next[next.length - 1] = {
                ...last,
                detail: (last.detail ?? "") + (step.detail ?? ""),
              };
            } else {
              next.push(step);
            }
          }
          return { ...m, agent_steps: next };
        })
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

  // 卸载时取消挂起的 rAF（ref 引用稳定，effect 只注册一次）
  useEffect(() => {
    const stepsRaf = rafRef;
    const answerRaf = answerRafRef;
    return () => {
      if (stepsRaf.current != null) cancelAnimationFrame(stepsRaf.current);
      if (answerRaf.current != null) cancelAnimationFrame(answerRaf.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
    listResumes().then((data) => {
      setResumeOptions(data.items);
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

  // 顶栏切换简历：切换后 useEffect [resumeId] 重载该简历的对话/预览/锁
  // （对话按简历隔离，切换即切换会话；ctxResumeId 由下方 useEffect 自动同步）
  const handleSwitchResume = useCallback(
    (id: number) => {
      if (!id || id === resumeId) return;
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
      toast.success("草稿已保存"); // 用户反馈：保存无任何反馈
    } catch (e) {
      setSaveStatus("error");
      toast.error(e instanceof Error ? e.message : "保存草稿失败");
    } finally {
      setSaving(false);
    }
  }, [resume, resumeId, toast]);

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
      toast.success("已保存并完成，可开始问答/检索");
      // 完成弹窗：确认保存成功 + 引导下一步（用户反馈：完成后应有弹窗）
      setShowSaveCompleteDialog(true);
    } catch (e) {
      setSaveStatus("error");
      toast.error(e instanceof Error ? e.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }, [resume, resumeId, version, toast]);

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

      // G1: 组装本次流式消息的处理器上下文（闭包依赖收敛，供集中事件分派读取）
      const streamCtx: StreamCtx = {
        tempId,
        setChat,
        setAsking,
        setError,
        setApprovalRequest,
        setConversations,
        setQuota,
        navigate,
        aiCreateMode,
        setAiCreateMode,
        activeConversationId,
        resumeId,
        pendingStepsRef,
        scheduleStreamingFlush,
        flushStreamingNow,
        appendThought,
        stepStartRef,
        beforeModulesRef,
        setDiffBeforeModules,
        setDiffAfterModules,
        setDiffToolName,
        setDiffLoading,
        setDiffDialogOpen,
        answerBufferRef,
        answerRafRef,
      };

      abortRef.current = askAgentStream(
        resumeId,
        q,
        (event: AgentSSEEvent) => {
          // G1: 按事件类型分派到独立 handler
          //（tool_start→tool_call / tool_done→tool_result|tool_error / content|reasoning→agent_thought|tool_stream
          //  / done→agent_done / error→error|quota_exceeded / approval_request|approval_decision 审批门）
          dispatchStreamEvent(event, streamCtx);
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
          // 流结束（含超时/异常）兜底关闭审批弹窗，避免残留
          setApprovalRequest(null);
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

  // ── AI 能力入口 / 快捷操作：待触发问题在 resumeId + 会话就绪后自动发送一次 ──
  // 发送后立即清空 pendingTriggerQuestion，配合 location.state 的正确清除，
  // 彻底避免 asking 变化导致的重复发送死循环（只发一次，不随 asking 往返重入）。
  // activeConversationId 条件：等对话加载自动创建/选中第一个会话后再发，
  // 确保这条问答的历史存入该会话（否则 conversation_id 为空导致历史不落库）。
  useEffect(() => {
    if (resumeId <= 0 || !pendingTriggerQuestion || asking) return;
    if (activeConversationId == null) return; // 会话未就绪，等待
    const q = pendingTriggerQuestion;
    setPendingTriggerQuestion(null);
    // 特殊指令拦截：__COMPARE__ → 打开「多选简历」选择器，而非发给 Agent
    // （用户反馈：简历对比不应要求输入简历 id）
    if (q === "__COMPARE__") {
      setCompareOpen(true);
      return;
    }
    sendQuestion(q);
  }, [resumeId, pendingTriggerQuestion, asking, activeConversationId, sendQuestion]);

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
        .then(() => {
          toast.success("已补充给正在思考的 AI");
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
            {/* 简历切换下拉（多简历时切换会话/对话；对话按简历隔离）。
                列出全部简历，value 匹配当前 resumeId，避免下拉无法显示/切换。 */}
            <select
              value={resumeId || ""}
              onChange={(e) => handleSwitchResume(Number(e.target.value))}
              className="max-w-[280px] text-base font-semibold text-[var(--color-text)] truncate
                bg-transparent border border-transparent rounded-md px-1 py-0.5
                hover:border-[var(--color-border)] focus:border-brand/40 focus:outline-none
                cursor-pointer"
              aria-label="切换简历"
              title="切换简历（对话按简历隔离）"
            >
              {resumeOptions.length === 0 && (
                <option value="">{resume?.filename ?? "加载中..."}</option>
              )}
              {resumeOptions.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.filename}
                </option>
              ))}
            </select>

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

          {/* v2: 预览面板切换 — 仅当简历有模块内容（LLM 已填入表单）时才显示，
              避免空表单时预览空白面板（用户反馈：等 LLM 填完且可正确预览再显示按钮） */}
          {resumeId > 0 && previewModules.length > 0 && (
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
        {/* 注意：真正的滚动容器是内层聊天区（flex-1 overflow-y-auto），
            ref/onScroll 必须挂在内层，外层 h-full 高度恒定不会滚动 */}
        <div
          className={`${showPreview ? "" : "flex-1"} overflow-y-auto`}
          style={showPreview ? { width: `${splitPct}%` } : undefined}
        >
          {/* Agent 聊天模式（无模块编辑时显示） */}
          {!editingModule ? (
            <div className="flex flex-col h-full">
              <div
                ref={scrollContainerRef}
                onScroll={checkNearBottom}
                className="flex-1 overflow-y-auto px-4 sm:px-6 py-6"
              >
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
                        onRegenerate={handleRegenerate}
                        asking={asking}
                        searchTerm={debouncedKeyword}
                      />
                    ))
                  )}
                  {error && (
                    <div className="max-w-3xl mx-auto mb-4 p-3 rounded-xl bg-danger-soft border border-danger/30 text-danger text-sm animate-shake">
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
                  onInject={handleInjectMessage}
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

        {/* P2: 可拖拽分隔条（仅预览模式） */}
        {showPreview && resumeId > 0 && (
          <div
            role="separator"
            aria-orientation="vertical"
            aria-label="拖拽调整预览宽度"
            onMouseDown={handleStartSplitDrag}
            className="relative w-2 shrink-0 cursor-col-resize group"
          >
            <div className="absolute inset-y-0 left-1/2 -translate-x-1/2 w-px bg-[var(--color-border)] group-hover:w-0.5 group-hover:bg-brand/40 transition-all" />
          </div>
        )}

        {/* 右侧：简历预览面板（宽度跟随拖拽） */}
        {showPreview && resumeId > 0 && (
          <div className="border-l border-[var(--color-border)] overflow-hidden" style={{ width: `${100 - splitPct}%` }}>
            <A4PreviewPanel
              resumeId={resumeId}
              previewKey={previewKey}
              collapsed={false}
              onToggleCollapse={handleToggleCollapse}
              modulesData={previewModulesData}
              onSelectSection={handleSelectSection}
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

      {/* ── D1: 工具审批确认弹窗（Agent 请求执行写类工具前征求用户同意） ── */}
      <ConfirmDialog
        open={Boolean(approvalRequest)}
        title={`AI 请求执行工具「${getToolLabel(approvalRequest?.toolName ?? "")}」`}
        description={approvalRequest
          ? `AI 想执行这个操作，具体内容如下：\n\n${approvalRequest.summary}\n\n⚠️ 点「允许执行」后才会真正执行（不会重复调用）。拒绝后 AI 将换一种方案。`
          : ""}
        confirmText="允许执行"
        cancelText="拒绝"
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
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
          onClick={() => setShowAtsAudit(false)}
        >
          <div
            className="bg-[var(--color-bg)] rounded-xl shadow-2xl w-full max-w-lg max-h-[80vh] overflow-y-auto p-6 relative"
            onClick={(e) => e.stopPropagation()}
          >
            {/* 右上角 X 关闭（对齐其他弹窗交互） */}
            <button
              onClick={() => setShowAtsAudit(false)}
              aria-label="关闭 ATS 审计"
              className="absolute top-3 right-3 p-1.5 rounded-lg text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-secondary)] transition-colors cursor-pointer"
            >
              <X size={16} weight="bold" />
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

      {/* ── 保存并完成确认弹窗 ── */}
      {showSaveCompleteDialog && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
          onClick={() => setShowSaveCompleteDialog(false)}
        >
          <div
            className="bg-[var(--color-bg)] rounded-xl shadow-2xl w-full max-w-sm p-6"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="text-center">
              <div className="w-12 h-12 mx-auto rounded-full bg-emerald-500/10 flex items-center justify-center mb-3">
                <Check size={24} weight="bold" className="text-emerald-500" />
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
                className="flex-1 px-4 py-2 rounded-lg bg-[var(--color-bg-secondary)] text-[var(--color-text-secondary)] text-sm hover:bg-[var(--color-bg-tertiary)] transition-colors cursor-pointer"
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
                className="flex-1 px-4 py-2 rounded-lg bg-brand text-white text-sm hover:bg-[#0077ed] transition-colors cursor-pointer"
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
