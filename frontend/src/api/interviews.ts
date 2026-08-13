import { api } from "./client";
import type { KnowledgeAsset } from "./assets";

// ── 类型定义 ──

/** 面试评分卡（object，结构由后端定义，前端透传/展示） */
export type InterviewScorecard = Record<string, unknown>;

/**
 * 后端 /api/v1/interviews 契约（已冻结）：
 * {id, company, position, resume_id, jd_text, questions, answers,
 *  scorecard, notes, status, created_at, updated_at}
 */
export interface InterviewSession {
  id: number;
  company: string;
  position: string;
  resume_id: number | null;
  job_application_id: number | null;
  jd_text: string | null;
  questions: string[] | null;
  answers: string[] | null;
  scorecard: InterviewScorecard | null;
  notes: string | null;
  status: string;
  created_at: string;
  updated_at: string;
}

/** 列表项（不含大字段：questions/answers/jd_text/scorecard），weak_count 为弱项维度数 */
export interface InterviewSummary {
  id: number;
  company: string;
  position: string;
  status: string;
  notes: string | null;
  created_at: string;
  weak_count?: number;
}

export interface InterviewListResponse {
  items: InterviewSummary[];
  total: number;
  page: number;
  limit: number;
}

export interface InterviewListParams {
  page?: number;
  limit?: number;
}

export interface InterviewCreateInput {
  company: string;
  position: string;
  resume_id?: number;
  job_application_id?: number;
  jd_text?: string;
  questions?: string[];
  answers?: string[];
  notes?: string;
  scorecard?: InterviewScorecard;
}

export interface ScorecardUpdateInput {
  scorecard: InterviewScorecard;
  notes?: string;
}

/** PUT /interviews/{id}/scorecard 的实际响应 + 派生 weak_competencies */
export interface ScorecardUpdateResult {
  interview_id: number;
  status: string;
  weak_competencies: string[];
  scorecard: InterviewScorecard;
  notes: string | null;
}

/** GET /interviews/review/summary 复盘概览 */
export interface InterviewReviewSummary {
  frequent_weaknesses: Array<{ competency: string; count: number }>;
  training_plan: {
    modules: Array<{
      id: string;
      competency: string;
      title: string;
      rationale: string;
      est_min: number;
    }>;
    summary: string;
    total_min: number;
  };
  trend: Array<{ period: string; count: number }>;
}

// ── API 函数 ──

/** GET /api/v1/interviews — 分页列表（不含大字段） */
export async function listInterviews(
  params: InterviewListParams = {}
): Promise<InterviewListResponse> {
  const qs = new URLSearchParams();
  qs.set("page", String(params.page ?? 1));
  qs.set("limit", String(params.limit ?? 20));
  return api.get(`/api/v1/interviews?${qs}`) as Promise<InterviewListResponse>;
}

/** GET /api/v1/interviews/{id} — 详情（含 questions/answers/scorecard） */
export async function getInterview(id: number): Promise<InterviewSession> {
  return api.get(`/api/v1/interviews/${id}`) as Promise<InterviewSession>;
}

/** POST /api/v1/interviews — 新建（201 InterviewResponse） */
export async function createInterview(
  body: InterviewCreateInput
): Promise<InterviewSession> {
  return api.post("/api/v1/interviews", body) as Promise<InterviewSession>;
}

/** PUT /api/v1/interviews/{id}/scorecard — 录入/更新评分卡，返回派生 weak_competencies */
export async function updateInterviewScorecard(
  id: number,
  body: ScorecardUpdateInput
): Promise<ScorecardUpdateResult> {
  return api.put(
    `/api/v1/interviews/${id}/scorecard`,
    body
  ) as Promise<ScorecardUpdateResult>;
}

/** DELETE /api/v1/interviews/{id} — 删除（204，client 返回 null） */
export async function deleteInterview(id: number): Promise<null> {
  return api.delete(`/api/v1/interviews/${id}`) as Promise<null>;
}

/** GET /api/v1/interviews/review/summary — 复盘概览（高频薄弱点/训练推荐/趋势） */
export async function getReviewSummary(): Promise<InterviewReviewSummary> {
  return api.get(
    "/api/v1/interviews/review/summary"
  ) as Promise<InterviewReviewSummary>;
}

/** POST /api/v1/interviews/{id}/archive — 归档为知识资产（幂等，供 Agent 检索） */
export async function archiveInterview(id: number): Promise<KnowledgeAsset> {
  return api.post(`/api/v1/interviews/${id}/archive`) as Promise<KnowledgeAsset>;
}
