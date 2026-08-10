import {
  useCallback, useRef, useEffect,
  type Dispatch, type SetStateAction, type MutableRefObject,
} from "react";
import {
  askAgentStream, getQuota,
  type AgentSSEEvent, type AgentStep, type ConversationItem, type QuotaResponse,
} from "../../api/qa";
import { createBuilderResume, getBuilderResume, type ResumeModule } from "../../api/builder";
import type { ChatMessage } from "./ChatMessage";
import type { DiagnosisSource } from "./DiagnosisCard";

/** D1: 工具审批请求（approval_request → ConfirmDialog 弹窗状态） */
export interface ApprovalRequest {
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
  activeResumeIdRef: MutableRefObject<number>;
  editRevisionRef: MutableRefObject<number>;
  diffOwnerTokenRef: MutableRefObject<number>;
  diffFetchTimerRef: MutableRefObject<ReturnType<typeof setTimeout> | null>;
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

function handleInjection(ev: AgentSSEEvent, ctx: StreamCtx): void {
  ctx.pendingStepsRef.current.push({ type: "agent_thought", name: "补充信息", detail: `已收到补充信息：${ev.content ?? ""}` });
  ctx.scheduleStreamingFlush(ctx.tempId);
}

function handleTurnRestarting(_ev: AgentSSEEvent, ctx: StreamCtx): void {
  if (ctx.answerRafRef.current != null) {
    cancelAnimationFrame(ctx.answerRafRef.current);
    ctx.answerRafRef.current = null;
  }
  ctx.answerBufferRef.current.delete(ctx.tempId);
  ctx.setChat((prev) => prev.map((m) => m.id === ctx.tempId ? { ...m, answer: "" } : m));
  ctx.pendingStepsRef.current.push({ type: "agent_thought", name: "重新生成", detail: "正在合并补充信息并重新生成答案…" });
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
    const ownerResumeId = ctx.resumeId;
    const ownerRevision = ctx.editRevisionRef.current;
    const ownerToken = ++ctx.diffOwnerTokenRef.current;
    const ownsDiff = () => ctx.diffOwnerTokenRef.current === ownerToken
      && ctx.activeResumeIdRef.current === ownerResumeId
      && ctx.editRevisionRef.current === ownerRevision;
    if (!ownsDiff()) return;
    ctx.setDiffBeforeModules(ctx.beforeModulesRef.current);
    ctx.setDiffToolName(toolName);
    ctx.setDiffLoading(true);
    ctx.setDiffDialogOpen(true);
    // 延迟 500ms 等待 DB 提交完成（与 refreshModules 修复同模式）
    if (ctx.diffFetchTimerRef.current) clearTimeout(ctx.diffFetchTimerRef.current);
    ctx.diffFetchTimerRef.current = setTimeout(() => {
      ctx.diffFetchTimerRef.current = null;
      getBuilderResume(ownerResumeId)
        .then((data) => {
          if (!ownsDiff()) return;
          ctx.setDiffAfterModules(data.modules);
          // 更新 before 快照为当前状态，支持后续多次修改
          ctx.beforeModulesRef.current = data.modules;
        })
        .catch(() => {
          if (!ownsDiff()) return;
          ctx.setDiffAfterModules(null);
        })
        .finally(() => {
          if (!ownsDiff()) return;
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
  const existingIndex = ev.id
    ? steps.findIndex((step) => step.type === "tool_stream" && step.id === ev.id)
    : -1;
  if (existingIndex >= 0) {
    const existing = steps[existingIndex];
    steps[existingIndex] = {
      ...existing,
      detail: (existing.detail ?? "") + (ev.content ?? ""),
    };
  } else {
    steps.push({
      type: "tool_stream" as const,
      name: ev.tool_name ?? "",
      id: ev.id,
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
    case "injection": return handleInjection(ev, ctx);
    case "turn_restarting": return handleTurnRestarting(ev, ctx);
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

/**
 * useAgentStream — QA 页 SSE 流式状态机 hook（G1 改造核心）。
 *
 * 将 QAPage 内散落的流式逻辑整体收纳：模块级 handler + dispatchStreamEvent
 * + rAF 节流（pendingStepsRef/answerBufferRef）+ sendQuestion。
 *
 * 闭包收敛策略：所有外部依赖通过 `getDeps()` 每渲染获取最新值存入 depsRef，
 * sendQuestion 以稳定引用（useCallback([])）调用时读取 depsRef.current——
 * 保证 dispatchStreamEvent 各 handler 行为与旧实现完全一致。
 */

/** 依赖刷新函数：QAPage 每渲染调用返回最新状态/回调快照 */
export interface AgentStreamDeps {
  resumeId: number;
  activeConversationId: number | null;
  compareIds: number[];
  aiCreateMode: boolean;
  setAiCreateMode: (v: boolean) => void;
  navigate: (to: string) => void;
  setResumeId: (id: number) => void;
  setPendingAiCreateQuestion: (q: string | null) => void;
  setQaInitState?: (state: "empty" | "creating" | "loading" | "ready" | "error") => void;
  setChat: Dispatch<SetStateAction<ChatMessage[]>>;
  setAsking: (v: boolean) => void;
  setError: (v: string) => void;
  setApprovalRequest: Dispatch<SetStateAction<ApprovalRequest | null>>;
  setConversations: Dispatch<SetStateAction<ConversationItem[]>>;
  setQuota: (v: QuotaResponse | null) => void;
  beforeModulesRef: MutableRefObject<ResumeModule[] | null>;
  activeResumeIdRef: MutableRefObject<number>;
  editRevisionRef: MutableRefObject<number>;
  diffOwnerTokenRef: MutableRefObject<number>;
  diffFetchTimerRef: MutableRefObject<ReturnType<typeof setTimeout> | null>;
  setDiffBeforeModules: (v: ResumeModule[] | null) => void;
  setDiffAfterModules: (v: ResumeModule[] | null) => void;
  setDiffToolName: (v: string) => void;
  setDiffLoading: (v: boolean) => void;
  setDiffDialogOpen: (v: boolean) => void;
  isNearBottomRef: MutableRefObject<boolean>;
  scrollToBottom: (smooth?: boolean) => void;
}

export interface SendQuestionOptions {
  compareIds?: number[];
  toolMode?: string;
  moduleType?: string;
  entryId?: string;
  action?: string;
}

export type SendQuestion = (q: string, options?: SendQuestionOptions) => void;

export function useAgentStream(getDeps: () => AgentStreamDeps): {
  sendQuestion: SendQuestion;
  abortRef: MutableRefObject<(() => void) | null>;
} {
  // 每渲染刷新最新依赖快照
  const depsRef = useRef<AgentStreamDeps>(getDeps());
  depsRef.current = getDeps();

  // ── 流式步骤 rAF 节流（性能优化） ──
  // agent_thought / tool_* 事件高频到达，若每段都 setChat 会触发整页重渲染。
  // 改为累积到 pendingStepsRef，由 requestAnimationFrame 每帧批量刷新一次。
  const pendingStepsRef = useRef<AgentStep[]>([]);
  const rafRef = useRef<number | null>(null);
  // P1-C: 记录每个 tool_call 的开始时间，用于计算 durationMs
  const stepStartRef = useRef<Map<string, number>>(new Map());
  // answer_token：最终轮答案分块累积缓冲（tempId → 累积文本）+ rAF 句柄
  const answerBufferRef = useRef<Map<string, string>>(new Map());
  const answerRafRef = useRef<number | null>(null);
  const abortRef = useRef<(() => void) | null>(null);
  const createResumePromiseRef = useRef<Promise<{ id: number }> | null>(null);

  const applyPendingSteps = useCallback((targetId: string) => {
    const d = depsRef.current;
    const steps = pendingStepsRef.current;
    pendingStepsRef.current = [];
    if (steps.length === 0) return;
    d.setChat((prev) =>
      prev.map((m) => {
        if (m.id !== targetId) return m;
        const existing = m.agent_steps ?? [];
        // 追加时合并同工具 tool_stream：逐 token 事件经 rAF 分帧到达，
        // 若已渲染末步与待追加首步同为同名 tool_stream，累积到同一 step，
        // 避免同一工具的 token 被拆成碎片步骤（agent_thought 由 mergeThoughtSteps 兜底）
        const next = [...existing];
        for (const step of steps) {
          if (step.id && (step.type === "tool_result" || step.type === "tool_error" || step.type === "tool_stream")) {
            const index = next.findIndex((candidate) => candidate.id === step.id);
            if (index >= 0) {
              const current = next[index];
              next[index] = step.type === "tool_stream"
                ? { ...current, detail: (current.detail ?? "") + (step.detail ?? "") }
                : { ...current, ...step };
              continue;
            }
          }
          const last = next[next.length - 1];
          if (
            last &&
            last.type === "tool_stream" &&
            step.type === "tool_stream" &&
            last.name === step.name && last.id === step.id
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
      if (d.isNearBottomRef.current) d.scrollToBottom(false);
    });
  }, []);

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

  // 卸载时取消挂起的 rAF + abort 流
  useEffect(() => {
    const stepsRaf = rafRef;
    const answerRaf = answerRafRef;
    return () => {
      if (stepsRaf.current != null) cancelAnimationFrame(stepsRaf.current);
      if (answerRaf.current != null) cancelAnimationFrame(answerRaf.current);
      abortRef.current?.();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const sendQuestion = useCallback<SendQuestion>((q, options) => {
    const d = depsRef.current;
    d.setError("");

    // ── 无简历时：先创建空简历，再启动 AI 创建流程 ──
    if (!d.resumeId || d.resumeId === 0) {
      d.setAiCreateMode(true);
      d.setQaInitState?.("creating");
      d.setPendingAiCreateQuestion(q);
      if (createResumePromiseRef.current) return;
      createResumePromiseRef.current = createBuilderResume({ filename: "未命名简历" })
        .then((resume) => { d.setResumeId(resume.id); d.setQaInitState?.("loading"); return resume; })
        .catch((err) => {
          d.setError(err instanceof Error ? err.message : "创建简历失败");
          d.setQaInitState?.("error");
          d.setAiCreateMode(false);
          d.setPendingAiCreateQuestion(null);
          return { id: 0 };
        })
        .finally(() => { createResumePromiseRef.current = null; });
      return;
    }

    d.setAsking(true);

    // ── 快照当前模块（before），用于 diff 弹窗 ──
    // 非阻塞：失败则 beforeModulesRef 保持 null，diff 弹窗不弹出
    if (d.resumeId > 0) {
      const snapshotResumeId = d.resumeId;
      const snapshotRevision = d.editRevisionRef.current;
      getBuilderResume(snapshotResumeId)
        .then((data) => {
          if (d.activeResumeIdRef.current === snapshotResumeId && d.editRevisionRef.current === snapshotRevision) {
            d.beforeModulesRef.current = data.modules;
          }
        })
        .catch(() => {
          if (d.activeResumeIdRef.current === snapshotResumeId && d.editRevisionRef.current === snapshotRevision) {
            d.beforeModulesRef.current = null;
          }
        });
    }

    const tempId = `streaming-${Date.now()}`;
    const newMsg: ChatMessage = {
      id: tempId,
      question: q,
      answer: "",
      streaming: true,
    };
    d.setChat((prev) => [...prev, newMsg]);

    // 发送新消息后强制滚动到底部（无论用户之前是否上滚）
    d.isNearBottomRef.current = true;
    requestAnimationFrame(() => d.scrollToBottom(false));

    // G1: 组装本次流式消息的处理器上下文（闭包依赖收敛，供集中事件分派读取）
    const streamCtx: StreamCtx = {
      tempId,
      setChat: d.setChat,
      setAsking: d.setAsking,
      setError: d.setError,
      setApprovalRequest: d.setApprovalRequest,
      setConversations: d.setConversations,
      setQuota: d.setQuota,
      navigate: d.navigate,
      aiCreateMode: d.aiCreateMode,
      setAiCreateMode: d.setAiCreateMode,
      activeConversationId: d.activeConversationId,
      resumeId: d.resumeId,
      pendingStepsRef,
      scheduleStreamingFlush,
      flushStreamingNow,
      appendThought,
      stepStartRef,
      beforeModulesRef: d.beforeModulesRef,
      activeResumeIdRef: d.activeResumeIdRef,
      editRevisionRef: d.editRevisionRef,
      diffOwnerTokenRef: d.diffOwnerTokenRef,
      diffFetchTimerRef: d.diffFetchTimerRef,
      setDiffBeforeModules: d.setDiffBeforeModules,
      setDiffAfterModules: d.setDiffAfterModules,
      setDiffToolName: d.setDiffToolName,
      setDiffLoading: d.setDiffLoading,
      setDiffDialogOpen: d.setDiffDialogOpen,
      answerBufferRef,
      answerRafRef,
    };

    abortRef.current = askAgentStream(
      d.resumeId,
      q,
      (event: AgentSSEEvent) => {
        // G1: 按事件类型分派到独立 handler
        //（tool_start→tool_call / tool_done→tool_result|tool_error / content|reasoning→agent_thought|tool_stream
        //  / done→agent_done / error→error|quota_exceeded / approval_request|approval_decision 审批门）
        dispatchStreamEvent(event, streamCtx);
      },
      (err: Error) => {
        flushStreamingNow(tempId);
        d.setError(err.message);
        d.setChat((prev) =>
          prev.map((m) =>
            m.id === tempId
              ? { ...m, answer: "生成失败，请重试", streaming: false }
              : m
          )
        );
        d.setAsking(false);
      },
      () => {
        flushStreamingNow(tempId);
        d.setAsking(false);
        // 流结束（含超时/异常）兜底关闭审批弹窗，避免残留
        d.setApprovalRequest(null);
        d.setChat((prev) =>
          prev.map((m) =>
            m.id === tempId ? { ...m, streaming: false } : m
          )
        );
      },
      {
        compareIds: options?.compareIds ?? (d.compareIds.length > 0 ? d.compareIds : undefined),
        conversationId: d.activeConversationId ?? undefined,
        toolMode: options?.toolMode,
        moduleType: options?.moduleType,
        entryId: options?.entryId,
        action: options?.action,
      },
    );
  }, [applyPendingSteps, scheduleStreamingFlush, flushStreamingNow, appendThought]);

  return { sendQuestion, abortRef };
}
