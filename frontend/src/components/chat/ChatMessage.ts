import type { AgentStep } from "../../api/qa";
import type { DiagnosisSource } from "./DiagnosisCard";

/** 聊天消息模型（QA 页核心消息结构） */
export interface ChatMessage {
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
export function normalizeHistorySources(raw: unknown): DiagnosisSource[] | undefined {
  if (!Array.isArray(raw)) return undefined;
  return raw.map((s) =>
    typeof s === "string" ? { text: s } : (s as DiagnosisSource)
  );
}

/** 将 ISO 时间字符串格式化为北京时间 "MM-DD HH:mm" */
export function formatTimestamp(dateStr?: string): string | null {
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
