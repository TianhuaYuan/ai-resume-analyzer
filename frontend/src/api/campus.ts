import { api } from "./client";

// ── 类型定义 ──

export interface CampusRecord {
  id: string;
  company: string;
  title: string;
  referralMethod: string;
  referralCode: string | null;
  workLocation: string;
  industry: string;
  positions: string;
  recordTime: string;
  createTime: string;
  remarks: string;
  infoType: string;
}

export interface CampusStats {
  total: number;
  count_3d: number;
  count_7d: number;
  top_industries: Array<{ name: string; count: number }>;
}

export interface CampusListResponse {
  items: CampusRecord[];
  total: number;
  page: number;
  limit: number;
  total_pages: number;
}

export interface CampusFilters {
  q?: string;
  infoType?: string;
  industry?: string;
  workLocation?: string;
  positions?: string;
  dateFrom?: string;
  dateTo?: string;
  page?: number;
  limit?: number;
}

// ── API 函数 ──

export async function getCampusStats(infoType = ""): Promise<CampusStats> {
  const params = new URLSearchParams();
  if (infoType) params.set("info_type", infoType);
  const qs = params.toString();
  return api.get(`/api/v1/campus/stats${qs ? "?" + qs : ""}`) as Promise<CampusStats>;
}

export async function listCampusRecords(filters: CampusFilters = {}): Promise<CampusListResponse> {
  const params = new URLSearchParams();
  if (filters.q) params.set("q", filters.q);
  if (filters.infoType) params.set("info_type", filters.infoType);
  if (filters.industry) params.set("industry", filters.industry);
  if (filters.workLocation) params.set("work_location", filters.workLocation);
  if (filters.positions) params.set("positions", filters.positions);
  if (filters.dateFrom) params.set("date_from", filters.dateFrom);
  if (filters.dateTo) params.set("date_to", filters.dateTo);
  params.set("page", String(filters.page ?? 1));
  params.set("limit", String(filters.limit ?? 20));
  return api.get(`/api/v1/campus/list?${params}`) as Promise<CampusListResponse>;
}

// ── 求职跟踪 ──

export interface CampusTrack {
  campus_record_id: string;
  status: string;
  notes: string | null;
}

export async function getCampusTracks(): Promise<Record<string, CampusTrack>> {
  const data = (await api.get("/api/v1/campus/tracks")) as { tracks: Record<string, CampusTrack> };
  return data.tracks;
}

export async function upsertCampusTrack(
  campus_record_id: string,
  status: string,
  notes: string | null = null
): Promise<CampusTrack> {
  return api.put("/api/v1/campus/tracks", { campus_record_id, status, notes }) as Promise<CampusTrack>;
}

// ── 求职进度选项（带颜色） ──

export interface TrackStatusOption {
  value: string;
  label: string;
  color: string;
  bg: string;
}

export const TRACK_STATUS_OPTIONS: TrackStatusOption[] = [
  { value: "cancelled", label: "取消", color: "text-zinc-400", bg: "bg-zinc-500/10 border-zinc-500/20" },
  { value: "pending", label: "待投递", color: "text-slate-400", bg: "bg-slate-500/10 border-slate-500/20" },
  { value: "applied", label: "已投递", color: "text-blue-400", bg: "bg-blue-500/10 border-blue-500/20" },
  { value: "pending_written", label: "待笔试", color: "text-amber-400", bg: "bg-amber-500/10 border-amber-500/20" },
  { value: "written_passed", label: "已笔试", color: "text-orange-400", bg: "bg-orange-500/10 border-orange-500/20" },
  { value: "first_round", label: "一面", color: "text-cyan-400", bg: "bg-cyan-500/10 border-cyan-500/20" },
  { value: "second_round", label: "二面", color: "text-indigo-400", bg: "bg-indigo-500/10 border-indigo-500/20" },
  { value: "third_round", label: "三面", color: "text-violet-400", bg: "bg-violet-500/10 border-violet-500/20" },
  { value: "offer", label: "Offer", color: "text-emerald-400", bg: "bg-emerald-500/10 border-emerald-500/20" },
  { value: "rejected", label: "已拒绝", color: "text-red-400", bg: "bg-red-500/10 border-red-500/20" },
];

export function getTrackStatusOption(value: string): TrackStatusOption {
  return TRACK_STATUS_OPTIONS.find((o) => o.value === value) ?? TRACK_STATUS_OPTIONS[1];
}
