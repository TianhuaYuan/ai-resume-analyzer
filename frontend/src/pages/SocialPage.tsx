/**
 * SocialPage — 社招岗位浏览页（公开，未登录可浏览）。
 *
 * 布局与校招页保持一致：统计卡 + 搜索/高级筛选 + 表格 + 分页。
 * 数据源：/api/v1/market/jobs（job_type=social）+ /api/v1/market/jobs/stats
 * 点击标题可查看岗位详情弹窗（全文 + 投递链接）。
 */

import { useEffect, useState, useCallback, useRef } from "react";
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
  Funnel,
  X,
  ArrowSquareOut,
  Spinner,
  Buildings,
  CurrencyCny,
  GraduationCap,
} from "@phosphor-icons/react";
import {
  listJobs,
  getJob,
  listJobStats,
  type MarketJob,
  type MarketJobDetail,
  type MarketJobFilters,
  type MarketJobStats,
} from "../api/market";

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

// ── 高级筛选面板 ──

interface AdvancedFilters {
  company: string;
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
            <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">公司</label>
            <input type="text" value={local.company} onChange={(e) => setLocal((p) => ({ ...p, company: e.target.value }))}
              placeholder="请输入公司名称" className="w-full px-3 py-1.5 rounded-xl bg-[#F2F2F7] border border-transparent text-xs text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] focus:outline-none focus:bg-white focus:border-brand/40 focus:ring-4 focus:ring-brand/15" />
          </div>
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
          <button onClick={() => { setLocal({ company: "", city: "", position: "", dateFrom: "", dateTo: "" }); }}
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

// ── 岗位详情弹窗 ──

interface JobDetailModalProps {
  job: MarketJobDetail | null;
  loading: boolean;
  onClose: () => void;
}

function JobDetailModal({ job, loading, onClose }: JobDetailModalProps) {
  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [onClose]);

  // 没有岗位数据时不渲染（否则弹窗常驻无法关闭）
  if (!job) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />
      <div className="relative w-full max-w-2xl glass-card shadow-2xl max-h-[85vh] flex flex-col animate-fade-in-up">
        {/* 头部 */}
        <div className="flex items-start justify-between gap-3 px-5 py-4 border-b border-[var(--color-border)]">
          <div className="min-w-0">
            <h3 className="text-sm font-semibold text-[var(--color-text)] leading-snug">
              {job?.company ?? "岗位详情"}
            </h3>
            <p className="text-xs text-[var(--color-text-secondary)] mt-1 truncate">{job?.title}</p>
          </div>
          <button onClick={onClose} className="p-1 rounded-lg text-[var(--color-text-muted)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-secondary)] transition-colors cursor-pointer shrink-0">
            <X size={16} weight="bold" />
          </button>
        </div>

