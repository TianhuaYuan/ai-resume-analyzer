/**
 * Market — 市场数据 API client。
 *
 * 对接后端 /api/v1/market/* 端点：
 * - GET    /api/v1/market/jobs        社招/校招/实习岗位列表
 * - GET    /api/v1/market/jobs/{id}   岗位详情（含全文 content + payload）
 * - POST   /api/v1/market/recommend   基于简历的岗位推荐（matched/gaps/reason）
 */

import { api } from "./client";

// ── 类型定义 ──

/** 岗位类型枚举（与后端 job_type 对齐） */
export type JobType = "campus" | "social" | "intern";

/** job_type 中文标签 */
export const JOB_TYPE_LABELS: Record<JobType, string> = {
  campus: "校招",
  social: "社招",
  intern: "实习",
};

/** 按 job_type 取中文标签（兼容未知值） */
export function jobTypeLabel(jobType: JobType | string | null | undefined): string {
  if (!jobType) return "";
  return JOB_TYPE_LABELS[jobType as JobType] ?? String(jobType);
}

/** 岗位列表项 */
export interface MarketJob {
  id: number;
  job_type: JobType | string | null;
  title: string;
  company: string;
  position: string;
  city: string;
  industry: string;
  salary: string;
  degree: string;
  deadline: string | null;
  is_expired: boolean;
  /** 外部投递链接（来源公开渠道） */
  apply_url?: string;
  /** 真实发布时间（缺失时前端回退 created_at） */
  published_at?: string | null;
  created_at: string;
}

/** 岗位详情（列表字段 + 全文） */
export interface MarketJobDetail extends MarketJob {
  content: string;
}

export interface MarketJobListResponse {
  items: MarketJob[];
  total: number;
  page: number;
  limit: number;
  total_pages: number;
}

export interface MarketJobFilters {
  q?: string;
  job_type?: JobType | string;
  city?: string;
  industry?: string;
  company?: string;
  position?: string;
  date_from?: string;
  date_to?: string;
  page?: number;
  limit?: number;
}

/** 岗位统计（近 3/7 日新增 + 累计 + 头部行业） */
export interface MarketJobStats {
  total: number;
  count_3d: number;
  count_7d: number;
  top_industries: Array<{ name: string; count: number }>;
}

export interface MarketJobStatsFilters {
  job_type?: string;
  source?: string;
}

/** 岗位推荐请求 */
export interface RecommendRequest {
  resume_id: number;
  top_k?: number;
  job_type?: JobType | string;
}

/** 岗位推荐项 */
export interface RecommendItem {
  id: string;
  title: string;
  company: string;
  position: string;
  city: string;
  salary: string;
  job_type: JobType;
  score: number;
  matched: string[];
  gaps: string[];
  reason: string;
}

// ── API 函数 ──

/** 岗位列表（job_type 筛选：campus/social/intern） */
export async function listJobs(filters: MarketJobFilters = {}): Promise<MarketJobListResponse> {
  const params = new URLSearchParams();
  if (filters.q) params.set("q", filters.q);
  if (filters.job_type) params.set("job_type", filters.job_type);
  if (filters.city) params.set("city", filters.city);
  if (filters.industry) params.set("industry", filters.industry);
  if (filters.company) params.set("company", filters.company);
  if (filters.position) params.set("position", filters.position);
  if (filters.date_from) params.set("date_from", filters.date_from);
  if (filters.date_to) params.set("date_to", filters.date_to);
  params.set("page", String(filters.page ?? 1));
  params.set("limit", String(filters.limit ?? 20));
  return api.get(`/api/v1/market/jobs?${params}`) as Promise<MarketJobListResponse>;
}

/** 岗位详情 */
export async function getJob(id: number | string): Promise<MarketJobDetail> {
  return api.get(`/api/v1/market/jobs/${encodeURIComponent(String(id))}`) as Promise<MarketJobDetail>;
}

/** 岗位统计（近 3/7 日新增 + 累计 + 头部行业） */
export async function listJobStats(filters: MarketJobStatsFilters = {}): Promise<MarketJobStats> {
  const params = new URLSearchParams();
  if (filters.job_type) params.set("job_type", filters.job_type);
  if (filters.source) params.set("source", filters.source);
  const qs = params.toString();
  return api.get(`/api/v1/market/jobs/stats${qs ? "?" + qs : ""}`) as Promise<MarketJobStats>;
}

/** 基于简历的岗位推荐 */
export async function recommendJobs(body: RecommendRequest): Promise<{ items: RecommendItem[] }> {
  return api.post("/api/v1/market/recommend", body) as Promise<{ items: RecommendItem[] }>;
}
