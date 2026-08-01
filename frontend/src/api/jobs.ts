import { api } from "./client";

// ── Types ──

export type JobStatus =
  | "wishlist"
  | "applied"
  | "interview"
  | "offer"
  | "rejected"
  | "accepted";

export interface JobApplication {
  id: number;
  user_id: number;
  resume_id: number | null;
  company: string;
  position: string;
  city: string | null;
  salary_range: string | null;
  status: string;
  applied_at: string | null;
  created_at: string;
}

export interface JobApplicationCreate {
  company: string;
  position: string;
  city?: string | null;
  salary_range?: string | null;
  status?: string;
  resume_id?: number | null;
  applied_at?: string | null;
}

export interface JobApplicationUpdate {
  company?: string;
  position?: string;
  city?: string | null;
  salary_range?: string | null;
  status?: string;
  resume_id?: number | null;
  applied_at?: string | null;
}

export interface JobApplicationListResponse {
  items: JobApplication[];
  total: number;
}

export interface CompanyCount {
  company: string;
  count: number;
}

export interface CityCount {
  city: string;
  count: number;
}

export interface TrendPoint {
  date: string;
  count: number;
}

export interface KanbanStats {
  by_status: Record<string, number>;
  by_company: CompanyCount[];
  by_city: CityCount[];
  trend: TrendPoint[];
  total: number;
}

// ── 看板列配置 ──

export const KANBAN_COLUMNS: Array<{
  status: JobStatus;
  label: string;
  color: string;
}> = [
  { status: "wishlist", label: "意向", color: "#a78bfa" },
  { status: "applied", label: "已投递", color: "#38bdf8" },
  { status: "interview", label: "面试中", color: "#f59e0b" },
  { status: "offer", label: "Offer", color: "#34d399" },
  { status: "rejected", label: "已拒绝", color: "#f87171" },
  { status: "accepted", label: "已接受", color: "#22c55e" },
];

export const STATUS_LABELS: Record<string, string> = Object.fromEntries(
  KANBAN_COLUMNS.map((c) => [c.status, c.label]),
);

// ── API functions ──

export async function createJobApplication(
  data: JobApplicationCreate,
): Promise<JobApplication> {
  return api.post("/api/v1/jobs", data) as Promise<JobApplication>;
}

export async function listJobApplications(
  status?: string,
  limit = 100,
  offset = 0,
): Promise<JobApplicationListResponse> {
  const params = new URLSearchParams();
  params.set("limit", String(limit));
  params.set("offset", String(offset));
  if (status) params.set("status", status);
  return api.get(
    `/api/v1/jobs?${params.toString()}`,
  ) as Promise<JobApplicationListResponse>;
}

export async function getJobApplication(id: number): Promise<JobApplication> {
  return api.get(`/api/v1/jobs/${id}`) as Promise<JobApplication>;
}

export async function updateJobApplication(
  id: number,
  data: JobApplicationUpdate,
): Promise<JobApplication> {
  return api.put(`/api/v1/jobs/${id}`, data) as Promise<JobApplication>;
}

export async function deleteJobApplication(id: number): Promise<void> {
  await api.delete(`/api/v1/jobs/${id}`);
}

export async function getKanbanStats(): Promise<KanbanStats> {
  return api.get("/api/v1/jobs/kanban") as Promise<KanbanStats>;
}
