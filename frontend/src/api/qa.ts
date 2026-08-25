import { api } from "./client";
import { refreshToken, notifySessionExpired } from "./client";

export interface AnswerResponse {
  id: number;
  question: string;
  answer: string;
  sources: SourceItem[];
  created_at: string;
  token_usage?: { total: number; prompt: number; completion: number };
  /** 当前用户对该条问答的反馈状态，history 接口返回（刷新后按钮回显）。 */
  feedback?: "positive" | "negative" | null;
}

export interface SSEEvent {
  /** 事件去重用的唯一 id（N5）。后端未下发时为 undefined，此时不去重。 */
  id?: string | number;
  type: "status" | "token" | "done" | "error" | "reset";
  message?: string;
  content?: string;
  answer?: string;
  sources?: SourceItem[];
  qa_id?: number;
  /** 错误代码，如 "quota_exceeded" */
  code?: string;
}

/**
 * N5：判断某个 SSE 事件是否应被丢弃（已出现过相同 id）。
 * 纯函数，便于单测。后端若未下发 id 则永远返回 false（不去重）。
 */
export function shouldSkipEvent(seen: Set<string>, event: SSEEvent): boolean {
  if (event.id == null) return false;
  const key = String(event.id);
  if (seen.has(key)) return true;
  seen.add(key);
  return false;
}

export type QAMode = "stream" | "agentic" | "agent";

export interface AskQuestionOptions {
  /**
   * Task 2.3：RAG 模式
   * - "stream"（默认）：普通流式 RAG，逐 token 推送
   * - "agentic"：完整 Agentic RAG 图（改写→检索→重排→生成→评估→反思），
   *              完成后一次性推送完整答案
   */
  mode?: QAMode;
  compareIds?: number[];
  conversationId?: number;
}

/**
 * SSE 流式问答。返回 abort 函数用于取消请求。
 * onEvent 在每个 SSE 事件时调用；onError 在出错时调用；
 * onDone 在流"无论正常结束还是异常"后都会调用（取消除外），用于兜底重置 UI 状态（C2）。
 */
export function askQuestionStream(
  resume_id: number,
  question: string,
  onEvent: (event: SSEEvent) => void,
  onError: (err: Error) => void,
  onDone?: () => void,
  options?: AskQuestionOptions,
): () => void {
  const abort = new AbortController();
  const seenIds = new Set<string>();
  let aborted = false;

  // Task 2.3：根据 mode 构造 URL。mode 缺省或为 "stream" 时不附加 query（保持向后兼容），
  // 显式传 "stream" 也附加 ?mode=stream（便于调用方明确表达意图）。
  // 后端约定：mode=agentic 走完整 Agentic RAG 图，否则走普通流式管线。
  const url =
    options?.mode === "agentic"
      ? "/api/v1/qa/ask/stream?mode=agentic"
      : options?.mode === "stream"
      ? "/api/v1/qa/ask/stream?mode=stream"
      : "/api/v1/qa/ask/stream";

  const buildHeaders = (): Record<string, string> => ({
    "Content-Type": "application/json",
    ...(localStorage.getItem("access_token")
      ? { Authorization: `Bearer ${localStorage.getItem("access_token")}` }
      : {}),
  });

  const body = JSON.stringify({
    resume_id,
    question,
    ...(options?.compareIds?.length ? { compare_ids: options.compareIds } : {}),
    ...(options?.conversationId != null
      ? { conversation_id: options.conversationId }
      : {}),
  });

  (async () => {
    try {
      let res = await fetch(url, {
        method: "POST",
        headers: buildHeaders(),
        body,
        signal: abort.signal,
      });

      // H10：流式接口原本不走 client.request，不会自动刷新 token。
      // 这里补上：401 先刷新再重试；刷新失败则弹过期提示。
      if (res.status === 401) {
        const ok = await refreshToken();
        if (!ok) {
          notifySessionExpired();
          throw new Error("登录已过期");
        }
        res = await fetch(url, {
          method: "POST",
          headers: buildHeaders(),
          body,
          signal: abort.signal,
        });
      }

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "请求失败" }));
        throw new Error((err as { detail?: string }).detail || "请求失败");
      }

      const reader = res.body?.getReader();
      if (!reader) throw new Error("无法读取响应流");

      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        // SSE 事件以 \n\n 分隔
        const parts = buffer.split("\n\n");
        buffer = parts.pop() || "";

        for (const part of parts) {
          const line = part.trim();
          if (!line.startsWith("data: ")) continue;
          try {
            const data: SSEEvent = JSON.parse(line.slice(6));
            if (shouldSkipEvent(seenIds, data)) continue; // N5 去重
            onEvent(data);
          } catch {
            // 跳过解析失败的行
          }
        }
      }
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") {
        aborted = true;
        return;
      }
      onError(err instanceof Error ? err : new Error("流式请求失败"));
    } finally {
      // C2：流结束（正常或异常）必兜底，确保 asking 状态一定被复位，
      // 否则网络中途断开没收到 done 事件时输入框会卡死在"发送中"。
      // 用户主动取消（abort）由调用方自己复位，这里跳过。
      if (!aborted) onDone?.();
    }
  })();

  return () => abort.abort();
}

