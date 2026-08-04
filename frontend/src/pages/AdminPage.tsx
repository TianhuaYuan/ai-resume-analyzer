import { useEffect, useState, useCallback } from "react";
import { Link } from "react-router-dom";
import {
  ChartBar,
  Gauge,
  ListChecks,
  ChatTeardropText,
  FileText,
  Monitor,
  ArrowLeft,
  Users,
  Database,
  ChatCircleDots,
  MagnifyingGlass,
  Warning,
} from "@phosphor-icons/react";
import {
  getSystemStats,
  getAuditLogs,
  getAdminFeedback,
  getAdminTemplates,
  getTrends,
  getLLMUsage,
  type SystemStats,
  type AuditLogItem,
  type FeedbackItem,
  type TemplateInfo,
  type TrendItem,
  type LLMUsageItem,
} from "../api/admin";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  Bar,
  BarChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

type TabId = "stats" | "audit" | "feedback" | "templates" | "grafana";

const TABS: { id: TabId; label: string; icon: typeof ChartBar }[] = [
  { id: "stats", label: "系统概览", icon: Gauge },
  { id: "audit", label: "审计日志", icon: ListChecks },
  { id: "feedback", label: "用户反馈", icon: ChatTeardropText },
  { id: "templates", label: "简历模板", icon: FileText },
  { id: "grafana", label: "监控面板", icon: Monitor },
];

/** ISO → "MM-DD HH:mm"（北京时间）。后端 naive datetime 视为 UTC。 */
function formatTimestamp(dateStr?: string | null): string {
  if (!dateStr) return "-";
  const normalized = /[Z+]/.test(dateStr) ? dateStr : dateStr + "Z";
  const d = new Date(normalized);
  if (isNaN(d.getTime())) return "-";
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "Asia/Shanghai",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(d);
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? "";
  return `${get("month")}-${get("day")} ${get("hour")}:${get("minute")}`;
}

// ── 系统概览 ──────────────────────────────────────────────

