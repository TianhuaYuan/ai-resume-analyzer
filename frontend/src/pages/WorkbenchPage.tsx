import { useEffect, useState, useCallback, useRef } from "react";
import { Link } from "react-router-dom";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
  LineChart,
  Line,
} from "recharts";
import {
  Plus,
  X,
  MapPin,
  Briefcase,
  ChartBar,
  Trash,
  PencilSimple,
  ArrowLeft,
} from "@phosphor-icons/react";
import { useToast } from "../components/Toast";
import {
  listJobApplications,
  createJobApplication,
  updateJobApplication,
  deleteJobApplication,
  getKanbanStats,
  KANBAN_COLUMNS,
  type JobApplication,
  type JobApplicationCreate,
  type JobApplicationUpdate,
  type KanbanStats,
} from "../api/jobs";

// ── 调色板 ──
const CHART_COLORS = [
  "#38bdf8",
  "#a78bfa",
  "#f59e0b",
  "#34d399",
  "#f472b6",
  "#f87171",
];

// ── 表单弹窗 ─────────────────────────────────────────────

interface FormModalProps {
  open: boolean;
  initial?: JobApplication | null;
  onClose: () => void;
  onSubmit: (data: JobApplicationCreate) => Promise<void>;
  onDelete?: (id: number) => Promise<void>;
}