// ── Agent SSE 事件（T18 + Spec 对齐） ──────────────────────

/** Agent 推理过程的一步（用于面板展示，由实时 SSE 事件累积构建） */
export interface AgentStep {
  type: "tool_call" | "tool_result" | "tool_error" | "agent_thought" | "tool_stream";
  name: string;
  /** 工具参数（tool_call）、结果摘要（tool_result）、错误文本（tool_error）或推理内容（agent_thought） */
  detail?: string;
  id?: string;
  // P1-C: 结构化扩展（全可选，向后兼容）
  /** tool_call 时的参数 dict（从 event.args 解析） */
  args?: Record<string, unknown>;
  /** tool_call 时的参数原始文本 */
  argsText?: string;
  /** tool_result 时的完整结果文本（来自 event.detail，非 summary） */
  result?: string;
  /** 当前步骤状态 */
  status?: "running" | "done" | "error";
  /** tool_call 收到时的 Date.now() 时间戳 */
  startedAt?: number;
  /** tool_result 收到时计算的耗时毫秒 */
  durationMs?: number;
}

/** 结构化引用来源（Spec A#10: search_resume 来源聚合） */
export interface SourceItem {
  text: string;
  score?: number;
  score_kind?: "dense_similarity" | "bm25" | "rerank_relevance" | "rrf" | "unknown" | string;
  retrieval_source?: string;
  chunk_id?: string | number;
  chunk_index?: number;
  asset_type?: string;
  asset_id?: number;
  version?: number;
  /** E1 可溯源：来源段落分节/字符区间（后端 sources 透出，缺失时为 undefined） */
  section?: string;
  start_char?: number;
  end_char?: number;
}

/** 紧凑过程追踪摘要（Spec SSE done.process_trace，非全量事件列表） */
export interface CompactTrace {
  rounds: number;
  tool_sequence: string[];
  duration_ms: number;
}

/**
 * Agent SSE 事件类型 — 对应后端 react_loop_stream 产出的事件。
 *
 * 字段命名与后端 streaming.py _transform_event 输出一致：
 * - tool_call: { tool_name, args, id }
 * - tool_result: { tool_name, summary, detail, id }
 * - tool_error: { tool_name, error, id }
 * - agent_thought: { content }
 * - usage: { prompt_tokens, completion_tokens, total }
 * - agent_done: { answer, qa_id, sources, token_usage, process_trace, degraded }
 */
export interface AgentSSEEvent {
  type:
    | "agent_start"
    | "agent_thought"
    | "usage"
    | "tool_call"
    | "tool_result"
    | "tool_error"
    | "tool_stream"
    // 最终轮答案分块实时推送（打字机效果，见后端 loop._stream_final_round）
    | "answer_token"
    | "agent_done"
    | "quota_exceeded"
    | "error"
    // D1 工具审批门：approval_request 请求用户确认；approval_decision 回执决议
    | "approval_request"
    | "approval_decision"
    | "injection"
    | "turn_restarting";

  // ── agent_start ──
  protocol_version?: string;
  event_type?: string;
  sequence?: number;
  resume_id?: number;
  turn_id?: string;
  tools?: { name: string; description: string }[];

  // ── agent_thought ──
  /** LLM 推理过程内容（Spec A#7: reasoning_content） */
  content?: string;

  // ── tool_stream ──
  /** 工具内部 LLM 流式 token（编辑器生成/检查/修改等，边出边看） */
  kind?: "token" | "reasoning";

  // ── usage ──
  prompt_tokens?: number;
  completion_tokens?: number;
  total?: { prompt_tokens: number; completion_tokens: number };

  // ── tool_call / tool_result / tool_error 共有 ──
  /** 工具名（SSE 协议字段，后端 _transform_event 输出） */
  tool_name?: string;
  /** tool_call 的参数 JSON 字符串 */
  args?: string;
  /** tool_result 的完整结果文本 */
  detail?: string;
  /** tool_error 的错误文本 */
  error?: string;
  /** 工具事件 ID（用于 tool_call ↔ tool_result/tool_error 配对） */
  id?: string;