function StatsSection() {
  const [stats, setStats] = useState<SystemStats | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    getSystemStats()
      .then(setStats)
      .catch((e) => setError(e instanceof Error ? e.message : "加载失败"));
  }, []);

  if (error) {
    return <ErrorBox message={error} />;
  }
  if (!stats) {
    return <Loading />;
  }

  const cards = [
    { label: "用户总数", value: stats.total_users, icon: Users, color: "text-brand" },
    { label: "简历总数", value: stats.total_resumes, icon: Database, color: "text-emerald-500" },
    { label: "问答记录", value: stats.total_qa_history, icon: ChatCircleDots, color: "text-sky-500" },
    { label: "用户反馈", value: stats.total_feedback, icon: ChatTeardropText, color: "text-amber-500" },
  ];

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
      {cards.map((c) => {
        const Icon = c.icon;
        return (
          <div
            key={c.label}
            className="glass-card p-4 hover:-translate-y-1 hover:shadow-xl hover:shadow-black/5 transition-all duration-300"
          >
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs text-[var(--color-text-muted)]">{c.label}</span>
              <Icon size={16} weight="duotone" className={c.color} aria-hidden="true" />
            </div>
            <div className="text-2xl font-semibold text-[var(--color-text)] tabular-nums">
              {c.value}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ── D3/D4: 数据趋势看板 ──────────────────────────────────

function TrendsSection() {
  const [days, setDays] = useState(30);
  const [trends, setTrends] = useState<TrendItem[]>([]);
  const [usage, setUsage] = useState<LLMUsageItem[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    setError("");
    Promise.all([getTrends(days), getLLMUsage(7)])
      .then(([t, u]) => {
        setTrends(t.items);
        setUsage(u.items);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "趋势加载失败"))
      .finally(() => setLoading(false));
  }, [days]);

  if (error) return <ErrorBox message={error} />;
  if (loading) return <Loading />;

  // 趋势图数据：日期 → "MM-DD" 显示
  const trendData = trends.map((t) => ({
    ...t,
    dayLabel: t.day.slice(5), // YYYY-MM-DD → MM-DD
  }));
  const usageData = usage.map((u) => ({
    ...u,
    dayLabel: u.date.slice(4), // YYYYMMDD → MMDD
    tokens_k: Math.round(u.total_tokens / 1000), // 千 token，便于阅读
  }));

  return (
    <div className="mt-6 space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-[var(--color-text)]">
          数据趋势（注册 / 日活 / 事件）
        </h3>
        <div className="flex gap-1 text-xs">
          {[7, 30, 90].map((d) => (
            <button
              key={d}
              onClick={() => setDays(d)}
              className={`px-2.5 py-1 rounded-lg transition-colors cursor-pointer ${
                days === d
                  ? "bg-brand text-white"
                  : "bg-[var(--color-bg-secondary)] text-[var(--color-text-secondary)] hover:bg-black/5"
              }`}
            >
              {d}天
            </button>
          ))}
        </div>
      </div>

      <div className="glass-card p-4">
        <ResponsiveContainer width="100%" height={220}>
          <LineChart data={trendData} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(0,0,0,0.06)" />
            <XAxis dataKey="dayLabel" fontSize={11} tickLine={false} axisLine={false} />
            <YAxis fontSize={11} tickLine={false} axisLine={false} allowDecimals={false} />
            <Tooltip />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            <Line type="monotone" dataKey="registrations" name="注册" stroke="#3b82f6" strokeWidth={2} dot={false} />
            <Line type="monotone" dataKey="active_users" name="活跃用户" stroke="#10b981" strokeWidth={2} dot={false} />
            <Line type="monotone" dataKey="events" name="事件数" stroke="#f59e0b" strokeWidth={2} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>

      {usageData.length > 0 && (
        <div className="glass-card p-4">
          <h4 className="text-sm font-semibold text-[var(--color-text)] mb-2">
            LLM 用量（近 7 天，千 token）
          </h4>
          <ResponsiveContainer width="100%" height={180}>
            <BarChart data={usageData} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(0,0,0,0.06)" />
              <XAxis dataKey="dayLabel" fontSize={11} tickLine={false} axisLine={false} />
              <YAxis fontSize={11} tickLine={false} axisLine={false} allowDecimals={false} />
              <Tooltip />
              <Bar dataKey="tokens_k" name="Token 用量(K)" fill="#8b5cf6" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}

// ── 审计日志 ──────────────────────────────────────────────

function AuditSection() {
  const [items, setItems] = useState<AuditLogItem[]>([]);
  const [total, setTotal] = useState(0);
  const [actionFilter, setActionFilter] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [offset, setOffset] = useState(0);
  const LIMIT = 20;

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await getAuditLogs({
        action: actionFilter.trim() || undefined,
        limit: LIMIT,
        offset,
      });
      setItems(data.items);
      setTotal(data.total);
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, [actionFilter, offset]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 flex-wrap">
        <div className="relative">
          <MagnifyingGlass
            size={14}
            weight="bold"
            aria-hidden="true"
            className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[var(--color-text-muted)] pointer-events-none"
          />
          <input
            type="text"
            value={actionFilter}
            onChange={(e) => {
              setActionFilter(e.target.value);
              setOffset(0);
            }}
            placeholder="按 action 过滤，如 login"
            className="w-52 pl-8 pr-3 py-1.5 rounded-xl text-xs text-[var(--color-text)]
              bg-[#F2F2F7] border border-transparent
              placeholder:text-[var(--color-text-muted)]
              focus:outline-none focus:bg-white focus:border-brand/40 focus:ring-4 focus:ring-brand/15"
          />
        </div>
        <span className="text-xs text-[var(--color-text-muted)]">
          共 <span className="tabular-nums">{total}</span> 条
        </span>
      </div>

      {error ? (
        <ErrorBox message={error} />
      ) : (
        <div className="overflow-x-auto rounded-2xl border border-[var(--color-border)] bg-[var(--color-card)]">
          <table className="w-full text-xs">
            <thead className="bg-[var(--color-bg-secondary)] text-[var(--color-text-muted)]">
              <tr>
                <th className="text-left px-3 py-2 font-medium">Action</th>
                <th className="text-left px-3 py-2 font-medium">用户 ID</th>
                <th className="text-left px-3 py-2 font-medium">目标</th>
                <th className="text-left px-3 py-2 font-medium">IP</th>
                <th className="text-left px-3 py-2 font-medium">时间</th>
              </tr>
            </thead>
            <tbody>
              {loading && items.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-3 py-8 text-center text-[var(--color-text-muted)]">
                    加载中...
                  </td>
                </tr>
              ) : items.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-3 py-8 text-center text-[var(--color-text-muted)]">
                    暂无审计日志
                  </td>
                </tr>
              ) : (
                items.map((it) => (
                  <tr
                    key={it.id}
                    className="border-t border-[var(--color-border)] text-[var(--color-text-secondary)]"
                  >
                    <td className="px-3 py-2">
                      <span className="inline-flex items-center px-1.5 py-0.5 rounded
                        bg-brand/10 text-brand text-[11px] font-medium">
                        {it.action}
                      </span>
                    </td>
                    <td className="px-3 py-2 tabular-nums">{it.user_id ?? "-"}</td>
                    <td className="px-3 py-2">
                      {it.target_type ? `${it.target_type}${it.target_id ? "#" + it.target_id : ""}` : "-"}
                    </td>
                    <td className="px-3 py-2 font-mono text-[11px]">{it.ip ?? "-"}</td>
                    <td className="px-3 py-2 tabular-nums">{formatTimestamp(it.created_at)}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}

      <Pagination offset={offset} limit={LIMIT} total={total} onChange={setOffset} />
    </div>
  );
}

// ── 用户反馈 ──────────────────────────────────────────────

function FeedbackSection() {
  const [items, setItems] = useState<FeedbackItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [offset, setOffset] = useState(0);
  const LIMIT = 20;

  useEffect(() => {
    setLoading(true);
    setError("");
    getAdminFeedback({ limit: LIMIT, offset })
      .then((data) => {
        setItems(data.items);
        setTotal(data.total);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "加载失败"))
      .finally(() => setLoading(false));
  }, [offset]);

  const typeColor: Record<string, string> = {
    bug: "bg-red-500/10 text-red-600",
    feature: "bg-emerald-500/10 text-emerald-600",
    other: "bg-sky-500/10 text-sky-600",
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <span className="text-xs text-[var(--color-text-muted)]">
          共 <span className="tabular-nums">{total}</span> 条反馈
        </span>
      </div>

      {error ? (
        <ErrorBox message={error} />
      ) : (
        <div className="overflow-x-auto rounded-2xl border border-[var(--color-border)] bg-[var(--color-card)]">
          <table className="w-full text-xs">
            <thead className="bg-[var(--color-bg-secondary)] text-[var(--color-text-muted)]">
              <tr>
                <th className="text-left px-3 py-2 font-medium">内容</th>
                <th className="text-left px-3 py-2 font-medium">类型</th>
                <th className="text-left px-3 py-2 font-medium">状态</th>
                <th className="text-left px-3 py-2 font-medium">用户 ID</th>
                <th className="text-left px-3 py-2 font-medium">时间</th>
              </tr>
            </thead>
            <tbody>
              {loading && items.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-3 py-8 text-center text-[var(--color-text-muted)]">
                    加载中...
                  </td>
                </tr>
              ) : items.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-3 py-8 text-center text-[var(--color-text-muted)]">
                    暂无用户反馈
                  </td>
                </tr>
              ) : (
                items.map((it) => (
                  <tr
                    key={it.id}
                    className="border-t border-[var(--color-border)] text-[var(--color-text-secondary)]"
                  >
                    <td className="px-3 py-2 max-w-md truncate" title={it.content}>
                      {it.content}
                    </td>
                    <td className="px-3 py-2">
                      <span
                        className={`inline-flex items-center px-1.5 py-0.5 rounded text-[11px] font-medium ${
                          typeColor[it.type] ?? "bg-[var(--color-bg-secondary)] text-[var(--color-text-muted)]"
                        }`}
                      >
                        {it.type}
                      </span>
                    </td>
                    <td className="px-3 py-2">{it.status}</td>
                    <td className="px-3 py-2 tabular-nums">{it.user_id}</td>
                    <td className="px-3 py-2 tabular-nums">{formatTimestamp(it.created_at)}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}

      <Pagination offset={offset} limit={LIMIT} total={total} onChange={setOffset} />
    </div>
  );
}

// ── 简历模板 ──────────────────────────────────────────────

function TemplatesSection() {
  const [templates, setTemplates] = useState<TemplateInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    setLoading(true);
    getAdminTemplates()
      .then((data) => setTemplates(data.templates))
      .catch((e) => setError(e instanceof Error ? e.message : "加载失败"))
      .finally(() => setLoading(false));
  }, []);

  if (error) return <ErrorBox message={error} />;
  if (loading) return <Loading />;

  return (
    <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
      {templates.map((t) => (
        <div
          key={t.id}
          className="glass-card p-4 hover:-translate-y-1 hover:shadow-xl hover:shadow-black/5 transition-all duration-300"
        >
          <div className="flex items-center gap-2 mb-2">
            <FileText size={18} weight="duotone" className="text-brand" aria-hidden="true" />
            <span className="text-sm font-semibold text-[var(--color-text)]">{t.name}</span>
            <span className="text-[10px] text-[var(--color-text-muted)] font-mono">{t.id}</span>
          </div>
          <p className="text-xs text-[var(--color-text-secondary)] mb-3">{t.description}</p>
          <a
            href={`/api/v1/resumes/0/preview?template=${t.id}`}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 text-xs text-brand hover:text-brand-hover transition-colors"
          >
            预览
          </a>
        </div>
      ))}
    </div>
  );
}

// ── Grafana 监控 ─────────────────────────────────────────

function GrafanaSection() {
  return (
    <div className="space-y-2">
      <p className="text-xs text-[var(--color-text-muted)]">
        若已部署 Grafana 并在反向代理中将 <code className="font-mono">/grafana</code> 指向它，则下方将显示监控面板；未配置时为空白。
      </p>
      <div className="rounded-2xl border border-[var(--color-border)] overflow-hidden bg-[var(--color-bg-secondary)]">
        <iframe
          src="/grafana"
          className="w-full h-[560px] border-0"
          title="Grafana 监控面板"
        />
      </div>
    </div>
  );
}

// ── 通用小组件 ────────────────────────────────────────────

function Loading() {
  return (
    <div className="flex items-center justify-center py-12">
      <span className="inline-block w-5 h-5 rounded-full border-2 border-brand border-t-transparent animate-spin" aria-hidden="true" />
      <span className="ml-2 text-xs text-[var(--color-text-muted)]">加载中...</span>
    </div>
  );
}

function ErrorBox({ message }: { message: string }) {
  return (
    <div className="flex items-start gap-2 p-3 rounded-xl bg-red-500/10 border border-red-500/20 text-red-600 text-sm">
      <Warning size={16} weight="bold" className="mt-0.5 shrink-0" aria-hidden="true" />
      <span>{message}</span>
    </div>
  );
}

function Pagination({
  offset,
  limit,
  total,
  onChange,
}: {
  offset: number;
  limit: number;
  total: number;
  onChange: (offset: number) => void;
}) {
  const hasPrev = offset > 0;
  const hasNext = offset + limit < total;
  return (
    <div className="flex items-center gap-2 text-xs">
      <button
        disabled={!hasPrev}
        onClick={() => onChange(Math.max(0, offset - limit))}
        className="px-2.5 py-1 rounded-full bg-[var(--color-bg-secondary)]
          text-[var(--color-text-secondary)] hover:bg-[#E5E5EA]
          disabled:opacity-40 disabled:cursor-not-allowed transition-all cursor-pointer"
      >
        上一页
      </button>
      <span className="text-[var(--color-text-muted)] tabular-nums">
        {total === 0 ? 0 : offset + 1}-{Math.min(offset + limit, total)} / {total}
      </span>
      <button
        disabled={!hasNext}
        onClick={() => onChange(offset + limit)}
        className="px-2.5 py-1 rounded-full bg-[var(--color-bg-secondary)]
          text-[var(--color-text-secondary)] hover:bg-[#E5E5EA]
          disabled:opacity-40 disabled:cursor-not-allowed transition-all cursor-pointer"
      >
        下一页
      </button>
    </div>
  );
}

// ── 主组件 ────────────────────────────────────────────────

export default function AdminPage() {
  const [tab, setTab] = useState<TabId>("stats");
  // 非管理员访问时后端返回 403，展示错误并提示返回
  const [forbidden, setForbidden] = useState(false);

  useEffect(() => {
    // 用 stats 接口探测权限；403 则锁定为无权限视图
    getSystemStats().catch((e) => {
      if (e instanceof Error && /403|管理员|forbidden/i.test(e.message)) {
        setForbidden(true);
      }
    });
  }, []);

  if (forbidden) {
    return (
      <div className="max-w-2xl mx-auto px-6 py-16 text-center">
        <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl
          bg-red-500/10 border border-red-500/15 text-red-500 mb-4">
          <Warning size={26} weight="duotone" aria-hidden="true" />
        </div>
        <h2 className="text-base font-semibold text-[var(--color-text)] mb-1.5">无访问权限</h2>
        <p className="text-sm text-[var(--color-text-muted)] mb-5">
          管理员后台仅对授权账号开放。如需访问，请联系管理员将你的邮箱加入白名单。
        </p>
        <Link
          to="/"
          className="inline-flex items-center gap-1.5 px-4 py-2 rounded-full text-xs font-medium
            bg-[var(--color-bg-secondary)] text-[var(--color-text-secondary)]
            hover:bg-[#E5E5EA] transition-all cursor-pointer"
        >
          <ArrowLeft size={14} weight="regular" aria-hidden="true" />
          返回首页
        </Link>
      </div>
    );
  }

  return (
    <div className="max-w-6xl mx-auto px-4 sm:px-6 py-6">
      {/* 标题 */}
      <div className="flex items-center gap-2 mb-5">
        <ChartBar size={22} weight="duotone" className="text-brand" aria-hidden="true" />
        <h1 className="text-lg font-semibold text-[var(--color-text)]">管理员后台</h1>
        <Link
          to="/"
          className="ml-auto inline-flex items-center gap-1 text-xs text-[var(--color-text-muted)]
            hover:text-brand transition-colors"
        >
          <ArrowLeft size={12} weight="regular" aria-hidden="true" />
          返回首页
        </Link>
      </div>

      {/* Tab 栏 */}
      <div className="flex items-center gap-1 mb-5 border-b border-[var(--color-border)] overflow-x-auto">
        {TABS.map((t) => {
          const Icon = t.icon;
          const isActive = tab === t.id;
          return (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`inline-flex items-center gap-1.5 px-3 py-2 text-xs font-medium
                border-b-2 transition-colors cursor-pointer whitespace-nowrap
                ${isActive
                  ? "border-brand text-brand"
                  : "border-transparent text-[var(--color-text-muted)] hover:text-[var(--color-text-secondary)]"
                }`}
              aria-selected={isActive}
              role="tab"
            >
              <Icon size={14} weight={isActive ? "fill" : "regular"} aria-hidden="true" />
              {t.label}
            </button>
          );
        })}
      </div>

      {/* Tab 内容 */}
      <div>
        {tab === "stats" && (
          <>
            <StatsSection />
            <TrendsSection />
          </>
        )}
        {tab === "audit" && <AuditSection />}
        {tab === "feedback" && <FeedbackSection />}
        {tab === "templates" && <TemplatesSection />}
        {tab === "grafana" && <GrafanaSection />}
      </div>
    </div>
  );
}
