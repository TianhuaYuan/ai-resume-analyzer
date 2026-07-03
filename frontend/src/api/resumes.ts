import { api } from "./client";

export interface ResumeItem {
  id: number;
  filename: string;
  chunk_count: number;
  created_at: string;
}

export interface UploadResult {
  id: number;
  filename: string;
  preview: string;
  chunk_count: number;
}

export async function listResumes(limit = 20, offset = 0) {
  return api.get(`/api/resumes?limit=${limit}&offset=${offset}`) as Promise<{
    items: ResumeItem[];
    total: number;
  }>;
}

export async function uploadResume(file: File) {
  const form = new FormData();
  form.append("file", file);
  return api.post("/api/resumes", form, true) as Promise<UploadResult>;
}

export async function deleteResume(id: number) {
  return api.delete(`/api/resumes/${id}`);
}
