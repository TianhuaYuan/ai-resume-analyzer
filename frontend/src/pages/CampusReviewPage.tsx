/**
 * CampusReviewPage — 求职复盘看板（E3）。
 *
 * 数据源：GET /campus/review/summary（后端 campus_review.py 纯函数聚合）
 *         + PUT /campus/tracks（幽灵候选「标记取消」）
 *
 * 借鉴 fieldwork InsightsView：KPI 网格 / 横向条形图（内联 div，无图表库）/
 * 阶段转化 pills / 拒因聚类 / 幽灵候选列表。样式沿用 InterviewPage glass-card。
 */
import { useCallback, useEffect, useState } from "react";
import {
  Spinner,
  ArrowClockwise,
  ChartBar,
  Funnel,
  ArrowRight,
  Prohibit,
  Ghost,
  CalendarBlank,
} from "@phosphor-icons/react";
import {
  getReviewSummary,
  upsertCampusTrack,
  getTrackStatusOption,
  type CampusReviewSummary,
} from "../api/campus";
import { useToast } from "../components/Toast";
import ConfirmDialog from "../components/ConfirmDialog";

/** 0~1 小数 → "42%"；null/NaN → "—" */
function fmtRate(r: number | null | undefined): string {
  if (r == null || Number.isNaN(r)) return "—";
  return `${Math.round(r * 100)}%`;
}

/** 横向条形图（fieldwork HBarChart 同思路，内联 div 无图表库） */
function HBar({
  rows,
  color = "var(--color-brand)",
}: {
  rows: { label: string; value: number }[];
  color?: string;
}) {
  const max = Math.max(1, ...rows.map((r) => r.value));
  return (
    <div className="space-y-2">
      {rows.map((r) => (
        <div key={r.label} className="flex items-center gap-3">
          <span
            className="w-32 shrink-0 truncate text-xs text-[var(--color-text-muted)]"
            title={r.label}
          >
            {r.label}
          </span>
          <div className="h-4 flex-1 rounded bg-[var(--color-bg-secondary)] overflow-hidden">
            <div
              className="h-full rounded transition-all"
              style={{ width: `${(r.value / max) * 100}%`, backgroundColor: color }}
            />
          </div>
          <span className="w-8 shrink-0 text-right text-xs tabular-nums text-[var(--color-text-muted)]">
            {r.value}
          </span>
        </div>
      ))}
    </div>
  );
}

/** KPI 卡（fieldwork Stat + grid 卡） */
function KpiCard({ value, label, hint }: { value: string | number; label: string; hint?: string }) {
  return (
    <div className="glass-card p-4">
      <p className="text-2xl font-semibold text-[var(--color-text)] tabular-nums">{value}</p>
      <p className="mt-1 text-xs text-[var(--color-text-muted)]">{label}</p>
      {hint && <p className="text-[10px] text-[var(--color-text-muted)]/70 mt-0.5">{hint}</p>}
    </div>
  );
}

/** 区块容器（fieldwork Section） */
function Section({
  icon,
  title,
  subtitle,
  children,
}: {
  icon: React.ReactNode;
  title: string;
  subtitle?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="glass-card p-5">
      <div className="flex items-center gap-2 mb-4">
        {icon}
        <div>
          <h2 className="text-sm font-semibold text-[var(--color-text)]">{title}</h2>
          {subtitle && <p className="text-xs text-[var(--color-text-muted)] mt-0.5">{subtitle}</p>}
        </div>
      </div>
      {children}
    </section>
  );
}

