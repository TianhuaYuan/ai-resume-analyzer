/**
 * CampusPage — 校招 + 内推信息浏览页。
 *
 * Tab 切换：校招信息 / 内推企业 / 投递进展
 * 数据源：/api/v1/market/jobs（job_type=campus | social&source=referral）+ /api/v1/market/jobs/stats
 * 高级筛选：发布日期范围、工作地点、行业、岗位
 * 求职进度：颜色区分的下拉选择 + 备注（track 仍走 /api/v1/campus/tracks，key 用 String(job.id)）
 */

import { useEffect, useState, useCallback, useRef } from "react";
import { deadlineInfo } from "../utils/deadline";
import {
  CalendarBlank,
  Clock,
  Users,
  MagnifyingGlass,
  Link,
  MapPin,
  User,
  CaretLeft,
  CaretRight,
  Note,
  Funnel,
  X,
  DownloadSimple,
} from "@phosphor-icons/react";
import {
  listJobs,
  listJobStats,
  type MarketJob,
  type MarketJobStats,
  type MarketJobFilters,
} from "../api/market";
import {
  getCampusTracks,
  upsertCampusTrack,
  TRACK_STATUS_OPTIONS,
  getTrackStatusOption,
  type CampusTrack,
} from "../api/campus";

// ── Tab 定义 ──
type TabKey = "campus" | "progress";
const TABS: Array<{ key: TabKey; label: string }> = [
  { key: "campus", label: "校招信息" },
  { key: "progress", label: "投递进展" },
];

function formatDate(dateStr: unknown): string {
  if (typeof dateStr !== "string" || !dateStr) return "-";
  const normalized = /[Z+]/.test(dateStr) ? dateStr : dateStr + "Z";
  const d = new Date(normalized);
  if (isNaN(d.getTime())) return dateStr.slice(0, 10);
  return d.toLocaleDateString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit" });
}

function truncate(text: string, maxLen: number): string {
  if (text.length <= maxLen) return text;
  return text.slice(0, maxLen) + "...";
}

// ── CSV 导出 ──