function ApplicationFormModal({
  open,
  initial,
  onClose,
  onSubmit,
  onDelete,
}: FormModalProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [form, setForm] = useState<JobApplicationCreate>({
    company: "",
    position: "",
    city: "",
    salary_range: "",
    status: "wishlist",
    applied_at: null,
  });

  useEffect(() => {
    if (open) {
      setForm({
        company: initial?.company ?? "",
        position: initial?.position ?? "",
        city: initial?.city ?? "",
        salary_range: initial?.salary_range ?? "",
        status: initial?.status ?? "wishlist",
        applied_at: initial?.applied_at ?? null,
      });
    }
  }, [open, initial]);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open) {
      try {
        dialog.showModal();
      } catch {
        dialog.open = true;
      }
    } else {
      try {
        dialog.close();
      } catch {
        dialog.open = false;
      }
    }
  }, [open]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.company.trim() || !form.position.trim()) return;
    setSaving(true);
    try {
      await onSubmit({
        ...form,
        city: form.city?.trim() || null,
        salary_range: form.salary_range?.trim() || null,
      });
      onClose();
    } catch {
      // onSubmit 内部处理 toast
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!initial || !onDelete) return;
    setDeleting(true);
    try {
      await onDelete(initial.id);
      onClose();
    } catch {
      // onDelete 内部处理 toast
    } finally {
      setDeleting(false);
    }
  };

  if (!open) return null;

  return (
    <dialog
      ref={dialogRef}
      onCancel={onClose}
      onClose={onClose}
      className="fixed inset-0 z-[60] m-0 w-full h-full p-0
        bg-black/60 backdrop-blur-sm motion-reduce:backdrop-blur-none"
      role="dialog"
      aria-modal="true"
      aria-label={initial ? "编辑求职申请" : "添加求职申请"}
    >
      <div
        className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2
          bg-[var(--color-bg-elevated,var(--color-surface))] border border-[var(--color-border)] rounded-2xl
          max-w-lg w-full mx-4 shadow-2xl
          animate-fade-in-up motion-reduce:animate-none"
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--color-border)]">
          <h3 className="text-base font-semibold text-[var(--color-text)]">
            {initial ? "编辑申请" : "添加申请"}
          </h3>
          <button
            onClick={onClose}
            aria-label="关闭"
            className="p-1.5 rounded-lg text-[var(--color-text-secondary)]
              hover:text-[var(--color-text)] hover:bg-white/8
              transition-all cursor-pointer"
          >
            <X size={18} weight="bold" aria-hidden="true" />
          </button>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="px-6 py-5 space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">
                公司 <span className="text-red-400">*</span>
              </label>
              <input
                type="text"
                value={form.company}
                onChange={(e) => setForm({ ...form, company: e.target.value })}
                required
                maxLength={100}
                className="w-full px-3 py-2 rounded-lg bg-[var(--color-bg)] border border-[var(--color-border)]
                  text-sm text-[var(--color-text)]
                  focus:outline-none focus:border-indigo-500 transition-colors"
                placeholder="如：字节跳动"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">
                职位 <span className="text-red-400">*</span>
              </label>
              <input
                type="text"
                value={form.position}
                onChange={(e) => setForm({ ...form, position: e.target.value })}
                required
                maxLength={100}
                className="w-full px-3 py-2 rounded-lg bg-[var(--color-bg)] border border-[var(--color-border)]
                  text-sm text-[var(--color-text)]
                  focus:outline-none focus:border-indigo-500 transition-colors"
                placeholder="如：后端工程师"
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">
                城市
              </label>
              <input
                type="text"
                value={form.city ?? ""}
                onChange={(e) => setForm({ ...form, city: e.target.value })}
                maxLength={50}
                className="w-full px-3 py-2 rounded-lg bg-[var(--color-bg)] border border-[var(--color-border)]
                  text-sm text-[var(--color-text)]
                  focus:outline-none focus:border-indigo-500 transition-colors"
                placeholder="如：北京"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">
                薪资范围
              </label>
              <input
                type="text"
                value={form.salary_range ?? ""}
                onChange={(e) => setForm({ ...form, salary_range: e.target.value })}
                maxLength={50}
                className="w-full px-3 py-2 rounded-lg bg-[var(--color-bg)] border border-[var(--color-border)]
                  text-sm text-[var(--color-text)]
                  focus:outline-none focus:border-indigo-500 transition-colors"
                placeholder="如：25-40k"
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">
                状态
              </label>
              <select
                value={form.status}
                onChange={(e) => setForm({ ...form, status: e.target.value })}
                className="w-full px-3 py-2 rounded-lg bg-[var(--color-bg)] border border-[var(--color-border)]
                  text-sm text-[var(--color-text)]
                  focus:outline-none focus:border-indigo-500 transition-colors cursor-pointer"
              >
                {KANBAN_COLUMNS.map((col) => (
                  <option key={col.status} value={col.status}>
                    {col.label}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">
                投递时间
              </label>
              <input
                type="date"
                value={
                  form.applied_at
                    ? form.applied_at.slice(0, 10)
                    : ""
                }
                onChange={(e) =>
                  setForm({
                    ...form,
                    applied_at: e.target.value
                      ? new Date(e.target.value).toISOString()
                      : null,
                  })
                }
                className="w-full px-3 py-2 rounded-lg bg-[var(--color-bg)] border border-[var(--color-border)]
                  text-sm text-[var(--color-text)]
                  focus:outline-none focus:border-indigo-500 transition-colors"
              />
            </div>
          </div>
        </form>

        {/* Footer */}
        <div className="flex items-center justify-between px-6 py-4 border-t border-[var(--color-border)]">
          <div>
            {initial && onDelete && (
              <button
                onClick={handleDelete}
                disabled={deleting}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium rounded-lg
                  text-red-300 bg-red-500/10 border border-red-500/20
                  hover:bg-red-500/20 hover:border-red-500/40
                  disabled:opacity-50 disabled:cursor-not-allowed
                  transition-all cursor-pointer"
              >
                <Trash size={14} weight="bold" aria-hidden="true" />
                {deleting ? "删除中..." : "删除"}
              </button>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={onClose}
              className="px-3.5 py-1.5 text-sm font-medium rounded-lg
                text-[var(--color-text-secondary)] hover:text-[var(--color-text)] hover:bg-white/8
                transition-all cursor-pointer"
            >
              取消
            </button>
            <button
              onClick={handleSubmit}
              disabled={saving}
              className="px-3.5 py-1.5 text-sm font-medium rounded-lg
                bg-indigo-500/20 hover:bg-indigo-500/30 text-indigo-300 border border-indigo-500/40
                disabled:opacity-50 disabled:cursor-not-allowed
                transition-all cursor-pointer flex items-center gap-1.5"
            >
              {saving ? "保存中..." : initial ? "保存" : "添加"}
            </button>
          </div>
        </div>
      </div>
    </dialog>
  );
}

// ── 统计图表区 ─────────────────────────────────────────────

function StatsCharts({ stats }: { stats: KanbanStats | null }) {
  if (!stats) return null;

  const statusData = KANBAN_COLUMNS.map((col) => ({
    name: col.label,
    count: stats.by_status[col.status] ?? 0,
    color: col.color,
  }));

  const companyData = stats.by_company.map((c, i) => ({
    name: c.company,
    value: c.count,
    color: CHART_COLORS[i % CHART_COLORS.length],
  }));

  const trendData = stats.trend.map((t) => ({
    date: t.date.slice(5),
    count: t.count,
  }));

  const tooltipStyle = {
    background: "var(--color-bg)",
    border: "1px solid var(--color-border)",
    borderRadius: 4,
    fontSize: 12,
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-8">
      {/* 按状态分布 - 柱状图 */}
      <div className="border border-[var(--color-border)] rounded-lg p-4">
        <h3 className="text-xs font-mono-label tracking-widest uppercase text-[var(--color-text-muted)] mb-3">
          申请状态分布
        </h3>
        <ResponsiveContainer width="100%" height={200}>
          <BarChart data={statusData}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
            <XAxis
              dataKey="name"
              tick={{ fontSize: 10, fill: "var(--color-text-secondary)" }}
              interval={0}
              angle={-30}
              textAnchor="end"
              height={50}
            />
            <YAxis
              allowDecimals={false}
              tick={{ fontSize: 10, fill: "var(--color-text-secondary)" }}
            />
            <Tooltip contentStyle={tooltipStyle} />
            <Bar dataKey="count" radius={[2, 2, 0, 0]}>
              {statusData.map((entry, i) => (
                <Cell key={i} fill={entry.color} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* Top 5 公司 - 饼图 */}
      <div className="border border-[var(--color-border)] rounded-lg p-4">
        <h3 className="text-xs font-mono-label tracking-widest uppercase text-[var(--color-text-muted)] mb-3">
          投递公司 Top 5
        </h3>
        {companyData.length === 0 ? (
          <div className="h-[200px] flex items-center justify-center text-xs text-[var(--color-text-muted)]">
            暂无数据
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={200}>
            <PieChart>
              <Pie
                data={companyData}
                dataKey="value"
                nameKey="name"
                cx="50%"
                cy="50%"
                outerRadius={70}
                label={({ name, value }: { name?: string; value?: number }) =>
                  `${name} ${value}`
                }
                labelLine={false}
              >
                {companyData.map((entry, i) => (
                  <Cell key={i} fill={entry.color} />
                ))}
              </Pie>
              <Tooltip contentStyle={tooltipStyle} />
            </PieChart>
          </ResponsiveContainer>
        )}
      </div>

      {/* 近 30 天趋势 - 折线图 */}
      <div className="border border-[var(--color-border)] rounded-lg p-4">
        <h3 className="text-xs font-mono-label tracking-widest uppercase text-[var(--color-text-muted)] mb-3">
          近 30 天投递趋势
        </h3>
        {trendData.length === 0 ? (
          <div className="h-[200px] flex items-center justify-center text-xs text-[var(--color-text-muted)]">
            暂无数据
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={200}>
            <LineChart data={trendData}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
              <XAxis
                dataKey="date"
                tick={{ fontSize: 10, fill: "var(--color-text-secondary)" }}
              />
              <YAxis
                allowDecimals={false}
                tick={{ fontSize: 10, fill: "var(--color-text-secondary)" }}
              />
              <Tooltip contentStyle={tooltipStyle} />
              <Line
                type="monotone"
                dataKey="count"
                stroke="#38bdf8"
                strokeWidth={2}
                dot={{ r: 3, fill: "#38bdf8" }}
              />
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  );
}

// ── 看板卡片 ──

function KanbanCard({
  app,
  onClick,
}: {
  app: JobApplication;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className="w-full text-left p-3 rounded-lg
        bg-[var(--color-bg-elevated,var(--color-surface))]
        border border-[var(--color-border)]
        hover:border-[var(--color-text-muted)]
        transition-all cursor-pointer group"
    >
      <div className="flex items-start justify-between gap-2 mb-1.5">
        <p className="text-sm font-medium text-[var(--color-text)] truncate">
          {app.company}
        </p>
        <PencilSimple
          size={12}
          weight="regular"
          className="text-[var(--color-text-muted)] opacity-0 group-hover:opacity-100 transition-opacity shrink-0 mt-0.5"
          aria-hidden="true"
        />
      </div>
      <p className="text-xs text-[var(--color-text-secondary)] truncate mb-2">
        {app.position}
      </p>
      <div className="flex items-center gap-2 text-[10px] text-[var(--color-text-muted)]">
        {app.city && (
          <span className="inline-flex items-center gap-0.5">
            <MapPin size={10} weight="fill" aria-hidden="true" />
            {app.city}
          </span>
        )}
        {app.salary_range && (
          <span className="inline-flex items-center gap-0.5">
            <Briefcase size={10} weight="fill" aria-hidden="true" />
            {app.salary_range}
          </span>
        )}
      </div>
    </button>
  );
}

// ── 主页面 ─────────────────────────────────────────────────

export default function WorkbenchPage() {
  const [apps, setApps] = useState<JobApplication[]>([]);
  const [stats, setStats] = useState<KanbanStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [modalOpen, setModalOpen] = useState(false);
  const [editingApp, setEditingApp] = useState<JobApplication | null>(null);
  const toast = useToast();

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [listData, statsData] = await Promise.all([
        listJobApplications(undefined, 100, 0),
        getKanbanStats(),
      ]);
      setApps(listData.items);
      setStats(statsData);
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const openCreate = () => {
    setEditingApp(null);
    setModalOpen(true);
  };

  const openEdit = (app: JobApplication) => {
    setEditingApp(app);
    setModalOpen(true);
  };

  const handleSubmit = async (data: JobApplicationCreate) => {
    if (editingApp) {
      await updateJobApplication(editingApp.id, data as JobApplicationUpdate);
      toast.success("已更新");
    } else {
      await createJobApplication(data);
      toast.success("已添加");
    }
    await fetchData();
  };

  const handleDelete = async (id: number) => {
    await deleteJobApplication(id);
    toast.success("已删除");
    await fetchData();
  };

  // 按状态分组
  const grouped = KANBAN_COLUMNS.map((col) => ({
    ...col,
    items: apps.filter((a) => a.status === col.status),
  }));

  return (
    <div className="min-h-screen bg-[var(--color-bg)]">
      <div className="max-w-7xl mx-auto">
        {/* ── 顶部栏 ── */}
        <div className="sticky top-[49px] z-30 bg-[var(--color-bg)] px-6 md:px-8 lg:px-12 py-4 border-b border-[var(--color-border)] flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Link
              to="/"
              className="inline-flex items-center gap-1 text-xs text-[var(--color-text-muted)]
                hover:text-indigo-400 transition-colors"
              aria-label="返回首页"
            >
              <ArrowLeft size={12} weight="regular" aria-hidden="true" />
              返回首页
            </Link>
            <h1 className="font-display text-3xl md:text-4xl font-bold tracking-tight text-[var(--color-text)]">
              求职看板
            </h1>
            {stats && (
              <span className="font-mono-label tabular-nums text-sm font-normal tracking-widest text-[var(--color-text-muted)] uppercase">
                {stats.total} 个申请
              </span>
            )}
          </div>
          <button
            onClick={openCreate}
            className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium
              text-white bg-linear-to-br from-indigo-500 to-purple-600
              hover:brightness-110 hover:shadow-lg hover:shadow-indigo-500/20
              active:scale-[0.98] motion-reduce:active:scale-100
              transition-all cursor-pointer"
            aria-label="添加申请"
          >
            <Plus size={16} weight="bold" aria-hidden="true" />
            添加申请
          </button>
        </div>

        {/* ── 内容区 ── */}
        <div className="px-6 md:px-8 lg:px-12 py-8">
          {loading ? (
            <div className="flex items-center justify-center py-32">
              <div className="inline-block w-6 h-6 rounded-full border-2 border-[var(--color-text-muted)] border-t-[var(--color-text)] animate-spin" />
            </div>
          ) : apps.length === 0 ? (
            /* 空状态 */
            <div className="py-16 md:py-32 flex flex-col items-center text-center">
              <div className="w-16 h-16 border-2 border-[var(--color-text)] flex items-center justify-center mb-6">
                <ChartBar size={28} weight="regular" className="text-[var(--color-text)]" aria-hidden="true" />
              </div>
              <p className="font-display text-2xl md:text-3xl font-bold tracking-tight text-[var(--color-text)] mb-3">
                开始追踪你的求职进度
              </p>
              <p className="text-sm text-[var(--color-text-secondary)] mb-6 max-w-md">
                添加你的求职申请，用看板管理投递状态，用图表分析投递趋势。
              </p>
              <button onClick={openCreate} className="mono-btn-primary inline-flex">
                添加第一个申请 →
              </button>
            </div>
          ) : (
            <>
              {/* 统计图表 */}
              <StatsCharts stats={stats} />

              {/* 看板 */}
              <div className="flex gap-4 overflow-x-auto pb-4">
                {grouped.map((col) => (
                  <div
                    key={col.status}
                    className="shrink-0 w-64 flex flex-col"
                  >
                    {/* 列头 */}
                    <div className="flex items-center justify-between px-3 py-2 mb-2 border-b-2"
                      style={{ borderColor: col.color }}
                    >
                      <span className="text-xs font-medium text-[var(--color-text)]">
                        {col.label}
                      </span>
                      <span
                        className="text-[10px] font-mono-label tabular-nums px-1.5 py-0.5 rounded text-white"
                        style={{ backgroundColor: col.color }}
                      >
                        {col.items.length}
                      </span>
                    </div>

                    {/* 卡片列表 */}
                    <div className="flex-1 space-y-2 min-h-[60px]">
                      {col.items.length === 0 ? (
                        <div className="text-[10px] text-[var(--color-text-muted)] text-center py-4 border border-dashed border-[var(--color-border)] rounded-lg">
                          暂无
                        </div>
                      ) : (
                        col.items.map((app) => (
                          <KanbanCard
                            key={app.id}
                            app={app}
                            onClick={() => openEdit(app)}
                          />
                        ))
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      </div>

      {/* 表单弹窗 */}
      <ApplicationFormModal
        open={modalOpen}
        initial={editingApp}
        onClose={() => setModalOpen(false)}
        onSubmit={handleSubmit}
        onDelete={editingApp ? handleDelete : undefined}
      />
    </div>
  );
}
