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
}

export interface TemplateInfo {
  id: string;
  name: string;
  description: string;
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
