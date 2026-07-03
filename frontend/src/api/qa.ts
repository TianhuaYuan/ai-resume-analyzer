import { api } from "./client";

export interface AnswerResponse {
  id: number;
  question: string;
  answer: string;
  sources: string[];
  created_at: string;
}

export async function askQuestion(
  resume_id: number,
  question: string
): Promise<AnswerResponse> {
  return api.post("/api/qa/ask", { resume_id, question }) as Promise<AnswerResponse>;
}

export async function getHistory(
  resume_id: number,
  limit = 20,
  offset = 0
) {
  return api.get(
    `/api/qa/history/${resume_id}?limit=${limit}&offset=${offset}`
  ) as Promise<{ items: AnswerResponse[]; total: number }>;
}