        {loading || !job ? (
          <div className="flex-1 flex items-center justify-center py-16">
            <Spinner size={20} className="animate-spin text-[var(--color-text-muted)]" />
          </div>
        ) : (
          <>
            {/* 信息区 */}
            <div className="px-5 py-4 border-b border-[var(--color-border)] flex flex-wrap gap-1.5">
              {job.salary && (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-medium bg-emerald-500/10 text-emerald-600 border border-emerald-500/20">
                  <CurrencyCny size={11} weight="duotone" /> {job.salary}
                </span>
              )}
              {job.position && (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-medium bg-brand/10 text-brand border border-brand/20">
                  <Buildings size={11} weight="duotone" /> {job.position}
                </span>
              )}
              {job.city && (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-medium bg-red-500/10 text-red-600 border border-red-500/20">
                  <MapPin size={11} weight="duotone" /> {job.city}
                </span>
              )}
              {job.degree && (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-medium bg-sky-500/10 text-sky-600 border border-sky-500/20">
                  <GraduationCap size={11} weight="duotone" /> {job.degree}
                </span>
              )}
              {job.published_at && (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium bg-[var(--color-bg-secondary)] text-[var(--color-text-muted)] border border-[var(--color-border)]">
                  <CalendarBlank size={10} weight="duotone" /> 发布于 {formatDate(job.published_at)}
                </span>
              )}
            </div>

            {/* 正文 */}
            <div className="flex-1 overflow-y-auto px-5 py-4 min-h-0">
              <p className="text-xs text-[var(--color-text-secondary)] leading-relaxed whitespace-pre-wrap break-words">
                {job.content || "暂无详细描述"}
              </p>
            </div>

            {/* 投递 */}
            <div className="px-5 py-3 border-t border-[var(--color-border)] flex items-center justify-between gap-3">
              <p className="text-[10px] text-[var(--color-text-muted)]">
                来源公开渠道，投递前请自行核实岗位信息
              </p>
              {job.apply_url ? (
                <a href={job.apply_url} target="_blank" rel="noopener noreferrer"
                  className="inline-flex items-center gap-1.5 px-4 py-1.5 rounded-full bg-brand text-white text-xs font-medium hover:bg-[#0077ed] hover:scale-[1.02] active:scale-[0.98] transition-all duration-300 cursor-pointer shrink-0">
                  <ArrowSquareOut size={13} weight="bold" /> 前往投递
                </a>
              ) : (
                <span className="shrink-0 text-xs text-[var(--color-text-muted)]">
                  暂无可投递链接
                </span>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

// ── 主组件 ──

export default function SocialPage() {
  const [stats, setStats] = useState<MarketJobStats | null>(null);
  const [jobs, setJobs] = useState<MarketJob[]>([]);
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(0);
  const [page, setPage] = useState(1);
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [filterOpen, setFilterOpen] = useState(false);
  const [advancedFilters, setAdvancedFilters] = useState<AdvancedFilters>({ company: "", city: "", position: "", dateFrom: "", dateTo: "" });
  const [activeFilters, setActiveFilters] = useState<AdvancedFilters>({ company: "", city: "", position: "", dateFrom: "", dateTo: "" });
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // 详情弹窗
  const [detail, setDetail] = useState<MarketJobDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailId, setDetailId] = useState<number | null>(null);

  const handleQueryChange = useCallback((val: string) => {
    setQuery(val);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => { setDebouncedQuery(val); setPage(1); }, 300);
  }, []);

  // 加载统计（近 3/7 日 + 累计）
  useEffect(() => {
    listJobStats({ job_type: "social" })
      .then(setStats)
      .catch(() => setStats(null));
  }, []);

  // 加载岗位列表（job_type 固定 social）
  useEffect(() => {
    setLoading(true);
    const filters: MarketJobFilters = { job_type: "social", page, limit: 20 };
    if (debouncedQuery) filters.q = debouncedQuery;
    if (activeFilters.company) filters.company = activeFilters.company;
    if (activeFilters.city) filters.city = activeFilters.city;
    if (activeFilters.position) filters.position = activeFilters.position;
    if (activeFilters.dateFrom) filters.date_from = activeFilters.dateFrom;
    if (activeFilters.dateTo) filters.date_to = activeFilters.dateTo;
    listJobs(filters)
      .then((data) => { setJobs(data.items); setTotal(data.total); setTotalPages(data.total_pages); })
      .catch(() => { setJobs([]); setTotal(0); setTotalPages(0); })
      .finally(() => setLoading(false));
  }, [debouncedQuery, page, activeFilters]);

  // 加载岗位详情
  useEffect(() => {
    if (!detailId) return;
    setDetailLoading(true);
    setDetail(null);
    getJob(detailId)
      .then(setDetail)
      .catch(() => setDetail(null))
      .finally(() => setDetailLoading(false));
  }, [detailId]);

  const openDetail = (id: number) => setDetailId(id);
  const closeDetail = () => { setDetailId(null); setDetail(null); };

  const hasActiveFilters = activeFilters.company || activeFilters.city || activeFilters.position || activeFilters.dateFrom || activeFilters.dateTo;

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

        {/* ── 工具栏 ── */}
        <div className="flex items-center gap-2 mb-4">
          <div className="relative flex-1 max-w-md">
            <MagnifyingGlass size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--color-text-muted)]" />
            <input type="text" value={query} onChange={(e) => handleQueryChange(e.target.value)}
              placeholder="搜索公司、标题、岗位、城市..."
              className="w-full pl-9 pr-3 py-2 rounded-xl bg-[#F2F2F7] border border-transparent
                text-sm text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] focus:outline-none focus:bg-white focus:border-brand/40 focus:ring-4 focus:ring-brand/15 transition-colors" />
          </div>
          <button onClick={() => setFilterOpen(true)}
            className={`flex items-center gap-1.5 px-3 py-2 rounded-full text-xs font-medium transition-all cursor-pointer
              ${hasActiveFilters
                ? "bg-brand/10 text-brand border border-brand/30"
                : "bg-[var(--color-bg-secondary)] text-[var(--color-text-secondary)] hover:bg-[#E5E5EA]"
              }`}>
            <Funnel size={13} />
            高级筛选
          </button>
          <span className="text-xs text-[var(--color-text-muted)] tabular-nums shrink-0">
            {loading ? "加载中..." : `${total.toLocaleString()} 条结果`}
          </span>
        </div>