  // ── agent_done ──
  answer?: string;
  qa_id?: number;
  /** 引用来源列表（结构化，Spec A#10） */
  sources?: SourceItem[];
  /** token 使用量（SSE 协议字段，对应旧 usage） */
  token_usage?: { prompt_tokens: number; completion_tokens: number };
  /** 紧凑过程追踪摘要（轮数/工具序列/耗时，非全量事件） */
  process_trace?: CompactTrace;
  /** 是否降级（含 tool_error，Spec A#30） */
  degraded?: boolean;

  // ── quota_exceeded / error ──
  message?: string;

  // ── approval_request / approval_decision（D1 工具审批门）──
  /** 审批请求唯一 ID（前端 POST /api/v1/qa/approval 回传决议时携带） */
  approval_id?: string;
  /** 工具结果摘要（tool_result 截断摘要 ≤2000 字符，Spec A#11）或审批弹窗展示摘要（approval_request 工具描述首句 + 关键参数） */
  summary?: string;
  /** approval_decision 的决议结果：approved / denied */
  decision?: string;
  /** 触发审批时的 ReAct 轮次 */
  round?: number;
}

export interface AgentEventGateState {
  turnId?: string;
  lastSequence: number;
  terminalSeen?: boolean;
}

/**
 * 接受当前 turn 的严格递增事件；兼容未携带 metadata 的旧协议事件。
 * state 由单次 stream 独占，接受事件后原地推进。
 */
export function shouldAcceptAgentEvent(
  state: AgentEventGateState,
  event: AgentSSEEvent,
): boolean {
  if (state.terminalSeen) return false;

  const hasTurnId = event.turn_id != null;
  const hasSequence = event.sequence != null;
  // Versioned metadata must be atomic. Half-present metadata is neither a
  // valid versioned event nor a legacy event, so reject without advancing.
  if (hasTurnId !== hasSequence) return false;

  if (event.turn_id != null && event.sequence != null) {
    if (state.turnId && event.turn_id !== state.turnId) return false;
    if (event.sequence <= state.lastSequence) return false;
    state.turnId ??= event.turn_id;
    state.lastSequence = event.sequence;
  }

  if (
    event.type === "agent_done" ||
    event.type === "quota_exceeded" ||
    event.type === "error"
  ) {
    state.terminalSeen = true;
  }
  return true;
}

/**
 * T18: Agent SSE 流式问答。调用 POST /api/v1/qa/ask/agent。
 *
 * 与 askQuestionStream 的区别：
 * - 独立限流（8/min vs 20/min）
 * - 事件类型不同（agent_start/tool_call/tool_result/tool_error/agent_done）
 * - 实时展示 Agent 推理过程
 *
 * T19: 新增可选 compare_ids 参数，用于对比功能。
 *
 * 返回 abort 函数用于取消请求。
 */
export function askAgentStream(
  resume_id: number,
  question: string,
  onEvent: (event: AgentSSEEvent) => void,
  onError: (err: Error) => void,
  onDone?: () => void,
  options?: {
    compareIds?: number[];
    conversationId?: number;
    // v2: Builder 上下文参数
    toolMode?: string;
    moduleType?: string;
    entryId?: string;
    action?: string;
    toolHint?: string;
  },
): () => void {
  const abort = new AbortController();
  let aborted = false;

  const url = "/api/v1/qa/ask/agent";

  const buildHeaders = (): Record<string, string> => ({
    "Content-Type": "application/json",
    ...(localStorage.getItem("access_token")
      ? { Authorization: `Bearer ${localStorage.getItem("access_token")}` }
      : {}),
  });

  const body = JSON.stringify({
    resume_id,
    question,
    ...(options?.compareIds?.length ? { compare_ids: options.compareIds } : {}),
    ...(options?.conversationId != null
      ? { conversation_id: options.conversationId }
      : {}),
    ...(options?.toolMode ? { tool_mode: options.toolMode } : {}),
    ...(options?.moduleType ? { module_type: options.moduleType } : {}),
    ...(options?.entryId ? { entry_id: options.entryId } : {}),
    ...(options?.action ? { action: options.action } : {}),
    ...(options?.toolHint ? { tool_hint: options.toolHint } : {}),
  });

  (async () => {
    try {
      let res = await fetch(url, {
        method: "POST",
        headers: buildHeaders(),
        body,
        signal: abort.signal,
      });

      // 401 自动刷新 token 重试
      if (res.status === 401) {
        const ok = await refreshToken();
        if (!ok) {
          notifySessionExpired();
          throw new Error("登录已过期");
        }
        res = await fetch(url, {
          method: "POST",
          headers: buildHeaders(),
          body,
          signal: abort.signal,
        });
      }

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "请求失败" }));
        throw new Error((err as { detail?: string }).detail || "请求失败");
      }

      const reader = res.body?.getReader();
      if (!reader) throw new Error("无法读取响应流");

      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split("\n\n");
        buffer = parts.pop() || "";

        for (const part of parts) {
          const line = part.trim();
          if (!line.startsWith("data: ")) continue;
          try {
            const data: AgentSSEEvent = JSON.parse(line.slice(6));
            onEvent(data);
          } catch {
            // 跳过解析失败的行
          }
        }
      }
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") {
        aborted = true;
        return;
      }
      onError(err instanceof Error ? err : new Error("Agent 请求失败"));
    } finally {
      if (!aborted) onDone?.();
    }
  })();

  return () => abort.abort();
}

