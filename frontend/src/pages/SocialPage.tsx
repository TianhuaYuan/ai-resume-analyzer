/**
 * SocialPage — 社招岗位浏览页（公开，未登录可浏览）。
 *
 * 数据来自市场数据接口：/api/v1/market/jobs?job_type=social
 * - 搜索框（300ms 防抖）+ 筛选（公司/城市/行业）
 * - 岗位卡片网格 + 分页 + 统计条数
 * - 点击卡片弹详情（拉全文 + payload.apply_url 投递链接）
 * - 空态显示"数据同步中，请稍后再试"（不报错）
 */

import { useEffect, useState, useCallback, useRef } from "react";
import {
  Buildings,
  MagnifyingGlass,
  MapPin,
  CurrencyCny,
  GraduationCap,
  Funnel,
  X,
  CaretLeft,
  CaretRight,
  ArrowSquareOut,
  Spinner,
  Tag,
} from "@phosphor-icons/react";
import {
  listJobs,
  getJob,
  JOB_TYPE_LABELS,
  type MarketJob,
  type MarketJobDetail,
  type MarketJobFilters,
} from "../api/market";

// ── 行业标签颜色（对齐 CampusPage） ──

const INDUSTRY_COLORS: Record<string, string> = {
  科技: "bg-sky-500/10 text-sky-600 border-sky-500/20",
  游戏: "bg-purple-500/10 text-purple-600 border-purple-500/20",
  金融: "bg-amber-500/10 text-amber-600 border-amber-500/20",
  银行: "bg-amber-500/10 text-amber-600 border-amber-500/20",
  国企: "bg-emerald-500/10 text-emerald-600 border-emerald-500/20",
  软件: "bg-brand/10 text-brand border-brand/20",
  专业服务: "bg-rose-500/10 text-rose-600 border-rose-500/20",
  互联网: "bg-violet-500/10 text-violet-600 border-violet-500/20",
  教育: "bg-teal-500/10 text-teal-600 border-teal-500/20",
  医疗: "bg-red-500/10 text-red-600 border-red-500/20",
  汽车: "bg-orange-500/10 text-orange-600 border-orange-500/20",
  人工智能: "bg-sky-500/10 text-sky-600 border-sky-500/20",
};

function getIndustryColor(industry: string): string {
  if (INDUSTRY_COLORS[industry]) return INDUSTRY_COLORS[industry];
  const palette = [
    "bg-sky-500/10 text-sky-600 border-sky-500/20",
    "bg-purple-500/10 text-purple-600 border-purple-500/20",
    "bg-amber-500/10 text-amber-600 border-amber-500/20",
    "bg-emerald-500/10 text-emerald-600 border-emerald-500/20",
    "bg-brand/10 text-brand border-brand/20",
    "bg-rose-500/10 text-rose-600 border-rose-500/20",
  ];
  let hash = 0;
  for (let i = 0; i < industry.length; i++) {
    hash = ((hash << 5) - hash + industry.charCodeAt(i)) | 0;
  }
  return palette[Math.abs(hash) % palette.length];
}

function formatDate(dateStr?: string): string {
  if (!dateStr) return "-";
  const normalized = /[Z+]/.test(dateStr) ? dateStr : dateStr + "Z";
  const d = new Date(normalized);
  if (isNaN(d.getTime())) return dateStr.slice(0, 10);
  return d.toLocaleDateString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit" });
}

// ── 截止徽标 ──

function DeadlineBadge({ deadline, isExpired }: { deadline?: string | null; isExpired?: boolean }) {
  if (!deadline) return null;
  if (isExpired) {
    return (
      <span className="shrink-0 px-2 py-0.5 rounded text-[10px] font-medium border border-zinc-500/20 bg-zinc-500/10 text-zinc-500">
        已截止
      </span>
    );
  }
  return (
    <span className="shrink-0 inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium border border-amber-500/20 bg-amber-500/10 text-amber-600">
      截止 {formatDate(deadline)}
    </span>
  );
}

// ── 筛选面板 ──

interface SocialFilterProps {
  open: boolean;
  filters: { company: string; city: string; industry: string };
  onApply: (filters: { company: string; city: string; industry: string }) => void;
  onClose: () => void;
}