function exportProgressCSV(records: MarketJob[], tracks: Record<string, CampusTrack>) {
  const headers = ["发布时间", "截止", "公司", "投递链接", "求职进度", "备注", "工作地点", "岗位"];
  const statusLabelMap = Object.fromEntries(TRACK_STATUS_OPTIONS.map((o) => [o.value, o.label]));
  const rows = records
    .filter((r) => tracks[String(r.id)])
    .map((r) => {
      const t = tracks[String(r.id)];
      return [
        formatDate(r.published_at ?? r.created_at),
        r.company ?? "",
        r.apply_url ?? "",
        statusLabelMap[t.status] ?? t.status,
        t.notes ?? "",
        r.city ?? "",
        r.position ?? "",
      ];
    });

  const csvContent =
    "﻿" +
    [headers, ...rows]
      .map((row) => row.map((cell) => `"${String(cell).replace(/"/g, '""')}"`).join(","))
      .join("\n");

  const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `投递进展_${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

// ── 高级筛选面板 ──

interface AdvancedFilters {
  city: string;
  position: string;
  dateFrom: string;
  dateTo: string;
}

interface AdvancedFilterProps {
  open: boolean;
  filters: AdvancedFilters;
  onApply: (filters: AdvancedFilters) => void;
  onClose: () => void;
}

function AdvancedFilterPanel({ open, filters, onApply, onClose }: AdvancedFilterProps) {
  const [local, setLocal] = useState(filters);
  useEffect(() => { setLocal(filters); }, [filters]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="glass-card w-full max-w-sm shadow-2xl animate-fade-in-up">
        <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--color-border)]">
          <h3 className="text-sm font-semibold text-[var(--color-text)]">高级筛选</h3>
          <button onClick={onClose} className="p-1 rounded-lg text-[var(--color-text-muted)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-secondary)] transition-colors cursor-pointer">
            <X size={16} weight="bold" />
          </button>
        </div>
        <div className="px-5 py-4 space-y-4">
          <div>
            <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">发布日期</label>
            <div className="flex items-center gap-2">
              <input type="date" value={local.dateFrom} onChange={(e) => setLocal((p) => ({ ...p, dateFrom: e.target.value }))}
                className="flex-1 px-3 py-1.5 rounded-xl bg-[#F2F2F7] border border-transparent text-xs text-[var(--color-text)] focus:outline-none focus:bg-white focus:border-brand/40 focus:ring-4 focus:ring-brand/15" />
              <span className="text-[var(--color-text-muted)] text-xs">→</span>
              <input type="date" value={local.dateTo} onChange={(e) => setLocal((p) => ({ ...p, dateTo: e.target.value }))}
                className="flex-1 px-3 py-1.5 rounded-xl bg-[#F2F2F7] border border-transparent text-xs text-[var(--color-text)] focus:outline-none focus:bg-white focus:border-brand/40 focus:ring-4 focus:ring-brand/15" />
            </div>
          </div>
          <div>
            <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">工作地点</label>
            <input type="text" value={local.city} onChange={(e) => setLocal((p) => ({ ...p, city: e.target.value }))}
              placeholder="请输入工作地点" className="w-full px-3 py-1.5 rounded-xl bg-[#F2F2F7] border border-transparent text-xs text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] focus:outline-none focus:bg-white focus:border-brand/40 focus:ring-4 focus:ring-brand/15" />
          </div>
          <div>
            <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">岗位</label>
            <input type="text" value={local.position} onChange={(e) => setLocal((p) => ({ ...p, position: e.target.value }))}
              placeholder="请输入岗位" className="w-full px-3 py-1.5 rounded-xl bg-[#F2F2F7] border border-transparent text-xs text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] focus:outline-none focus:bg-white focus:border-brand/40 focus:ring-4 focus:ring-brand/15" />
          </div>
        </div>
        <div className="flex items-center justify-end gap-2 px-5 py-3 border-t border-[var(--color-border)]">
          <button onClick={() => { setLocal({ city: "", position: "", dateFrom: "", dateTo: "" }); }}
            className="px-4 py-1.5 rounded-full bg-[var(--color-bg-secondary)] text-xs text-[var(--color-text-secondary)] hover:bg-[#E5E5EA] transition-all cursor-pointer">
            重 置
          </button>
          <button onClick={() => { onApply(local); onClose(); }}
            className="px-4 py-1.5 rounded-full bg-brand text-white text-xs font-medium hover:bg-[#0077ed] hover:scale-[1.02] active:scale-[0.98] transition-all duration-300 cursor-pointer">
            应用筛选
          </button>
        </div>
      </div>
    </div>
  );
}

// ── 主组件 ──

export default function CampusPage() {
  const [tab, setTab] = useState<TabKey>("campus");
  const [stats, setStats] = useState<MarketJobStats | null>(null);
  const [records, setRecords] = useState<MarketJob[]>([]);
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(0);
  const [page, setPage] = useState(1);
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [tracks, setTracks] = useState<Record<string, CampusTrack>>({});
  const [editingNotes, setEditingNotes] = useState<Record<string, string>>({});
  const [filterOpen, setFilterOpen] = useState(false);
  const [advancedFilters, setAdvancedFilters] = useState<AdvancedFilters>({ city: "", position: "", dateFrom: "", dateTo: "" });
  const [activeFilters, setActiveFilters] = useState<AdvancedFilters>({ city: "", position: "", dateFrom: "", dateTo: "" });
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const isProgress = tab === "progress";

  const handleQueryChange = useCallback((val: string) => {
    setQuery(val);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => { setDebouncedQuery(val); setPage(1); }, 300);
  }, []);

  const handleStatusChange = useCallback(async (recordId: string, newStatus: string) => {
    const track = tracks[recordId];
    const notes = track?.notes ?? null;
    setTracks((prev) => ({ ...prev, [recordId]: { campus_record_id: recordId, status: newStatus, notes } }));
    await upsertCampusTrack(recordId, newStatus, notes).catch(() => {});
  }, [tracks]);

  const handleNotesBlur = useCallback(async (recordId: string) => {
    const notes = editingNotes[recordId];
    if (notes === undefined) return;
    const track = tracks[recordId];
    const status = track?.status ?? "pending";
    setTracks((prev) => ({ ...prev, [recordId]: { campus_record_id: recordId, status, notes: notes || null } }));
    setEditingNotes((prev) => { const next = { ...prev }; delete next[recordId]; return next; });
    await upsertCampusTrack(recordId, status, notes || null).catch(() => {});
  }, [editingNotes, tracks]);

  // Tab 切换时重置筛选
  useEffect(() => {
    setQuery(""); setDebouncedQuery(""); setPage(1);
    setAdvancedFilters({ city: "", position: "", dateFrom: "", dateTo: "" });
    setActiveFilters({ city: "", position: "", dateFrom: "", dateTo: "" });
  }, [tab]);

  // 加载统计（近 3/7 日 + 累计 + 头部行业）
  useEffect(() => {
    listJobStats({ job_type: tab === "campus" ? "campus" : undefined })
      .then(setStats)
      .catch(() => setStats(null));
  }, [tab]);

  // 加载求职跟踪
  useEffect(() => { getCampusTracks().then(setTracks).catch(() => {}); }, []);

  // 加载岗位列表
  useEffect(() => {
    setLoading(true);
    const filters: MarketJobFilters = { page, limit: 20 };
    if (debouncedQuery) filters.q = debouncedQuery;
    if (tab === "campus") filters.job_type = "campus";
    if (activeFilters.city) filters.city = activeFilters.city;
    if (activeFilters.position) filters.position = activeFilters.position;
    if (activeFilters.dateFrom) filters.date_from = activeFilters.dateFrom;
    if (activeFilters.dateTo) filters.date_to = activeFilters.dateTo;
    listJobs(filters)
      .then((data) => { setRecords(data.items); setTotal(data.total); setTotalPages(data.total_pages); })
      .catch(() => { setRecords([]); setTotal(0); setTotalPages(0); })
      .finally(() => setLoading(false));
  }, [debouncedQuery, tab, page, activeFilters]);

  const hasActiveFilters = activeFilters.city || activeFilters.position || activeFilters.dateFrom || activeFilters.dateTo;

  // 投递进展：只显示有 track 的记录
  const progressRecords = isProgress
    ? records.filter((r) => tracks[String(r.id)])
    : records;

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-[1200px] mx-auto px-6 py-6">
        {/* ── 统计卡 ── */}
        <div className="grid grid-cols-3 gap-4 mb-6">
          <div className="glass-card p-5 hover:-translate-y-1 hover:shadow-xl hover:shadow-black/5 transition-all duration-300">
            <div className="flex items-center gap-2 mb-2">
              <CalendarBlank size={16} weight="duotone" className="text-brand" />
              <span className="text-xs font-medium text-[var(--color-text-secondary)]">近三日更新数量</span>
            </div>
            <span className="text-3xl font-bold text-[var(--color-text)] tabular-nums">{stats?.count_3d?.toLocaleString() ?? "-"}</span>
            <div className="flex items-center gap-1.5 mt-2">
              <span className="w-1.5 h-1.5 rounded-full bg-brand" />
              <span className="text-[10px] text-[var(--color-text-muted)]">实时更新</span>
            </div>
          </div>
          <div className="glass-card p-5 hover:-translate-y-1 hover:shadow-xl hover:shadow-black/5 transition-all duration-300">
            <div className="flex items-center gap-2 mb-2">
              <Clock size={16} weight="duotone" className="text-emerald-500" />
              <span className="text-xs font-medium text-[var(--color-text-secondary)]">近七日更新数量</span>
            </div>
            <span className="text-3xl font-bold text-[var(--color-text)] tabular-nums">{stats?.count_7d?.toLocaleString() ?? "-"}</span>
            <div className="flex items-center gap-1.5 mt-2">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
              <span className="text-[10px] text-[var(--color-text-muted)]">每周统计</span>
            </div>
          </div>
          <div className="glass-card p-5 hover:-translate-y-1 hover:shadow-xl hover:shadow-black/5 transition-all duration-300">
            <div className="flex items-center gap-2 mb-2">
              <Users size={16} weight="duotone" className="text-purple-500" />
              <span className="text-xs font-medium text-[var(--color-text-secondary)]">累计更新数量</span>
            </div>
            <span className="text-3xl font-bold text-[var(--color-text)] tabular-nums">{stats?.total?.toLocaleString() ?? "-"}</span>
            <div className="flex items-center gap-1.5 mt-2">
              <span className="w-1.5 h-1.5 rounded-full bg-purple-500" />
              <span className="text-[10px] text-[var(--color-text-muted)]">持续增长中</span>
            </div>
          </div>
        </div>

        {/* ── Tab 栏 ── */}
        <div className="flex items-center gap-1 mb-4 border-b border-[var(--color-border)]">
          {TABS.map((t) => (
            <button key={t.key} onClick={() => setTab(t.key)}
              className={`px-4 py-2.5 text-xs font-medium transition-all cursor-pointer border-b-2 -mb-px
                ${tab === t.key
                  ? "text-brand border-brand"
                  : "text-[var(--color-text-muted)] border-transparent hover:text-[var(--color-text-secondary)]"
                }`}>
              {t.label}
            </button>
          ))}
        </div>

        {/* ── 工具栏 ── */}
        <div className="flex items-center gap-2 mb-4">
          <div className="relative flex-1 max-w-md">
            <MagnifyingGlass size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--color-text-muted)]" />
            <input type="text" value={query} onChange={(e) => handleQueryChange(e.target.value)}
              placeholder={isProgress ? "搜索公司、岗位、地点、行业、备注..." : "搜索公司、标题、岗位、地点..."}
              className="w-full pl-9 pr-3 py-2 rounded-xl bg-[#F2F2F7] border border-transparent
                text-sm text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] focus:outline-none focus:bg-white focus:border-brand/40 focus:ring-4 focus:ring-brand/15 transition-colors" />
          </div>
          {!isProgress && (
            <button onClick={() => setFilterOpen(true)}
              className={`flex items-center gap-1.5 px-3 py-2 rounded-full text-xs font-medium transition-all cursor-pointer
                ${hasActiveFilters
                  ? "bg-brand/10 text-brand border border-brand/30"
                  : "bg-[var(--color-bg-secondary)] text-[var(--color-text-secondary)] hover:bg-[#E5E5EA]"
                }`}>
              <Funnel size={13} />
              高级筛选
            </button>
          )}
          {isProgress && progressRecords.length > 0 && (
            <button onClick={() => exportProgressCSV(records, tracks)}
              className="flex items-center gap-1.5 px-3 py-2 rounded-full bg-[var(--color-bg-secondary)]
                text-xs font-medium text-[var(--color-text-secondary)] hover:bg-[#E5E5EA] transition-all cursor-pointer">
              <DownloadSimple size={13} />
              导出
            </button>
          )}
          <span className="text-xs text-[var(--color-text-muted)] tabular-nums shrink-0">
            {loading ? "加载中..." : `${total.toLocaleString()} 条结果`}
          </span>
        </div>

        {/* ── 投递 Momentum 统计条（fieldwork MomentumStrip 对照：已投递/进行中/Offer/已拒绝）── */}
        {isProgress && progressRecords.length > 0 && (() => {
          const trackList = Object.values(tracks);
          const momentumStats = [
            { label: "已投递", value: trackList.filter((t) => t.status !== "pending" && t.status !== "cancelled").length },
            { label: "进行中", value: trackList.filter((t) => ["applied", "pending_written", "written_passed", "first_round", "second_round", "third_round"].includes(t.status)).length },
            { label: "Offer", value: trackList.filter((t) => t.status === "offer").length },
            { label: "已拒绝", value: trackList.filter((t) => t.status === "rejected").length },
          ];
          return (
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
              {momentumStats.map((s) => (
                <div key={s.label} className="rounded-xl border border-[var(--color-border)] bg-[var(--color-card)] px-4 py-3">
                  <p className="text-lg font-bold tabular-nums text-[var(--color-text)]">{s.value}</p>
                  <p className="text-[11px] text-[var(--color-text-muted)] mt-0.5">{s.label}</p>
                </div>
              ))}
            </div>
          );
        })()}

        {/* ── 表格 ── */}
        <div className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-card)] overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[var(--color-border)] bg-[var(--color-bg-secondary)]">
                  <th className="text-left px-4 py-3 text-xs font-medium text-[var(--color-text-secondary)] whitespace-nowrap">发布时间</th>
                  <th className="text-left px-4 py-3 text-xs font-medium text-[var(--color-text-secondary)] whitespace-nowrap">截止</th>
                  <th className="text-left px-4 py-3 text-xs font-medium text-[var(--color-text-secondary)]">公司</th>
                  {!isProgress && <th className="text-left px-4 py-3 text-xs font-medium text-[var(--color-text-secondary)]">标题</th>}
                  <th className="text-left px-4 py-3 text-xs font-medium text-[var(--color-text-secondary)] whitespace-nowrap">投递方式</th>
                  <th className="text-left px-4 py-3 text-xs font-medium text-[var(--color-text-secondary)]">求职进度</th>
                  <th className="text-left px-4 py-3 text-xs font-medium text-[var(--color-text-secondary)]">备注</th>
                  <th className="text-left px-4 py-3 text-xs font-medium text-[var(--color-text-secondary)]">工作地点</th>
                  <th className="text-left px-4 py-3 text-xs font-medium text-[var(--color-text-secondary)]">岗位</th>
                </tr>
              </thead>
              <tbody>
                {(isProgress ? progressRecords : records).map((r) => {
                  const track = tracks[String(r.id)];
                  const statusOpt = getTrackStatusOption(track?.status ?? "pending");
                  return (
                    <tr key={r.id} className="border-b border-[var(--color-border)] last:border-b-0 hover:bg-[var(--color-bg-secondary)] transition-colors">
                      <td className="px-4 py-3 text-xs text-[var(--color-text-muted)] whitespace-nowrap tabular-nums">
                        {formatDate(r.published_at ?? r.created_at)}
                      </td>
                      {/* 截止日期分级着色（Job deadlineInfo 对照：<=3 红 / <=7 黄 / 过期深红 / 正常绿） */}
                      <td className={`px-4 py-3 text-xs whitespace-nowrap ${deadlineInfo(r.deadline, r.is_expired).className}`}>
                        {deadlineInfo(r.deadline, r.is_expired).text}
                      </td>
                      <td className="px-4 py-3 text-xs font-semibold text-[var(--color-text)] whitespace-nowrap">{r.company}</td>
                      {!isProgress && (
                        <td className="px-4 py-3 text-xs text-[var(--color-text-secondary)] max-w-[200px]">
                          <span title={r.title}>{truncate(r.title || "-", 30)}</span>
                        </td>
                      )}
                      <td className="px-4 py-3 whitespace-nowrap">
                        {r.apply_url ? (
                          <a href={r.apply_url} target="_blank" rel="noopener noreferrer"
                            className="inline-flex items-center gap-1 text-xs text-brand hover:text-brand-hover hover:underline transition-colors">
                            <Link size={12} /> 点击投递
                          </a>
                        ) : <span className="text-xs text-[var(--color-text-muted)]">-</span>}
                      </td>
                      <td className="px-4 py-3 whitespace-nowrap">
                        <select value={track?.status ?? "pending"} onChange={(e) => handleStatusChange(String(r.id), e.target.value)}
                          className={`px-2 py-1 rounded border text-xs cursor-pointer focus:outline-none focus:border-brand/40 transition-colors ${statusOpt.color} ${statusOpt.bg}`}>
                          {TRACK_STATUS_OPTIONS.map((opt) => (<option key={opt.value} value={opt.value}>{opt.label}</option>))}
                        </select>
                      </td>
                      <td className="px-4 py-3 max-w-[140px]">
                        {editingNotes[String(r.id)] !== undefined ? (
                          <input type="text" value={editingNotes[String(r.id)]}
                            onChange={(e) => setEditingNotes((prev) => ({ ...prev, [String(r.id)]: e.target.value }))}
                            onBlur={() => handleNotesBlur(String(r.id))}
                            onKeyDown={(e) => { if (e.key === "Enter") handleNotesBlur(String(r.id)); }}
                            autoFocus
                            className="w-full px-2 py-1 rounded border border-brand/50 bg-[#F2F2F7] text-xs text-[var(--color-text)] outline-none focus:bg-white focus:ring-4 focus:ring-brand/15"
                            placeholder="点击添加备注" />
                        ) : (
                          <button onClick={() => setEditingNotes((prev) => ({ ...prev, [String(r.id)]: track?.notes ?? "" }))}
                            className="flex items-center gap-1 text-xs text-[var(--color-text-muted)] hover:text-brand transition-colors cursor-pointer max-w-full"
                            title={track?.notes || "点击添加备注"}>
                            <Note size={11} weight="duotone" className="shrink-0" />
                            <span className="truncate">{track?.notes || <span className="italic">点击添加</span>}</span>
                          </button>
                        )}
                      </td>
                      <td className="px-4 py-3 text-xs text-[var(--color-text-secondary)] max-w-[160px]">
                        <span className="inline-flex items-center gap-1">
                          <MapPin size={11} weight="duotone" className="text-red-500 shrink-0" />
                          <span title={r.city}>{truncate(r.city ?? "-", 18)}</span>
                        </span>
                      </td>
                      <td className="px-4 py-3 text-xs text-[var(--color-text-secondary)] max-w-[200px]">
                        <span className="inline-flex items-start gap-1">
                          <User size={11} weight="duotone" className="text-emerald-500 shrink-0 mt-0.5" />
                          <span title={r.position}>{truncate(r.position ?? "-", 25)}</span>
                        </span>
                      </td>
                    </tr>
                  );
                })}
                {!loading && (isProgress ? progressRecords : records).length === 0 && (
                  <tr><td colSpan={isProgress ? 8 : 9} className="px-4 py-16 text-center text-xs text-[var(--color-text-muted)]">
                    {isProgress ? "暂无投递记录，设置求职进度后自动显示" : "未找到匹配的校招信息"}
                  </td></tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        {/* ── 分页 ── */}
        {totalPages > 1 && (
          <div className="flex items-center justify-between mt-4">
            <span className="text-xs text-[var(--color-text-muted)]">第 {page}/{totalPages} 页，共 {total.toLocaleString()} 条</span>
            <div className="flex items-center gap-2">
              <button onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page <= 1}
                className="p-2 rounded-full bg-[var(--color-bg-secondary)] text-[var(--color-text-secondary)] hover:bg-[#E5E5EA] disabled:opacity-30 disabled:cursor-not-allowed transition-all cursor-pointer">
                <CaretLeft size={14} weight="bold" />
              </button>
              {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
                const start = Math.max(1, Math.min(page - 2, totalPages - 4));
                const p = start + i;
                if (p > totalPages) return null;
                return (
                  <button key={p} onClick={() => setPage(p)}
                    className={`w-8 h-8 rounded-full text-xs font-medium transition-all cursor-pointer
                      ${p === page ? "bg-brand/10 text-brand border border-brand/30" : "bg-[var(--color-bg-secondary)] text-[var(--color-text-secondary)] hover:bg-[#E5E5EA]"}`}>
                    {p}
                  </button>
                );
              })}
              <button onClick={() => setPage((p) => Math.min(totalPages, p + 1))} disabled={page >= totalPages}
                className="p-2 rounded-full bg-[var(--color-bg-secondary)] text-[var(--color-text-secondary)] hover:bg-[#E5E5EA] disabled:opacity-30 disabled:cursor-not-allowed transition-all cursor-pointer">
                <CaretRight size={14} weight="bold" />
              </button>
            </div>
          </div>
        )}
      </div>

      <AdvancedFilterPanel open={filterOpen} filters={advancedFilters}
        onApply={(f) => { setAdvancedFilters(f); setActiveFilters(f); setPage(1); }}
        onClose={() => setFilterOpen(false)} />
    </div>
  );
}
