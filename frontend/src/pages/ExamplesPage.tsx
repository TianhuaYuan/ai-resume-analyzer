/**
 * ExamplesPage — 简历范文列表页（真实数据）。
 *
 * - 列表：market/samples 卡片网格，展示 title + position(目标岗位) + category
 * - 点卡片 → 跳转详情页 /examples/:id（展示原文 + 快速套用 / AI 改写）
 * - 搜索（300ms 防抖）+ 分页
 */

import { useEffect, useState, useCallback, useRef } from "react";
import { useNavigate } from "react-router-dom";
import {
  CaretRight,
  MagnifyingGlass,
  CaretLeft,
  Target,
  Spinner,
} from "@phosphor-icons/react";
import LandingNav from "../components/LandingNav";
import { listSamples, type ResumeSample } from "../api/market";

// ── 内容 Tab 栏（对齐 ContentSection） ──

const CONTENT_TABS = [
  { key: "templates", label: "简历模板", route: "/templates" },
  { key: "examples", label: "简历范文", route: "/examples" },
  { key: "tips", label: "求职攻略", route: "/tips" },
];

function formatDate(dateStr?: string): string {
  if (!dateStr) return "";
  const normalized = /[Z+]/.test(dateStr) ? dateStr : dateStr + "Z";
  const d = new Date(normalized);
  if (isNaN(d.getTime())) return dateStr.slice(0, 10);
  return d.toLocaleDateString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit" });
}

// ── 主组件 ──

export default function ExamplesPage() {
  const navigate = useNavigate();

  const [samples, setSamples] = useState<ResumeSample[]>([]);
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const handleQueryChange = useCallback((val: string) => {
    setQuery(val);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => { setDebouncedQuery(val); setPage(1); }, 300);
  }, []);

  // 加载范文列表
  useEffect(() => {
    setLoading(true);
    const filters: { q?: string; page: number; limit: number } = { page, limit: 12 };
    if (debouncedQuery) filters.q = debouncedQuery;
    listSamples(filters)
      .then((data) => { setSamples(data.items); setTotal(data.total); setTotalPages(data.total_pages); })
      .catch(() => { setSamples([]); setTotal(0); setTotalPages(0); })
      .finally(() => setLoading(false));
  }, [debouncedQuery, page]);

  return (
    <div className="min-h-screen bg-[var(--color-bg)]">
      <LandingNav activeKey="examples" />

      <div className="max-w-7xl mx-auto px-6 py-8">
        {/* 内容 Tab 栏 */}
        <div className="flex items-center gap-1 mb-6 border-b border-[var(--color-border)]">
          {CONTENT_TABS.map((t) => (
            <button key={t.key} onClick={() => navigate(t.route)}
              className={`px-5 py-2.5 text-sm font-medium transition-all duration-300 cursor-pointer border-b-2 -mb-px
                ${t.key === "examples"
                  ? "text-brand border-brand"
                  : "text-[var(--color-text-muted)] border-transparent hover:text-[var(--color-text-secondary)]"
                }`}>
              {t.label}
            </button>
          ))}
        </div>

        {/* 搜索 + 统计 */}
        <div className="flex items-center gap-3 mb-6">
          <div className="relative flex-1 max-w-md">
            <MagnifyingGlass size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--color-text-muted)]" />
            <input type="text" value={query} onChange={(e) => handleQueryChange(e.target.value)}
              placeholder="搜索范文标题、目标岗位..."
              className="w-full pl-9 pr-3 py-2 rounded-xl bg-[#F2F2F7] border border-transparent
                text-sm text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] focus:outline-none focus:bg-white focus:border-brand/40 focus:ring-4 focus:ring-brand/15 transition-colors" />
          </div>
          <span className="text-xs text-[var(--color-text-muted)] tabular-nums shrink-0">
            {loading ? "加载中..." : `共 ${total.toLocaleString()} 篇范文`}
          </span>
        </div>

        {/* 范文卡片网格 */}
        {loading ? (
          <div className="flex items-center justify-center py-24">
            <Spinner size={20} className="animate-spin text-[var(--color-text-muted)]" />
          </div>
        ) : samples.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-24">
            <Target size={32} className="text-[var(--color-text-muted)] mb-3" />
            <p className="text-sm text-[var(--color-text-secondary)]">数据同步中，请稍后再试</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
            {samples.map((s) => (
              <button key={s.id} onClick={() => navigate(`/examples/${s.id}`)}
                className="glass-card p-5 text-left hover:-translate-y-1 hover:shadow-xl hover:shadow-black/5 transition-all duration-300 cursor-pointer animate-fade-in-up group">
                <div className="flex items-start justify-between gap-2 mb-3">
                  <h3 className="text-sm font-semibold text-[var(--color-text)] leading-snug line-clamp-2 flex-1 min-w-0">
                    {s.title}
                  </h3>
                  <CaretRight size={14} className="shrink-0 text-[var(--color-text-muted)] group-hover:text-brand group-hover:translate-x-0.5 transition-all mt-0.5" />
                </div>
                <div className="flex items-center gap-1.5 flex-wrap">
                  {s.position && (
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium bg-brand/10 text-brand border border-brand/20">
                      <Target size={10} weight="duotone" /> {s.position}
                    </span>
                  )}
                  {s.category && (
                    <span className="inline-flex px-2 py-0.5 rounded text-[10px] font-medium bg-[var(--color-bg-secondary)] text-[var(--color-text-secondary)] border border-[var(--color-border)]">
                      {s.category}
                    </span>
                  )}
                </div>
                {s.created_at && (
                  <p className="text-[10px] text-[var(--color-text-muted)] mt-3">{formatDate(s.created_at)}</p>
                )}
              </button>
            ))}
          </div>
        )}

        {/* 分页 */}
        {!loading && totalPages > 1 && (
          <div className="flex items-center justify-between mt-6">
            <span className="text-xs text-[var(--color-text-muted)]">第 {page}/{totalPages} 页，共 {total.toLocaleString()} 篇</span>
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
    </div>
  );
}