function SocialFilterPanel({ open, filters, onApply, onClose }: SocialFilterProps) {
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
            <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">城市</label>
            <input type="text" value={local.city} onChange={(e) => setLocal((p) => ({ ...p, city: e.target.value }))}
              placeholder="请输入城市，如：北京" className="w-full px-3 py-1.5 rounded-xl bg-[#F2F2F7] border border-transparent text-xs text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] focus:outline-none focus:bg-white focus:border-brand/40 focus:ring-4 focus:ring-brand/15" />
          </div>
          <div>
            <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">行业</label>
            <input type="text" value={local.industry} onChange={(e) => setLocal((p) => ({ ...p, industry: e.target.value }))}
              placeholder="请输入行业，如：互联网" className="w-full px-3 py-1.5 rounded-xl bg-[#F2F2F7] border border-transparent text-xs text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] focus:outline-none focus:bg-white focus:border-brand/40 focus:ring-4 focus:ring-brand/15" />
          </div>
        </div>
        <div className="flex items-center justify-end gap-2 px-5 py-3 border-t border-[var(--color-border)]">
          <button onClick={() => { setLocal({ company: "", city: "", industry: "" }); }}
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
              {job.industry && (
                <span className={`inline-flex px-2 py-0.5 rounded text-[10px] font-medium border ${getIndustryColor(job.industry)}`}>
                  {job.industry}
                </span>
              )}
              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium bg-[var(--color-bg-secondary)] text-[var(--color-text-muted)] border border-[var(--color-border)]">
                来源：{job.source || "公开渠道"}
              </span>
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
              {job.payload?.apply_url ? (
                <a href={job.payload.apply_url} target="_blank" rel="noopener noreferrer"
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
  const [jobs, setJobs] = useState<MarketJob[]>([]);
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [filterOpen, setFilterOpen] = useState(false);
  const [activeFilters, setActiveFilters] = useState({ company: "", city: "", industry: "" });
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // 详情弹窗
  const [detail, setDetail] = useState<MarketJobDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailId, setDetailId] = useState<string | null>(null);

  const handleQueryChange = useCallback((val: string) => {
    setQuery(val);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => { setDebouncedQuery(val); setPage(1); }, 300);
  }, []);

  // 加载岗位列表（job_type 固定 social）
  useEffect(() => {
    setLoading(true);
    const filters: MarketJobFilters = { job_type: "social", page, limit: 20 };
    if (debouncedQuery) filters.q = debouncedQuery;
    if (activeFilters.company) filters.company = activeFilters.company;
    if (activeFilters.city) filters.city = activeFilters.city;
    if (activeFilters.industry) filters.industry = activeFilters.industry;
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

  const openDetail = (id: string) => setDetailId(id);
  const closeDetail = () => { setDetailId(null); setDetail(null); };

  const hasActiveFilters = activeFilters.company || activeFilters.city || activeFilters.industry;

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-[1200px] mx-auto px-6 py-6">
        {/* ── 页头 ── */}
        <div className="mb-6">
          <div className="flex items-center gap-2 mb-1.5">
            <Buildings size={18} weight="duotone" className="text-brand" />
            <h1 className="text-xl font-bold text-[var(--color-text)] display-tight">社招岗位</h1>
            <span className="px-2 py-0.5 rounded text-[10px] font-medium bg-brand/10 text-brand border border-brand/20">
              {JOB_TYPE_LABELS.social}
            </span>
          </div>
          <p className="text-xs text-[var(--color-text-muted)]">
            汇集公开渠道的社招岗位信息，支持关键词与公司 / 城市 / 行业筛选
          </p>
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
            筛选
          </button>
          <span className="text-xs text-[var(--color-text-muted)] tabular-nums shrink-0">
            {loading ? "加载中..." : `${total.toLocaleString()} 条岗位`}
          </span>
        </div>

        {/* ── 岗位卡片网格 ── */}
        {loading ? (
          <div className="flex items-center justify-center py-24">
            <Spinner size={20} className="animate-spin text-[var(--color-text-muted)]" />
          </div>
        ) : jobs.length === 0 ? (
          <div className="glass-card flex flex-col items-center justify-center py-24">
            <Buildings size={32} className="text-[var(--color-text-muted)] mb-3" />
            <p className="text-sm text-[var(--color-text-secondary)]">数据同步中，请稍后再试</p>
            <p className="text-xs text-[var(--color-text-muted)] mt-1">暂未检索到符合条件的社招岗位</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {jobs.map((job) => (
              <button key={job.id} onClick={() => openDetail(job.id)}
                className="glass-card p-5 text-left hover:-translate-y-1 hover:shadow-xl hover:shadow-black/5 transition-all duration-300 cursor-pointer animate-fade-in-up group">
                <div className="flex items-start justify-between gap-2 mb-2">
                  <div className="min-w-0">
                    <p className="text-xs font-semibold text-[var(--color-text)] truncate">{job.company}</p>
                    <p className="text-xs text-[var(--color-text-secondary)] mt-0.5 truncate">{job.title}</p>
                  </div>
                  <DeadlineBadge deadline={job.deadline} isExpired={job.is_expired} />
                </div>

                <div className="flex flex-wrap gap-1.5 mb-3">
                  {job.salary && (
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium bg-emerald-500/10 text-emerald-600 border border-emerald-500/20">
                      <CurrencyCny size={10} weight="duotone" /> {job.salary}
                    </span>
                  )}
                  {job.city && (
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium bg-red-500/10 text-red-600 border border-red-500/20">
                      <MapPin size={10} weight="duotone" /> {job.city}
                    </span>
                  )}
                  {job.degree && (
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium bg-sky-500/10 text-sky-600 border border-sky-500/20">
                      <GraduationCap size={10} weight="duotone" /> {job.degree}
                    </span>
                  )}
                  {job.industry && (
                    <span className={`inline-flex px-2 py-0.5 rounded text-[10px] font-medium border ${getIndustryColor(job.industry)}`}>
                      {job.industry}
                    </span>
                  )}
                </div>

                <div className="flex items-center justify-between border-t border-[var(--color-border)] pt-2.5">
                  <span className="inline-flex items-center gap-1 text-[10px] text-[var(--color-text-muted)]">
                    <Tag size={10} weight="duotone" className="shrink-0" />
                    {job.source || "公开渠道"}
                  </span>
                  <span className="inline-flex items-center gap-1 text-xs text-brand group-hover:underline">
                    查看详情 <ArrowSquareOut size={11} weight="bold" />
                  </span>
                </div>
              </button>
            ))}
          </div>
        )}

        {/* ── 分页 ── */}
        {!loading && totalPages > 1 && (
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
      <SocialFilterPanel open={filterOpen} filters={activeFilters}
        onApply={(f) => { setActiveFilters(f); setPage(1); }}
        onClose={() => setFilterOpen(false)} />
      <JobDetailModal job={detail} loading={detailLoading} onClose={closeDetail} />
    </div>
  );
}