export async function getHistory(
  resume_id: number,
  limit = 20,
  offset = 0,
  keyword?: string,
  conversationId?: number,
) {
  const params = new URLSearchParams();
  params.set("limit", String(limit));
  params.set("offset", String(offset));
  if (keyword && keyword.trim()) {
    params.set("keyword", keyword.trim());
  }
  if (conversationId != null) {
    params.set("conversation_id", String(conversationId));
  }
  return api.get(
    `/api/v1/qa/history/${resume_id}?${params.toString()}`
  ) as Promise<{ items: AnswerResponse[]; total: number }>;
}

export interface QADeleteResult {
  deleted_count: number;
}

/** 清空指定简历（或指定对话）的问答历史，返回被删除的记录数。 */
export async function clearHistory(
  resume_id: number,
  conversationId?: number,
): Promise<QADeleteResult> {
  const params = conversationId != null
    ? `?conversation_id=${conversationId}`
    : "";
  return api.delete(
    `/api/v1/qa/history/${resume_id}${params}`
  ) as Promise<QADeleteResult>;
}

/** 删单条问答记录。后端返回 204，前端不解析 body。 */
export async function deleteQa(qa_id: number): Promise<void> {
  await api.delete(`/api/v1/qa/${qa_id}`);
}

/** Task 5.1: 提交质量反馈（upsert）。rating = "positive" | "negative"。 */
export async function submitFeedback(
  qa_id: number,
  rating: "positive" | "negative"
): Promise<void> {
  await api.post(`/api/v1/qa/${qa_id}/feedback`, { rating });
}

/** 取消对单条问答的反馈（点同按钮再点一次取消，后端幂等）。 */
export async function cancelFeedback(qa_id: number): Promise<void> {
  await api.delete(`/api/v1/qa/${qa_id}/feedback`);
}

/** Token 限额状态。 */
export interface QuotaResponse {
  enabled: boolean;
  used: number;
  limit: number;
  remaining: number;
  reset_at: string | null;
}

/** 获取当前用户的 token 限额状态。 */
export async function getQuota(): Promise<QuotaResponse> {
  return api.get("/api/v1/qa/quota") as Promise<QuotaResponse>;
}

// ── 对话会话 API ──────────────────────────────────────────

export interface ConversationItem {
  id: number;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
}

/** 列出某简历下的所有对话。 */
export async function getConversations(
  resumeId: number,
): Promise<ConversationItem[]> {
  const data = await api.get(
    `/api/v1/qa/conversations/${resumeId}`,
  ) as { items: ConversationItem[]; total: number };
  return data.items;
}

/** 创建新对话。 */
export async function createConversation(
  resumeId: number,
  title?: string,
): Promise<ConversationItem> {
  return api.post(
    `/api/v1/qa/conversations/${resumeId}`,
    title ? { title } : {},
  ) as Promise<ConversationItem>;
}

/** 重命名对话。 */
export async function renameConversation(
  conversationId: number,
  title: string,
): Promise<ConversationItem> {
  return api.put(
    `/api/v1/qa/conversations/${conversationId}`,
    { title },
  ) as Promise<ConversationItem>;
}

/** 删除对话及其所有问答。 */
export async function deleteConversation(
  conversationId: number,
): Promise<{ deleted_count: number }> {
  return api.delete(
    `/api/v1/qa/conversations/${conversationId}`,
  ) as Promise<{ deleted_count: number }>;
}

/** P1-2: 注入消息到当前活跃的 agent 回合（asking 期间补充信息，不排队新回合）。 */
export async function injectToActiveTurn(
  resumeId: number,
  content: string,
  conversationId?: number,
): Promise<{ injected: boolean; status: "restarting" | "queued" | "failed"; turn_id: string | null }> {
  return api.post(`/api/v1/qa/${resumeId}/inject`, {
    content,
    conversation_id: conversationId ?? null,
    }) as Promise<{ injected: boolean; status: "restarting" | "queued" | "failed"; turn_id: string | null }>;
}
