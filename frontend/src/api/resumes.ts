import { api } from "./client";

export interface ResumeItem {
  id: number;
  filename: string;
  parsed_text: string;
  chunk_count: number;
  status: string;
  status_message: string;
  created_at: string;
  updated_at: string;
  // T17: 索引新鲜度（懒索引脏标记）
  //   content_hash: 当前内容哈希；indexed_hash: 上次成功索引时的哈希
  //   is_indexed = indexed_hash 非空；is_stale = content_hash != indexed_hash
  content_hash?: string | null;
  indexed_hash?: string | null;
  is_indexed?: boolean;
  is_stale?: boolean;
  // 卡片预览：模块列表 + 样式（不传时前端兜底灰色占位）
  modules_data?: {
    modules: Array<{ module_type: string; content: Record<string, unknown>; sort_order: number }>;
    style: Record<string, unknown> | null;
  } | null;
  // 解析进度：{stage: parsing|materializing|done|partial|failed, percent, message}
  parse_progress?: {
    stage: string;
    percent: number;
    message: string;
  } | null;
}

export interface UploadAsyncResult {
  id: number;
  filename: string;
  status: string;
  /** 处理完成预计耗时（秒），用于提示"预计等待时间" */
  estimated_seconds?: number;
}

export async function listResumes(limit = 20, offset = 0) {
  return api.get(`/api/v1/resumes?limit=${limit}&offset=${offset}`) as Promise<{
    items: ResumeItem[];
    total: number;
  }>;
}

/**
 * Task 2.6: 基于 file 元信息生成幂等键。
 *
 * 同文件（同名+同 size+同 lastModified）重复上传生成相同 key，
 * 后端命中 idempotency cache 自动返回首次结果，避免重复入库。
 *
 * 注意：不读取 file 内容做 hash，因为：
 * 1. 内容读取需 await file.arrayBuffer()，对大文件有性能开销
 * 2. lastModified 已能区分"用户修改后重新上传"场景
 * 3. 元信息 hash 已足够防"双击/网络重发"场景
 *
 * 导出供调用方（如 HomePage / Sidebar）预先计算 key 并保存，
 * 用于网络失败重试时复用同 key 实现真正幂等。
 */
