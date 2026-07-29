import { api } from "./client";

export interface ResumeItem {
  id: number;
  filename: string;
  parsed_text: string;
  chunk_count: number;
  status: string;
  status_message: string;
  created_at: string;
}

export interface UploadAsyncResult {
  id: number;
  filename: string;
  status: string;
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
 * 导出供调用方（如 ResumeListPage）预先计算 key 并保存，
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

export interface ChunkItem {
  chunk_index: number;
  section: string;
  text: string;
  start_char: number;
  end_char: number;
}

export interface ChunksResult {
  resume_id: number;
  total: number;
  chunks: ChunkItem[];
}

export async function getChunks(id: number): Promise<ChunksResult> {
  return api.get(`/api/v1/resumes/${id}/chunks`) as Promise<ChunksResult>;
}

export interface MatchJDResult {
  resume_id: number;
  analysis: string;
}

export async function matchJD(
  id: number,
  jdText: string
): Promise<MatchJDResult> {
  return api.post(`/api/v1/resumes/${id}/match-jd`, {
    jd_text: jdText,
  }) as Promise<MatchJDResult>;
}

/** 单个维度的值：summary/skills/experience 是 Markdown 字符串，score 是结构化评分，projects 是项目名列表 */
export type DimensionValue = string | ScoreDetail | string[];

export interface CompareDimensions {
  summary?: Record<string, string>;
  skills?: Record<string, string>;
  experience?: Record<string, string>;
  score?: Record<string, ScoreDetail>;
  projects?: Record<string, string[]>;
}

export interface CompareResult {
  resumes: Array<{ id: number; filename: string }>;
  dimensions: CompareDimensions;
}

export async function compareResumes(
  resumeIds: number[],
  dimensions?: string[]
): Promise<CompareResult> {
  return api.post("/api/v1/resumes/compare", {
    resume_ids: resumeIds,
    dimensions,
  }) as Promise<CompareResult>;
}

export async function exportResume(
  id: number,
  format: string = "markdown"
): Promise<string> {
  const token = localStorage.getItem("access_token");
  const resp = await fetch(`/api/v1/resumes/${id}/export?format=${format}`, {
    headers: {
      Authorization: `Bearer ${token}`,
      "X-Request-ID": crypto.randomUUID?.() ?? "",
    },
  });
  if (!resp.ok) throw new Error(`导出失败: ${resp.status}`);
  return resp.text();
}
