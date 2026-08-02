/**
 * TipsPage — 求职攻略页（真实数据）。
 *
 * 数据来自市场数据接口：/api/v1/market/guides
 * - 搜索框（300ms 防抖，q 参数）+ 分页 + 条数统计
 * - 攻略卡片网格：标题 + 摘要 + 日期 + 收录状态徽标
 * - 点卡片：跳转站内详情 /guides/:id（has_fulltext=true 站内读全文，
 *   否则详情页展示摘要 + "阅读原文"外链按钮）
 * - 空态显示"攻略同步中，请稍后再试"（不报错）
 */

import { useEffect, useState, useCallback, useRef } from "react";
import { useNavigate } from "react-router-dom";
import {
  BookOpen,
  MagnifyingGlass,
  CalendarBlank,
  CaretLeft,
  CaretRight,
  Spinner,
} from "@phosphor-icons/react";
import LandingNav from "../components/LandingNav";
import {
  listGuides,
  type MarketGuideItem,
  type GuideFilters,
} from "../api/market";

// ── 内容 Tab 栏（对齐 ContentSection / ExamplesPage） ──

const CONTENT_TABS = [
  { key: "templates", label: "简历模板", route: "/templates" },
  { key: "examples", label: "简历范文", route: "/examples" },
  { key: "tips", label: "求职攻略", route: "/tips" },
];

function formatDate(dateStr?: string | null): string {
  if (!dateStr) return "-";
  const normalized = /[Z+]/.test(dateStr) ? dateStr : dateStr + "Z";
  const d = new Date(normalized);
  if (isNaN(d.getTime())) return dateStr.slice(0, 10);
  return d.toLocaleDateString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit" });
}

// ── 收录状态徽标 ──

function FulltextBadge({ hasFulltext }: { hasFulltext: boolean }) {
  if (hasFulltext) {
    return (
      <span className="shrink-0 px-2 py-0.5 rounded text-[10px] font-medium border border-emerald-500/20 bg-emerald-500/10 text-emerald-600">
        站内全文
      </span>
    );
  }
  return (
    <span className="shrink-0 px-2 py-0.5 rounded text-[10px] font-medium border border-zinc-500/20 bg-zinc-500/10 text-zinc-500">
      原文待收录
    </span>
  );
}

// ── 主组件 ──

export default function TipsPage() {
  const navigate = useNavigate();

  const [guides, setGuides] = useState<MarketGuideItem[]>([]);
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

  // 加载攻略列表
  useEffect(() => {
    setLoading(true);
    const filters: GuideFilters = { page, limit: 12 };
    if (debouncedQuery) filters.q = debouncedQuery;
    listGuides(filters)
      .then((data) => { setGuides(data.items); setTotal(data.total); setTotalPages(data.total_pages); })
      .catch(() => { setGuides([]); setTotal(0); setTotalPages(0); })
      .finally(() => setLoading(false));
  }, [debouncedQuery, page]);

  const openGuide = (g: MarketGuideItem) => navigate(`/guides/${g.id}`);

  return (
    <div className="min-h-screen bg-[var(--color-bg)]">
      <LandingNav activeKey="tips" />

      <div className="max-w-7xl mx-auto px-6 py-8">
        {/* 内容 Tab 栏 */}
        <div className="flex items-center gap-1 mb-6 border-b border-[var(--color-border)]">
          {CONTENT_TABS.map((t) => (
            <button key={t.key} onClick={() => navigate(t.route)}
              className={`px-5 py-2.5 text-sm font-medium transition-all duration-300 cursor-pointer border-b-2 -mb-px
                ${t.key === "tips"
                  ? "text-brand border-brand"
                  : "text-[var(--color-text-muted)] border-transparent hover:text-[var(--color-text-secondary)]"
                }`}>
              {t.label}
            </button>
          ))}
        </div>

        {/* 页头 */}
        <div className="flex items-center gap-2 mb-1.5">
          <BookOpen size={18} weight="duotone" className="text-brand" />
          <h1 className="text-xl font-bold text-[var(--color-text)] display-tight">求职攻略</h1>
        </div>
        <p className="text-xs text-[var(--color-text-muted)] mb-6">
          汇集公开渠道的求职攻略，覆盖简历、笔试、面试与谈薪全流程
        </p>

        {/* 搜索 + 统计 */}
        <div className="flex items-center gap-3 mb-6">
          <div className="relative flex-1 max-w-md">
            <MagnifyingGlass size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--color-text-muted)]" />
            <input type="text" value={query} onChange={(e) => handleQueryChange(e.target.value)}
              placeholder="搜索攻略标题、关键词..."
              className="w-full pl-9 pr-3 py-2 rounded-xl bg-[#F2F2F7] border border-transparent
                text-sm text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] focus:outline-none focus:bg-white focus:border-brand/40 focus:ring-4 focus:ring-brand/15 transition-colors" />
          </div>
          <span className="text-xs text-[var(--color-text-muted)] tabular-nums shrink-0">
            {loading ? "加载中..." : `共 ${total.toLocaleString()} 篇攻略`}
          </span>
        </div>

        {/* 攻略卡片网格 */}
        {loading ? (
          <div className="flex items-center justify-center py-24">
            <Spinner size={20} className="animate-spin text-[var(--color-text-muted)]" />
          </div>
        ) : guides.length === 0 ? (
          <div className="glass-card flex flex-col items-center justify-center py-24">
            <BookOpen size={32} className="text-[var(--color-text-muted)] mb-3" />
            <p className="text-sm text-[var(--color-text-secondary)]">攻略同步中，请稍后再试</p>
            <p className="text-xs text-[var(--color-text-muted)] mt-1">暂未检索到符合条件的求职攻略</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
            {guides.map((g) => (
              <button key={g.id} onClick={() => openGuide(g)}
                className="glass-card p-5 text-left hover:-translate-y-1 hover:shadow-xl hover:shadow-black/5 transition-all duration-300 cursor-pointer animate-fade-in-up group flex flex-col">
                <div className="flex items-start justify-between gap-2 mb-2">
                  <h3 className="text-sm font-semibold text-[var(--color-text)] leading-snug line-clamp-2 flex-1 min-w-0">
                    {g.title}
                  </h3>
                  <FulltextBadge hasFulltext={g.has_fulltext} />
                </div>
                <p className="text-xs text-[var(--color-text-secondary)] leading-relaxed line-clamp-3 flex-1 mb-3">
                  {g.summary || "暂无摘要"}
                </p>
                <div className="flex items-center justify-between border-t border-[var(--color-border)] pt-2.5">
                  <span className="inline-flex items-center gap-1 text-[10px] text-[var(--color-text-muted)]">
                    <CalendarBlank size={10} weight="duotone" /> {formatDate(g.date)}
                  </span>
                  <span className="inline-flex items-center gap-1 text-xs text-brand group-hover:underline">
                    查看详情 <CaretRight size={11} weight="bold" />
                  </span>
                </div>
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
