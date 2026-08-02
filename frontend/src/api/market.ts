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

/** 按 job_type 取中文标签（兼容未知值） */
export function jobTypeLabel(jobType: JobType | string | null | undefined): string {
  if (!jobType) return "";
  return JOB_TYPE_LABELS[jobType as JobType] ?? String(jobType);
}

/** 岗位列表项 */
export interface MarketJob {
  id: number;
  source: string;
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
  created_at: string;
  /** 来源渠道附带的投递信息 */
  payload?: {
    /** 外部投递链接（来源公开渠道） */
    apply_url?: string;
    /** 内推码 */
    referral_code?: string;
    [key: string]: unknown;
  };
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
  source?: string;
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

/** 简历模板（模板画廊 / 模板详情） */
export interface MarketTemplate {
  id: string;
  name: string;
  description: string;
  tags: string[];
  /** 模板布局配置（后端元数据，结构随模板而异） */
  layout: unknown;
  /** 渲染后的预览 HTML（iframe srcDoc 使用） */
  preview_html: string;
}

export interface MarketTemplateListResponse {
  items: MarketTemplate[];
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
  /** 范文原文（content，分节文本） */
  content: string;
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

/** 模板画廊列表 */
export async function listTemplates(): Promise<MarketTemplateListResponse> {
  return api.get("/api/v1/market/templates") as Promise<MarketTemplateListResponse>;
}

/** 模板详情 */
export async function getTemplate(id: string): Promise<MarketTemplate> {
  return api.get(`/api/v1/market/templates/${encodeURIComponent(id)}`) as Promise<MarketTemplate>;
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