export async function generateIdempotencyKey(file: File): Promise<string> {
  const meta = `${file.name}|${file.size}|${file.lastModified}`;
  // SubtleCrypto SHA-256 → 64 位 hex（浏览器原生，无依赖）
  const buf = new TextEncoder().encode(meta);
  const hashBuf = await crypto.subtle.digest("SHA-256", buf);
  return Array.from(new Uint8Array(hashBuf))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

/**
 * Task 2.6: 上传简历，附带 Idempotency-Key 实现幂等。
 *
 * @param file 简历文件
 * @param overrideKey 可选，重试场景复用旧 key（如网络失败后重试）。
 *                    未传则基于 file 元信息计算 hash。
 */
export async function uploadResume(file: File, overrideKey?: string) {
  const idempotencyKey = overrideKey ?? (await generateIdempotencyKey(file));
  const form = new FormData();
  form.append("file", file);
  return api.post("/api/v1/resumes", form, true, {
    "Idempotency-Key": idempotencyKey,
  }) as Promise<UploadAsyncResult>;
}

export async function getResume(id: number) {
  return api.get(`/api/v1/resumes/${id}`) as Promise<ResumeItem>;
}

export async function deleteResume(id: number) {
  return api.delete(`/api/v1/resumes/${id}`);
}

/** 多语言版本族中的一个版本（GET /resumes/{id}/family 返回项） */
export interface ResumeFamilyItem {
  id: number;
  filename: string;
  language: string | null;
  created_at: string;
  source: string;
}

/** 复制为新语言版本（language 如 zh/en，空则未标注）。返回新副本 BuilderResumeResponse */
export async function copyResume(id: number, language?: string): Promise<unknown> {
  const q = language ? `?language=${encodeURIComponent(language)}` : "";
  return api.post(`/api/v1/resumes/${id}/copy${q}`);
}

/** 获取同 family 的所有语言版本（含自身），用于多语言版本管理下拉 */
export async function getResumeFamily(id: number): Promise<ResumeFamilyItem[]> {
  return api.get(`/api/v1/resumes/${id}/family`) as Promise<ResumeFamilyItem[]>;
}

// Task 1.3: 重试失败的简历处理。后端会将 status 改回 processing 并重新触发解析。
// 仅 status=failed 的简历可重试，否则后端返回 409。
export async function retryResume(id: number) {
  return api.post(`/api/v1/resumes/${id}/retry`) as Promise<UploadAsyncResult>;
}

export type AnalysisType = "summary" | "skills" | "experience" | "score";

export interface ScoreDetail {
  ats_match: number;
  keyword_coverage: number;
  skill_density: number;
  overall: number;
}

export interface AnalyzeResult {
  resume_id: number;
  analysis_type: string;
  analysis: string;
  scores: ScoreDetail | null;
}

export async function analyzeResume(
  id: number,
  analysisType: AnalysisType
): Promise<AnalyzeResult> {
  return api.post(`/api/v1/resumes/${id}/analyze`, {
    analysis_type: analysisType,
  }) as Promise<AnalyzeResult>;
}

export interface RoleScoreItem {
  score: number;
  summary: string;
}

export interface RoleScoreResult {
  resume_id: number;
  analysis_type: string;
  analysis: string;
  roles: Record<string, RoleScoreItem>;
  aggregate: { score: number; band: string; weights: Record<string, number> } | null;
  target_position: string | null;
  evidence?: { start: number; end: number; quote: string }[];
  evidence_quote?: string | null;
}

/** E3 多角色评分：peer/lead/HRBP 各打 0-100 + rubric 加权聚合（含证据锚定） */
export async function roleScore(
  id: number,
  targetPosition?: string
): Promise<RoleScoreResult> {
  return api.post(`/api/v1/resumes/${id}/role-score`, {
    target_position: targetPosition ?? null,
  }) as Promise<RoleScoreResult>;
}

// ── T18: 版本浏览 ─────────────────────────────────────────────

export interface ResumeVersionInfo {
  version: number;
  is_latest: boolean;
  chunk_count: number;
  sections: string[];
}

export interface ResumeVersionsResult {
  versions: ResumeVersionInfo[];
  current_version: number;
}

/** 查简历的索引版本历史（版本号 / 是否最新 / chunk 数 / 节段列表） */
export async function getResumeVersions(
  id: number,
): Promise<ResumeVersionsResult> {
  return api.get(`/api/v1/resumes/${id}/versions`) as Promise<ResumeVersionsResult>;
}

/** I1: JD 6-block 评估报告（角色摘要/CV匹配/级别策略/薪酬市场/个性化计划/面试故事/岗位可信度） */
export interface JdReport {
  role_summary?: {
    archetype?: string;
    domain?: string;
    function?: string;
    seniority?: string;
    remote?: string;
    team_size?: string;
    tldr?: string;
  };
  cv_match?: {
    table?: { jd_requirement: string; cv_evidence: string; status: string }[];
    gaps?: { type: string; adjacent: string; mitigation: string }[];
  };
  level_strategy?: {
    jd_level?: string;
    candidate_level?: string;
    sell_senior_plan?: string;
    downlevel_plan?: string;
  };
  comp_market?: {
    market_range?: string;
    base_hint?: string;
    sources?: string[];
    notes?: string;
  };
  personalization_plan?: {
    cv_changes?: { section: string; current: string; proposed: string; why: string }[];
    linkedin_changes?: string[];
  };
  interview_stories?: {
    jd_requirement: string;
    story_title: string;
    s: string;
    t: string;
    a: string;
    r: string;
    reflection: string;
  }[];
  job_credibility?: {
    tier?: string;
    signals?: { signal: string; risk: string; note: string }[];
    conclusion?: string;
  };
}

export interface MatchJDResult {
  resume_id: number;
  analysis: string;
  /** A3 结构化匹配（Magic-Resume FitReport 契约对照；LLM JSON 输出失败时为 null/空） */
  scores?: { overall: number; band: string } | null;
  /** E3: 四维 JD fit（technical/experience/behavioral/career） */
  dims?: { technical?: number; experience?: number; behavioral?: number; career?: number } | null;
  matched_keywords?: string[];
  missing_keywords?: string[];
  gaps?: string[];
  /** I1: 6-block 求职评估报告（JDMatchTool 生成） */
  report?: JdReport | null;
}

export async function matchJD(
  id: number,
  jdText: string
): Promise<MatchJDResult> {
  return api.post(`/api/v1/resumes/${id}/match-jd`, {
    jd_text: jdText,
  }) as Promise<MatchJDResult>;
}

// ── P0-A: ATS 可读性审计 ──────────────────────────────────

export interface AtsAuditIssue {
  section: string;
  issue_type: string;
  severity: string; // "high" | "medium" | "low"
  message: string;
  suggestion: string;
  context?: string | null;
}

export interface AtsAuditResult {
  resume_id: number;
  ats_score: number;
  issue_count: number;
  issues: AtsAuditIssue[];
  method: string; // "html" | "pdf" | "pdf+html"
  pdf_available: boolean;
  warnings: string[];
}

export async function auditResume(id: number): Promise<AtsAuditResult> {
  return api.post(`/api/v1/resumes/${id}/ats-audit`) as Promise<AtsAuditResult>;
}
