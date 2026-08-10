/**
 * T34: 管理员后台 API 客户端。
 *
 * 对应后端 /api/v1/admin/* 端点，所有端点需管理员权限（后端 require_admin）。
 * 非管理员调用后端返回 403，前端在 AdminPage 中捕获并展示错误。
 */
import { api } from "./client";

// ── 类型定义 ──────────────────────────────────────────────

export interface AuditLogItem {
  id: number;
  user_id: number | null;
  action: string;
  target_type: string | null;
  target_id: string | null;
  detail: Record<string, unknown> | null;
  ip: string | null;
  created_at: string;
}

export interface AuditLogListResponse {
  items: AuditLogItem[];
  total: number;
}

export interface AdminUserItem {
  id: number;
  username: string;
  email: string;
  created_at: string;
}

export interface AdminUserListResponse {
  items: AdminUserItem[];
  total: number;
}

export interface SystemStats {
  total_users: number;
  total_resumes: number;
  total_qa_history: number;
  total_feedback: number;
  total_job_applications: number;
  total_interviews: number;
}

export interface TemplateInfo {
  id: string;
  name: string;
  description: string;
}

// D3/D4: 后台看板趋势 + LLM 用量
export interface TrendItem {
  day: string;
  registrations: number;
  active_users: number;
  events: number;
}

export interface TrendResponse {
  days: number;
  items: TrendItem[];
}

export interface LLMUsageItem {
  date: string;
  total_tokens: number;
  calls: number;
}

export interface LLMUsageResponse {
  days: number;
  items: LLMUsageItem[];
}

export interface TemplateListResponse {
  templates: TemplateInfo[];
}

export interface FeedbackItem {
  id: number;
  user_id: number;
  content: string;
  type: string;
  status: string;
  created_at: string;
}

export interface FeedbackListResponse {
  items: FeedbackItem[];
  total: number;
}

// ── QA 反馈质量统计（问答质量看板） ──────────────────────

export interface QAStatsResumeItem {
  resume_id: number;
  resume_title: string;
  positive: number;
  negative: number;
  negative_rate: number;
}

export interface QANegativeSample {
  qa_id: number;
  question: string;
  answer_excerpt: string;
  resume_id: number;
  created_at: string;
  process_trace: Record<string, unknown> | null;
}

export interface QAStatsResponse {
  total_feedback: number;
  positive: number;
  negative: number;
  negative_rate: number;
  by_resume: QAStatsResumeItem[];
  recent_negative: QANegativeSample[];
}

// ── API 函数 ──────────────────────────────────────────────

/** 查询审计日志（可按 action / user_id 过滤）。 */
export async function getAuditLogs(params: {
  action?: string;
  user_id?: number;
  limit?: number;
  offset?: number;
} = {}): Promise<AuditLogListResponse> {
  const qs = new URLSearchParams();
  if (params.action) qs.set("action", params.action);
  if (params.user_id != null) qs.set("user_id", String(params.user_id));
  qs.set("limit", String(params.limit ?? 20));
  qs.set("offset", String(params.offset ?? 0));
  return api.get(`/api/v1/admin/audit-logs?${qs.toString()}`) as Promise<AuditLogListResponse>;
}

/** 分页查询用户列表（仅安全字段）。 */
export async function getAdminUsers(params: {
  limit?: number;
  offset?: number;
} = {}): Promise<AdminUserListResponse> {
  const qs = new URLSearchParams();
  qs.set("limit", String(params.limit ?? 20));
  qs.set("offset", String(params.offset ?? 0));
  return api.get(`/api/v1/admin/users?${qs.toString()}`) as Promise<AdminUserListResponse>;
}

/** 系统级统计数据。 */
export async function getSystemStats(): Promise<SystemStats> {
  return api.get("/api/v1/admin/stats") as Promise<SystemStats>;
}

/** D3: 按天趋势（注册/日活/事件），后台看板图表。 */
export async function getTrends(days: number = 30): Promise<TrendResponse> {
  return api.get(`/api/v1/track/trends?days=${days}`) as Promise<TrendResponse>;
}

/** D4: LLM 用量历史（按天聚合），后台看板图表。 */
export async function getLLMUsage(days: number = 7): Promise<LLMUsageResponse> {
  return api.get(`/api/v1/track/llm-usage?days=${days}`) as Promise<LLMUsageResponse>;
}

/** 管理员查看意见箱反馈。 */
export async function getAdminFeedback(params: {
  limit?: number;
  offset?: number;
} = {}): Promise<FeedbackListResponse> {
  const qs = new URLSearchParams();
  qs.set("limit", String(params.limit ?? 20));
  qs.set("offset", String(params.offset ?? 0));
  return api.get(`/api/v1/admin/feedback?${qs.toString()}`) as Promise<FeedbackListResponse>;
}

/** 列出可用简历模板。 */
export async function getAdminTemplates(): Promise<TemplateListResponse> {
  return api.get("/api/v1/admin/templates") as Promise<TemplateListResponse>;
}

/** 管理员问答质量统计（正负比例 + 简历维度排行 + negative 样本）。 */
export async function getQaStats(): Promise<QAStatsResponse> {
  return api.get("/api/v1/qa/stats") as Promise<QAStatsResponse>;
}
