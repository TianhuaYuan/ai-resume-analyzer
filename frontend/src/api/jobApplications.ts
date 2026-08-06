import { api } from "./client";
import type { KnowledgeAsset } from "./assets";

// ── 类型定义 ──

/** 投递状态机（third_party/Job STATUS_FLOW 契约，后端同构） */
export const APPLICATION_STATUSES = [
  "待投递",
  "已投递",
  "笔试",
  "一面",
  "二面",
  "三面",
  "HR面",
  "Offer",
  "已拒",
] as const;

export type ApplicationStatus = (typeof APPLICATION_STATUSES)[number];

/** 状态流转图：旧状态 → 允许的新状态（面试轮次可跳过） */
export const APPLICATION_STATUS_FLOW: Record<ApplicationStatus, ApplicationStatus[]> = {
  待投递: ["已投递"],
  已投递: ["笔试", "一面", "已拒"],
  笔试: ["一面", "已拒"],
  一面: ["二面", "三面", "HR面", "Offer", "已拒"],
  二面: ["三面", "HR面", "Offer", "已拒"],
  三面: ["HR面", "Offer", "已拒"],
  HR面: ["Offer", "已拒"],
  Offer: [],
  已拒: [],
};

export const APPLICATION_PRIORITIES = ["高", "中", "低"] as const;

/** JD 评分卡（对象，结构由后端定义，前端透传/展示） */
export interface JdScorecard {
  grade?: string;
  comp_min?: number | null;
  comp_max?: number | null;
  pain_line?: string;
  gaps?: string[];
  generated_at?: string;
}

/** 投递记录（后端 /api/v1/job-applications 契约） */
export interface JobApplication {
  id: number;
  company: string;
  position: string;
  url: string | null;
  status: ApplicationStatus;
  priority: string;
  deadline: string | null;
  notes: string | null;
  jd_text: string | null;
  jd_scorecard: JdScorecard | null;
  timeline: Array<{ at: string; from: string; to: string; note: string }> | null;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
  /** 派生字段 */
  stay_days: number | null;
  deadline_status: "red" | "yellow" | "green" | "overdue" | "none";
}

export interface DuplicateItem {
  id: number;
  company: string;
  position: string;
  status: string;
}

export interface JobApplicationCreateResult {
  application: JobApplication;
  duplicates: DuplicateItem[];
}

export interface JobApplicationListResponse {
  items: JobApplication[];
  total: number;
  page: number;
  limit: number;
  total_pages: number;
}

export interface JobApplicationCreateInput {
  company: string;
  position: string;
  url?: string;
  status?: string;
  priority?: string;
  deadline?: string;
  notes?: string;
  jd_text?: string;
  generate_scorecard?: boolean;
}

export interface JobApplicationUpdateInput {
  company?: string;
  position?: string;
  url?: string;
  priority?: string;
  deadline?: string;
  notes?: string;
  jd_text?: string;
  generate_scorecard?: boolean;
}

export interface JobApplicationStatusInput {
  new_status: ApplicationStatus;
  note?: string;
}

/** 看板今日队列项：thank_you=致谢 / nudge=催办 / ghost=失联 */
export interface DashboardQueueItem {
  kind: "thank_you" | "nudge" | "ghost";
  headline: string;
  detail: string;
  application_id: number;
  company: string;
  position: string;
  priority: string;
  status: ApplicationStatus;
  stay_days: number | null;
}

export interface JobDashboard {
  timing: { thankyou_hours: number; nudge_days: number; ghost_days: number };
  stats: {
    total: number;
    active: number;
    to_apply: number;
    offer: number;
    rejected: number;
    high_priority: number;
  };
  deadline_counts: { red: number; yellow: number; green: number; overdue: number; none: number };
  queue: DashboardQueueItem[];
}

export interface JobApplicationListParams {
  status?: string;
  priority?: string;
  keyword?: string;
  deleted?: boolean;
  page?: number;
  limit?: number;
}

// ── API 函数 ──

/** GET /api/v1/job-applications — 分页列表（默认排除软删除；deleted=true 查垃圾箱） */
export async function listJobApplications(
  params: JobApplicationListParams = {}
): Promise<JobApplicationListResponse> {
  const qs = new URLSearchParams();
  qs.set("page", String(params.page ?? 1));
  qs.set("limit", String(params.limit ?? 50));
  if (params.status) qs.set("status", params.status);
  if (params.priority) qs.set("priority", params.priority);
  if (params.keyword) qs.set("keyword", params.keyword);
  if (params.deleted) qs.set("deleted", "true");
  return api.get(`/api/v1/job-applications?${qs}`) as Promise<JobApplicationListResponse>;
}

/** GET /api/v1/job-applications/dashboard — 看板（统计+截止红黄绿+今日队列） */
export async function getJobDashboard(): Promise<JobDashboard> {
  return api.get("/api/v1/job-applications/dashboard") as Promise<JobDashboard>;
}

/** GET /api/v1/job-applications/{id} — 详情（含 timeline/jd_scorecard） */
export async function getJobApplication(id: number): Promise<JobApplication> {
  return api.get(`/api/v1/job-applications/${id}`) as Promise<JobApplication>;
}

/** POST /api/v1/job-applications — 新建（返回记录 + 去重提示） */
export async function createJobApplication(
  body: JobApplicationCreateInput
): Promise<JobApplicationCreateResult> {
  return api.post("/api/v1/job-applications", body) as Promise<JobApplicationCreateResult>;
}

/** PUT /api/v1/job-applications/{id} — 更新（不含状态流转） */
export async function updateJobApplication(
  id: number,
  body: JobApplicationUpdateInput
): Promise<JobApplicationCreateResult> {
  return api.put(`/api/v1/job-applications/${id}`, body) as Promise<JobApplicationCreateResult>;
}

/** POST /api/v1/job-applications/{id}/status — 状态流转（校验 STATUS_FLOW，timeline 自动追加） */
export async function transitionJobApplicationStatus(
  id: number,
  body: JobApplicationStatusInput
): Promise<JobApplication> {
  return api.post(
    `/api/v1/job-applications/${id}/status`,
    body
  ) as Promise<JobApplication>;
}

/** DELETE /api/v1/job-applications/{id} — 软删除（进垃圾箱） */
export async function deleteJobApplication(id: number): Promise<null> {
  return api.delete(`/api/v1/job-applications/${id}`) as Promise<null>;
}

/** POST /api/v1/job-applications/{id}/restore — 从垃圾箱恢复 */
export async function restoreJobApplication(id: number): Promise<JobApplication> {
  return api.post(`/api/v1/job-applications/${id}/restore`) as Promise<JobApplication>;
}

/** POST /api/v1/job-applications/{id}/archive — 归档 JD 为知识资产（幂等，供 Agent 检索） */
export async function archiveJobApplication(id: number): Promise<KnowledgeAsset> {
  return api.post(
    `/api/v1/job-applications/${id}/archive`
  ) as Promise<KnowledgeAsset>;
}
