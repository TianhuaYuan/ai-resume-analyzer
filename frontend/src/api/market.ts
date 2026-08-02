/**
 * Market — 市场数据 API client。
 *
 * 对接后端 /api/v1/market/* 端点：
 * - GET    /api/v1/market/jobs        社招/校招/实习岗位列表
 * - GET    /api/v1/market/jobs/{id}   岗位详情（含全文 content + payload）
 * - GET    /api/v1/market/samples     简历范文列表
 * - GET    /api/v1/market/samples/{id} 范文详情（payload 含 target_position / style / modules）
 * - GET    /api/v1/market/guides      求职攻略列表（title/summary/date/url/has_fulltext）
 * - GET    /api/v1/market/guides/{id} 攻略详情（content 为正文；未抓取时为摘要）
 * - POST   /api/v1/market/recommend   基于简历的岗位推荐（matched/gaps/reason）
 */

import { api } from "./client";
import type { ResumeModuleInput, ResumeStyle } from "./builder";

// ── 类型定义 ──

/** 岗位类型枚举（与后端 job_type 对齐） */
export type JobType = "campus" | "social" | "intern";

/** job_type 中文标签 */
export const JOB_TYPE_LABELS: Record<JobType, string> = {
  campus: "校招",
  social: "社招",
  intern: "实习",
};

/** 岗位列表项 */
export interface MarketJob {
  id: string;
  source: string;
  job_type: JobType;
  title: string;
  company: string;
  position: string;
  city: string;
  industry: string;
  salary: string;
  degree: string;
  deadline: string | null;
  is_expired: boolean;
  created_at: string;
}

/** 岗位详情（含全文 + 可选的 payload） */
export interface MarketJobDetail extends MarketJob {
  content: string;
  payload?: {
    /** 外部投递链接（来源公开渠道） */
    apply_url?: string;
    [key: string]: unknown;
  };
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
  source?: string;
  city?: string;
  industry?: string;
  company?: string;
  page?: number;
  limit?: number;
}

/** 简历范文列表项 */
export interface ResumeSample {
  id: string;
  title: string;
  /** 目标岗位 */
  position: string;
  category: string;
  created_at: string;
}

/** 范文 payload（后端惰性转换生成，可能为空） */
export interface SamplePayload {
  target_position?: string;
  style?: ResumeStyle | null;
  modules?: ResumeModuleInput[];
}

export interface ResumeSampleDetail {
  id: string;
  title: string;
  position: string;
  category: string;
  created_at: string;
  payload?: SamplePayload;
}

export interface SampleListResponse {
  items: ResumeSample[];
  total: number;
  page: number;
  limit: number;
  total_pages: number;
}

export interface SampleFilters {
  q?: string;
  page?: number;
  limit?: number;
}

/** 求职攻略列表项（正文未抓取时跳原文链接） */
export interface MarketGuideItem {
  id: number;
  title: string;
  summary: string;
  /** 发布日期（原文页面上的日期，可能为空） */
  date: string | null;
  /** 原文外链（upcv.tech 等公开来源） */
  url: string | null;
  /** 是否已抓取正文（true 时可站内阅读 content） */
  has_fulltext: boolean;
}

/** 攻略详情（content 为正文；未抓取时为摘要） */
export interface MarketGuideDetail extends MarketGuideItem {
  content: string;
}

export interface MarketGuideListResponse {
  items: MarketGuideItem[];
  total: number;
  page: number;
  limit: number;
  total_pages: number;
}

export interface GuideFilters {
  q?: string;
  page?: number;
  limit?: number;
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
  if (filters.source) params.set("source", filters.source);
  if (filters.city) params.set("city", filters.city);
  if (filters.industry) params.set("industry", filters.industry);
  if (filters.company) params.set("company", filters.company);
  params.set("page", String(filters.page ?? 1));
  params.set("limit", String(filters.limit ?? 20));
  return api.get(`/api/v1/market/jobs?${params}`) as Promise<MarketJobListResponse>;
}

/** 岗位详情 */
export async function getJob(id: string): Promise<MarketJobDetail> {
  return api.get(`/api/v1/market/jobs/${encodeURIComponent(id)}`) as Promise<MarketJobDetail>;
}

/** 简历范文列表 */
export async function listSamples(filters: SampleFilters = {}): Promise<SampleListResponse> {
  const params = new URLSearchParams();
  if (filters.q) params.set("q", filters.q);
  params.set("page", String(filters.page ?? 1));
  params.set("limit", String(filters.limit ?? 12));
  return api.get(`/api/v1/market/samples?${params}`) as Promise<SampleListResponse>;
}

/** 简历范文详情 */
export async function getSample(id: string): Promise<ResumeSampleDetail> {
  return api.get(`/api/v1/market/samples/${encodeURIComponent(id)}`) as Promise<ResumeSampleDetail>;
}

/** 求职攻略列表 */
export async function listGuides(filters: GuideFilters = {}): Promise<MarketGuideListResponse> {
  const params = new URLSearchParams();
  if (filters.q) params.set("q", filters.q);
  params.set("page", String(filters.page ?? 1));
  params.set("limit", String(filters.limit ?? 12));
  return api.get(`/api/v1/market/guides?${params}`) as Promise<MarketGuideListResponse>;
}

/** 求职攻略详情 */
export async function getGuide(id: number | string): Promise<MarketGuideDetail> {
  return api.get(`/api/v1/market/guides/${encodeURIComponent(String(id))}`) as Promise<MarketGuideDetail>;
}

/** 基于简历的岗位推荐 */
export async function recommendJobs(body: RecommendRequest): Promise<{ items: RecommendItem[] }> {
  return api.post("/api/v1/market/recommend", body) as Promise<{ items: RecommendItem[] }>;
}