export default function CampusReviewPage() {
  const toast = useToast();
  const [summary, setSummary] = useState<CampusReviewSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [cancelling, setCancelling] = useState<string | null>(null);

  const fetchSummary = useCallback(async () => {
    setLoading(true);
    try {
      const data = await getReviewSummary();
      setSummary(data);
    } catch {
      setSummary(null);
      toast?.error?.("复盘数据加载失败");
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    void fetchSummary();
  }, [fetchSummary]);

  /** 幽灵候选 → 标记取消（PUT /campus/tracks status=cancelled） */
  const handleCancelGhost = async () => {
    if (!cancelling) return;
    try {
      await upsertCampusTrack(cancelling, "cancelled");
      toast?.success?.("已标记为取消");
      setCancelling(null);
      void fetchSummary();
    } catch {
      toast?.error?.("操作失败，请重试");
      setCancelling(null);
    }
  };

  return (
    <div className="p-4 md:p-6 max-w-6xl mx-auto">
      {/* ── 页头 ── */}
      <header className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-lg font-semibold text-[var(--color-text)]">求职复盘</h1>
          <p className="text-xs text-[var(--color-text-muted)] mt-0.5">
            投递漏斗、转化率、拒因聚类与幽灵候选一屏掌握
          </p>
        </div>
        <button
          onClick={() => void fetchSummary()}
          className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-full text-sm font-medium
            text-white bg-brand hover:bg-[#0077ed] hover:scale-[1.02] active:scale-[0.98]
            transition-all duration-300 cursor-pointer"
          aria-label="刷新复盘数据"
        >
          <ArrowClockwise size={14} weight="bold" aria-hidden="true" />
          刷新
        </button>
      </header>

      {loading ? (
        <div className="flex items-center gap-2 py-12 justify-center">
          <Spinner size={16} className="animate-spin text-[var(--color-text-muted)]" aria-hidden="true" />
          <span className="text-sm text-[var(--color-text-muted)]">加载中...</span>
        </div>
      ) : !summary ? (
        <div className="glass-card p-8 text-center">
          <ChartBar size={28} className="mx-auto text-[var(--color-text-muted)]" aria-hidden="true" />
          <p className="mt-3 text-sm text-[var(--color-text-muted)]">
            暂无复盘数据，先在校招页对岗位进行投递跟踪吧
          </p>
        </div>
      ) : (
        <div className="space-y-5">
          {/* ── KPI 网格 ── */}
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4">
            <KpiCard value={summary.kpis.applied} label="已投递" />
            <KpiCard value={summary.kpis.active} label="进行中" hint="未到终态" />
            <KpiCard value={fmtRate(summary.kpis.response_rate)} label="回响率" hint="≥一面" />
            <KpiCard value={fmtRate(summary.kpis.interview_rate)} label="面试率" />
            <KpiCard value={fmtRate(summary.kpis.offer_rate)} label="Offer 率" />
            <KpiCard value={summary.kpis.ghost_count} label="幽灵数" hint="超阈值无回应" />
            <KpiCard
              value={summary.kpis.avg_response_days ?? "—"}
              label="平均回响天数"
              hint={summary.kpis.avg_response_days == null ? "暂无回响记录" : undefined}
            />
          </div>

          {/* ── 投递漏斗 ── */}
          <Section
            icon={<Funnel size={16} weight="duotone" className="text-brand" aria-hidden="true" />}
            title="投递漏斗"
            subtitle="按当前状态分布（含零）"
          >
            <HBar
              rows={summary.funnel.map((f) => ({
                label: getTrackStatusOption(f.status).label,
                value: f.count,
              }))}
            />
          </Section>

          {/* ── 阶段转化 ── */}
          <Section
            icon={<ArrowRight size={16} weight="duotone" className="text-sky-400" aria-hidden="true" />}
            title="阶段转化"
            subtitle="相邻阶段到达率"
          >
            {summary.conversion.length === 0 ? (
              <p className="text-xs text-[var(--color-text-muted)]">暂无转化数据</p>
            ) : (
              <div className="flex flex-wrap gap-2">
                {summary.conversion.map((c) => (
                  <span
                    key={`${c.from}-${c.to}`}
                    className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full
                      bg-sky-500/10 border border-sky-500/30 text-xs text-[var(--color-text-secondary)]"
                  >
                    {getTrackStatusOption(c.from).label}
                    <ArrowRight size={11} className="text-[var(--color-text-muted)]" aria-hidden="true" />
                    {getTrackStatusOption(c.to).label}
                    <span className="text-sky-400 font-medium tabular-nums">{fmtRate(c.rate)}</span>
                  </span>
                ))}
              </div>
            )}
          </Section>

          {/* ── 拒因聚类 ── */}
          <Section
            icon={<Prohibit size={16} weight="duotone" className="text-rose-400" aria-hidden="true" />}
            title="拒信原因聚类"
            subtitle="标记「已拒绝」时填写的拒信理由按桶汇总"
          >
            {summary.rejection_reasons.length === 0 ? (
              <p className="text-xs text-[var(--color-text-muted)]">暂无拒信记录，拒绝时填写原因自动聚类</p>
            ) : (
              <HBar
                rows={summary.rejection_reasons.map((r) => ({ label: r.bucket, value: r.count }))}
                color="var(--color-rose, #f43f5e)"
              />
            )}
          </Section>

          {/* ── 幽灵候选 ── */}
          <Section
            icon={<Ghost size={16} weight="duotone" className="text-amber-400" aria-hidden="true" />}
            title="幽灵候选"
            subtitle="投递超过阈值无回应的岗位（未来面试会自动豁免）"
          >
            {summary.ghost_candidates.length === 0 ? (
              <p className="text-xs text-[var(--color-text-muted)]">暂无幽灵候选，一切都在推进中</p>
            ) : (
              <div className="space-y-2">
                {summary.ghost_candidates.map((g) => (
                  <div
                    key={g.campus_record_id}
                    className="flex items-center justify-between gap-3 rounded-lg
                      bg-[var(--color-bg-secondary)]/60 border border-[var(--color-border)] px-3 py-2"
                  >
                    <div className="flex items-center gap-2 min-w-0">
                      <CalendarBlank size={14} className="text-[var(--color-text-muted)] shrink-0" aria-hidden="true" />
                      <span className="text-xs text-[var(--color-text-secondary)] truncate">
                        {g.campus_record_id}
                      </span>
                      <span className="text-[10px] text-[var(--color-text-muted)] shrink-0">
                        沉默 {g.days_since} 天
                      </span>
                    </div>
                    <button
                      onClick={() => setCancelling(g.campus_record_id)}
                      className="shrink-0 inline-flex items-center gap-1 px-2.5 py-1 rounded-full
                        text-xs text-amber-400 bg-amber-500/10 border border-amber-500/30
                        hover:bg-amber-500/20 transition-colors cursor-pointer"
                    >
                      <Prohibit size={11} aria-hidden="true" />
                      标记取消
                    </button>
                  </div>
                ))}
              </div>
            )}
          </Section>
        </div>
      )}

      {/* 标记取消确认 */}
      <ConfirmDialog
        open={cancelling !== null}
        title="标记为取消"
        description="确认将该岗位标记为「取消」？幽灵候选将不再出现在本列表。"
        confirmText="确认取消"
        danger
        onConfirm={() => void handleCancelGhost()}
        onCancel={() => setCancelling(null)}
      />
    </div>
  );
}
