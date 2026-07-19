import { api } from "./client";

export interface ResumeItem {
  id: number;
  filename: string;
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

export async function uploadResume(file: File) {
  const form = new FormData();
  form.append("file", file);
  return api.post("/api/v1/resumes", form, true) as Promise<UploadAsyncResult>;
}

export async function getResume(id: number) {
  return api.get(`/api/v1/resumes/${id}`) as Promise<ResumeItem>;
}

export async function deleteResume(id: number) {
  return api.delete(`/api/v1/resumes/${id}`);
}

export type AnalysisType = "summary" | "skills" | "experience";

export interface AnalyzeResult {
  resume_id: number;
  analysis_type: string;
  analysis: string;
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