        {/* ── 表格 ── */}
        <div className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-card)] overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[var(--color-border)] bg-[var(--color-bg-secondary)]">
                  <th className="text-left px-4 py-3 text-xs font-medium text-[var(--color-text-secondary)] whitespace-nowrap">发布时间</th>
                  <th className="text-left px-4 py-3 text-xs font-medium text-[var(--color-text-secondary)]">公司</th>
                  <th className="text-left px-4 py-3 text-xs font-medium text-[var(--color-text-secondary)]">标题</th>
                  <th className="text-left px-4 py-3 text-xs font-medium text-[var(--color-text-secondary)] whitespace-nowrap">投递方式</th>
                  <th className="text-left px-4 py-3 text-xs font-medium text-[var(--color-text-secondary)] whitespace-nowrap">薪资</th>
                  <th className="text-left px-4 py-3 text-xs font-medium text-[var(--color-text-secondary)]">学历</th>
                  <th className="text-left px-4 py-3 text-xs font-medium text-[var(--color-text-secondary)]">工作地点</th>
                  <th className="text-left px-4 py-3 text-xs font-medium text-[var(--color-text-secondary)]">岗位</th>
                </tr>
              </thead>
              <tbody>
                {jobs.map((r) => (
                  <tr key={r.id} className="border-b border-[var(--color-border)] last:border-b-0 hover:bg-[var(--color-bg-secondary)] transition-colors">
                    <td className="px-4 py-3 text-xs text-[var(--color-text-muted)] whitespace-nowrap tabular-nums">
                      {formatDate(r.published_at ?? r.created_at)}
                    </td>
                    <td className="px-4 py-3 text-xs font-semibold text-[var(--color-text)] whitespace-nowrap">{r.company}</td>
                    <td className="px-4 py-3 max-w-[220px]">
                      <button onClick={() => openDetail(r.id)}
                        title={r.title}
                        className="block max-w-full truncate text-left text-xs text-[var(--color-text-secondary)] hover:text-brand hover:underline transition-colors cursor-pointer">
                        {truncate(r.title || "-", 30)}
                      </button>
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap">
                      {r.apply_url ? (
                        <a href={r.apply_url} target="_blank" rel="noopener noreferrer"
                          className="inline-flex items-center gap-1 text-xs text-brand hover:text-brand-hover hover:underline transition-colors">
                          <Link size={12} /> 点击投递
                        </a>
                      ) : <span className="text-xs text-[var(--color-text-muted)]">-</span>}
                    </td>
                    <td className="px-4 py-3 text-xs text-[var(--color-text-secondary)] whitespace-nowrap">{r.salary || "-"}</td>
                    <td className="px-4 py-3 text-xs text-[var(--color-text-secondary)] max-w-[120px]">{r.degree || "-"}</td>
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
                ))}
                {!loading && jobs.length === 0 && (
                  <tr><td colSpan={8} className="px-4 py-16 text-center text-xs text-[var(--color-text-muted)]">
                    未找到匹配的社招岗位
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

      {/* ── 弹窗 ── */}
      <AdvancedFilterPanel open={filterOpen} filters={advancedFilters}
        onApply={(f) => { setAdvancedFilters(f); setActiveFilters(f); setPage(1); }}
        onClose={() => setFilterOpen(false)} />
      <JobDetailModal job={detail} loading={detailLoading} onClose={closeDetail} />
    </div>
  );
}
