/**
 * JobApplicationsPage — 投递看板（J 功能，阶段 5）。
 *
 * 数据源：/api/v1/job-applications（列表/详情/新建/更新/状态流转/软删除/恢复）
 *         + /api/v1/job-applications/dashboard（看板）
 *
 * 功能：
 * - 顶部统计：总数 / 进行中 / 待投递 / Offer / 高意向
 * - 截止日期红黄绿（≤3 天红 / ≤7 天黄 / 其余绿 / 过期）
 * - 停留 >14 天提醒（stay_days 黄色警示）
 * - 今日队列：致谢 / 催办 / 失联（后端 build_queue 派生，时序规则常量可调）
 * - 投递列表：过滤（状态/优先级/关键词）+ 垃圾箱切换
 * - 新建/编辑弹窗：公司/岗位/URL/优先级/截止/备注/JD（可选生成评分卡）
 * - 状态流转弹窗：校验 STATUS_FLOW，timeline 自动追加
 * - 详情弹窗：时间线 + JD 评分卡 + 备注
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { Plus, LoaderCircle, Trash2, X, Eye, Send, Bell, Ghost, CornerUpLeft, ArrowRight, CalendarDays, Flag, Search, Luggage } from "lucide-react";
import {
  listJobApplications,
  getJobDashboard,
  getJobApplication,
  createJobApplication,
  updateJobApplication,
  transitionJobApplicationStatus,
  deleteJobApplication,
  restoreJobApplication,
  archiveJobApplication,
  APPLICATION_STATUSES,
  APPLICATION_STATUS_FLOW,
  APPLICATION_PRIORITIES,
  type JobApplication,
  type JobDashboard,
  type DashboardQueueItem,
  type ApplicationStatus,
} from "../api/jobApplications";
import { useToast } from "../components/Toast";
import ConfirmDialog from "../components/ConfirmDialog";

// ── 常量与样式 ──

const STATUS_STYLE: Record<string, { bg: string; fg: string }> = {
  待投递: { bg: "#eceff1", fg: "#546e7a" },
  已投递: { bg: "#e3f2fd", fg: "#1565c0" },
  笔试: { bg: "#ede7f6", fg: "#5e35b1" },
  一面: { bg: "#fff3e0", fg: "#ef6c00" },
  二面: { bg: "#ffe0b2", fg: "#e65100" },
  三面: { bg: "#ffccbc", fg: "#d84315" },
  HR面: { bg: "#f3e5f5", fg: "#8e24aa" },
  Offer: { bg: "#e8f5e9", fg: "#2e7d32" },
  已拒: { bg: "#ffebee", fg: "#c62828" },
};

const QUEUE_META: Record<DashboardQueueItem["kind"], { label: string; icon: typeof Bell; cls: string }> = {
  thank_you: { label: "致谢", icon: Send, cls: "text-[var(--color-brand)]" },
  nudge: { label: "催办", icon: Bell, cls: "text-warning" },
  ghost: { label: "失联", icon: Ghost, cls: "text-danger" },
};

/** ISO → "YYYY-MM-DD" */
function fmtDate(s?: string | null): string {
  if (!s) return "-";
  const d = new Date(s);
  if (isNaN(d.getTime())) return "-";
  const p = new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(d);
  const get = (t: string) => p.find((x) => x.type === t)?.value ?? "";
  return `${get("year")}-${get("month")}-${get("day")}`;
}

function deadlineInfo(a: JobApplication): { cls: string; text: string } {
  if (!a.deadline) return { cls: "text-[var(--color-text-muted)]", text: "—" };
  const diff = Math.ceil(
    (new Date(a.deadline + "T00:00:00").getTime() - Date.now()) / 86400000
  );
  if (diff < 0) return { cls: "text-danger font-semibold", text: `${fmtDate(a.deadline)} 已过期` };
  if (diff <= 3) return { cls: "text-danger font-semibold", text: `${fmtDate(a.deadline)} (${diff}天)` };
  if (diff <= 7) return { cls: "text-warning font-medium", text: `${fmtDate(a.deadline)} (${diff}天)` };
  return { cls: "text-success", text: fmtDate(a.deadline) };
}

function StatusBadge({ status }: { status: string }) {
  const st = STATUS_STYLE[status] || { bg: "#eeeeee", fg: "#616161" };
  return (
    <span
      className="inline-block rounded-full px-2.5 py-0.5 text-xs font-medium"
      style={{ background: st.bg, color: st.fg }}
    >
      {status}
    </span>
  );
}

// ── 页面 ──

export default function JobApplicationsPage() {
  const toast = useToast();
  const [loading, setLoading] = useState(true);
  const [items, setItems] = useState<JobApplication[]>([]);
  const [total, setTotal] = useState(0);
  const [dash, setDash] = useState<JobDashboard | null>(null);

  // 过滤
  const [fStatus, setFStatus] = useState("");
  const [fPriority, setFPriority] = useState("");
  const [fKeyword, setFKeyword] = useState("");
  const [inTrash, setInTrash] = useState(false);

  // 弹窗状态
  const [createOpen, setCreateOpen] = useState(false);
  const [detail, setDetail] = useState<JobApplication | null>(null);
  const [statusTarget, setStatusTarget] = useState<JobApplication | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<JobApplication | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [list, dashboard] = await Promise.all([
        listJobApplications({
          status: fStatus || undefined,
          priority: fPriority || undefined,
          keyword: fKeyword.trim() || undefined,
          deleted: inTrash,
          limit: 100,
        }),
        inTrash ? Promise.resolve(null) : getJobDashboard(),
      ]);
      setItems(list.items);
      setTotal(list.total);
      setDash(dashboard);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, [fStatus, fPriority, fKeyword, inTrash, toast]);

  useEffect(() => {
    void load();
  }, [load]);

  const openDetail = async (id: number) => {
    try {
      setDetail(await getJobApplication(id));
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "加载详情失败");
    }
  };

  const stats = useMemo(() => {
    const s = dash?.stats;
    return s
      ? [
          { label: "总数", value: s.total },
          { label: "进行中", value: s.active },
          { label: "待投递", value: s.to_apply },
          { label: "Offer", value: s.offer },
          { label: "高意向", value: s.high_priority },
        ]
      : [];
  }, [dash]);

  const dl = dash?.deadline_counts;

  return (
    <div className="p-4 sm:p-6 max-w-6xl mx-auto w-full">
      {/* ── 头部 ── */}
      <div className="flex flex-wrap items-center justify-between gap-3 mb-5">
        <div>
          <h1 className="text-xl font-semibold text-[var(--color-text)]">投递看板</h1>
          <p className="text-xs text-[var(--color-text-muted)] mt-0.5">
            投递状态机追踪 · 截止提醒 · 今日队列（致谢/催办/失联）
          </p>
        </div>
        <button
          onClick={() => setCreateOpen(true)}
          className="flex items-center gap-1.5 rounded-full bg-brand text-white text-sm font-medium px-4 py-2 hover:bg-brand-hover active:scale-[0.98] transition-all cursor-pointer"
        >
          <Plus size={16} strokeWidth={2.25} />
          新建投递
        </button>
      </div>

      {/* ── 统计 ── */}
      <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 mb-4">
        {stats.map((s) => (
          <div key={s.label} className="rounded-input border border-[var(--color-border)] bg-[var(--color-card)] p-3.5">
            <p className="text-2xl font-semibold text-[var(--color-text)] tabular-nums">{s.value}</p>
            <p className="text-xs text-[var(--color-text-muted)] mt-0.5">{s.label}</p>
          </div>
        ))}
      </div>

      {/* ── 今日队列 + 截止分布 ── */}
      {!inTrash && dash && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-4">
          {/* 今日队列 */}
          <div className="lg:col-span-2 rounded-input border border-[var(--color-border)] bg-[var(--color-card)] p-4">
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-sm font-semibold text-[var(--color-text)]">
                今日队列
                <span className="ml-2 text-xs font-normal text-[var(--color-text-muted)]">
                  时序规则：致谢 {dash.timing.thankyou_hours}h · 催办 {dash.timing.nudge_days} 天 · 失联 {dash.timing.ghost_days} 天
                </span>
              </h2>
            </div>
            {dash.queue.length === 0 ? (
              <p className="text-sm text-[var(--color-text-muted)] py-4 text-center">
                今天没有需要跟进的事项，保持节奏。
              </p>
            ) : (
              <div className="flex flex-col gap-2">
                {dash.queue.map((q) => {
                  const meta = QUEUE_META[q.kind];
                  const Icon = meta.icon;
                  return (
                    <button
                      key={`${q.kind}-${q.application_id}`}
                      onClick={() => void openDetail(q.application_id)}
                      className="flex items-start gap-3 rounded-list border border-[var(--color-border)] p-3 text-left hover:bg-[var(--color-bg-secondary)] transition-colors cursor-pointer"
                    >
                      <Icon size={18} className={`mt-0.5 shrink-0 ${meta.cls}`} />
                      <div className="min-w-0 flex-1">
                        <p className="text-sm font-medium text-[var(--color-text)]">{q.headline}</p>
                        <p className="text-xs text-[var(--color-text-muted)] mt-0.5">{q.detail}</p>
                      </div>
                      <StatusBadge status={q.status} />
                    </button>
                  );
                })}
              </div>
            )}
          </div>
          {/* 截止分布 */}
          <div className="rounded-input border border-[var(--color-border)] bg-[var(--color-card)] p-4">
            <h2 className="text-sm font-semibold text-[var(--color-text)] mb-3">截止日期分布</h2>
            {dl && (
              <div className="flex flex-col gap-2">
                <DeadlineBar label="过期" count={dl.overdue} cls="text-danger" />
                <DeadlineBar label="≤3 天（红）" count={dl.red} cls="text-danger" />
                <DeadlineBar label="≤7 天（黄）" count={dl.yellow} cls="text-warning" />
                <DeadlineBar label=">7 天（绿）" count={dl.green} cls="text-success" />
                <DeadlineBar label="未设截止" count={dl.none} cls="text-[var(--color-text-muted)]" />
              </div>
            )}
            <p className="text-[11px] text-[var(--color-text-muted)] mt-3">
              红色 ≤3 天、黄色 ≤7 天、绿色 &gt;7 天；停留 &gt;14 天列表内黄色高亮提醒。
            </p>
          </div>
        </div>
      )}

      {/* ── 过滤栏 ── */}
      <div className="flex flex-wrap items-center gap-2 mb-3">
        <select
          value={fStatus}
          onChange={(e) => setFStatus(e.target.value)}
          className="rounded-action border border-[var(--color-border)] bg-[var(--color-card)] px-3 py-1.5 text-sm text-[var(--color-text)] outline-none cursor-pointer"
        >
          <option value="">全部状态</option>
          {APPLICATION_STATUSES.map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
        <select
          value={fPriority}
          onChange={(e) => setFPriority(e.target.value)}
          className="rounded-action border border-[var(--color-border)] bg-[var(--color-card)] px-3 py-1.5 text-sm text-[var(--color-text)] outline-none cursor-pointer"
        >
          <option value="">全部优先级</option>
          {APPLICATION_PRIORITIES.map((p) => (
            <option key={p} value={p}>{p}</option>
          ))}
        </select>
        <div className="relative flex-1 min-w-[180px]">
          <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[var(--color-text-muted)]" />
          <input
            value={fKeyword}
            onChange={(e) => setFKeyword(e.target.value)}
            placeholder="搜索公司 / 岗位 / 备注…"
            className="w-full rounded-action border border-[var(--color-border)] bg-[var(--color-card)] pl-8 pr-3 py-1.5 text-sm text-[var(--color-text)] outline-none focus:border-brand"
          />
        </div>
        <button
          onClick={() => setInTrash((v) => !v)}
          className={`flex items-center gap-1.5 rounded-action px-3 py-1.5 text-sm border transition-colors cursor-pointer ${
            inTrash
              ? "bg-danger-soft text-danger border-danger/30"
              : "border-[var(--color-border)] text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-secondary)]"
          }`}
        >
          <Trash2 size={14} />
          {inTrash ? "垃圾箱（查看中）" : "垃圾箱"}
        </button>
      </div>

      {/* ── 列表 ── */}
      {loading ? (
        <div className="flex justify-center py-16">
          <LoaderCircle size={22} className="animate-spin text-[var(--color-text-muted)]" />
        </div>
      ) : items.length === 0 ? (
        <div className="rounded-input border border-dashed border-[var(--color-border)] py-16 text-center text-sm text-[var(--color-text-muted)]">
          {inTrash ? "垃圾箱为空" : "暂无投递记录，点击右上角「新建投递」开始追踪。"}
        </div>
      ) : (
        <div className="rounded-input border border-[var(--color-border)] overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-[var(--color-text-muted)] bg-[var(--color-bg-secondary)]">
                  <th className="px-4 py-2.5 font-medium">公司 / 岗位</th>
                  <th className="px-3 py-2.5 font-medium">状态</th>
                  <th className="px-3 py-2.5 font-medium">优先级</th>
                  <th className="px-3 py-2.5 font-medium">截止日期</th>
                  <th className="px-3 py-2.5 font-medium">停留</th>
                  <th className="px-3 py-2.5 font-medium">操作</th>
                </tr>
              </thead>
              <tbody>
                {items.map((a) => (
                  <tr
                    key={a.id}
                    className="border-t border-[var(--color-border)] hover:bg-[var(--color-bg-secondary)] transition-colors cursor-pointer"
                    onClick={() => void openDetail(a.id)}
                  >
                    <td className="px-4 py-3">
                      <p className="font-medium text-[var(--color-text)]">{a.company}</p>
                      <p className="text-xs text-[var(--color-text-muted)]">{a.position}</p>
                    </td>
                    <td className="px-3 py-3"><StatusBadge status={a.status} /></td>
                    <td className="px-3 py-3 text-[var(--color-text-secondary)]">
                      <span className="flex items-center gap-1">
                        <Flag size={13} fill="currentColor" className={a.priority === "高" ? "text-danger" : a.priority === "中" ? "text-warning" : "text-[var(--color-text-muted)]"} />
                        {a.priority}
                      </span>
                    </td>
                    <td className={`px-3 py-3 ${deadlineInfo(a).cls}`}>{deadlineInfo(a).text}</td>
                    <td className="px-3 py-3">
                      {a.stay_days != null && a.stay_days > 14 ? (
                        <span className="text-warning font-medium">{a.stay_days} 天 ⚠</span>
                      ) : (
                        <span className="text-[var(--color-text-muted)]">
                          {a.stay_days != null ? `${a.stay_days} 天` : "—"}
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-3">
                      <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
                        {!inTrash && (
                          <button
                            onClick={() => setStatusTarget(a)}
                            disabled={APPLICATION_STATUS_FLOW[a.status]?.length === 0}
                            title={APPLICATION_STATUS_FLOW[a.status]?.length === 0 ? "终态不可流转" : "状态流转"}
                            className="p-1.5 rounded-action text-[var(--color-text-muted)] hover:text-brand hover:bg-brand/10 transition-colors cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
                          >
                            <ArrowRight size={15} />
                          </button>
                        )}
                        <button
                          onClick={() => void openDetail(a.id)}
                          className="p-1.5 rounded-action text-[var(--color-text-muted)] hover:text-brand hover:bg-brand/10 transition-colors cursor-pointer"
                          title="详情"
                        >
                          <Eye size={15} />
                        </button>
                        <button
                          onClick={() => {
                            if (inTrash) {
                              void restoreJobApplication(a.id).then(() => {
                                toast.success("已恢复");
                                void load();
                              }).catch((e) => toast.error(e.message));
                            } else {
                              setDeleteTarget(a);
                            }
                          }}
                          className={`p-1.5 rounded-action transition-colors cursor-pointer ${
                            inTrash
                              ? "text-success hover:bg-success/15"
                              : "text-[var(--color-text-muted)] hover:text-danger hover:bg-danger/10"
                          }`}
                          title={inTrash ? "恢复" : "删除（进垃圾箱）"}
                        >
                          {inTrash ? <CornerUpLeft size={15} /> : <Trash2 size={15} />}
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="px-4 py-2 text-xs text-[var(--color-text-muted)] border-t border-[var(--color-border)]">
            共 {total} 条{inTrash ? "（垃圾箱）" : ""}
          </div>
        </div>
      )}

      {/* ── 新建/编辑弹窗 ── */}
      {createOpen && (
        <ApplicationFormModal
          onClose={() => setCreateOpen(false)}
          onSaved={(dup) => {
            setCreateOpen(false);
            if (dup && dup.length > 0) {
              toast.info(`检测到 ${dup.length} 条近似记录，请在详情中核对是否重复。`);
            }
            toast.success("已保存");
            void load();
          }}
        />
      )}

      {/* ── 状态流转弹窗 ── */}
      {statusTarget && (
        <StatusFlowModal
          app={statusTarget}
          onClose={() => setStatusTarget(null)}
          onDone={() => {
            setStatusTarget(null);
            void load();
          }}
        />
      )}

      {/* ── 详情弹窗 ── */}
      {detail && (
        <ApplicationDetailModal
          app={detail}
          onClose={() => setDetail(null)}
          onChanged={(d) => {
            setDetail(d);
            void load();
          }}
        />
      )}

      {/* ── 删除确认 ── */}
      <ConfirmDialog
        open={deleteTarget !== null}
        title="删除投递记录"
        description={`确定把「${deleteTarget?.company} · ${deleteTarget?.position}」移入垃圾箱吗？可从垃圾箱恢复。`}
        confirmText="移入垃圾箱"
        onConfirm={() => {
          if (deleteTarget) {
            void deleteJobApplication(deleteTarget.id)
              .then(() => {
                toast.success("已移入垃圾箱");
                void load();
              })
              .catch((e) => toast.error(e.message));
          }
          setDeleteTarget(null);
        }}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
}

function DeadlineBar({ label, count, cls }: { label: string; count: number; cls: string }) {
  return (
    <div className="flex items-center justify-between text-sm">
      <span className={`flex items-center gap-1.5 ${cls}`}>
        <span className="inline-block w-2 h-2 rounded-full bg-current" />
        {label}
      </span>
      <span className="text-[var(--color-text)] font-medium tabular-nums">{count}</span>
    </div>
  );
}

// ── 新建/编辑表单弹窗 ──

function ApplicationFormModal({
  initial,
  onClose,
  onSaved,
}: {
  initial?: JobApplication | null;
  onClose: () => void;
  onSaved: (duplicates: Array<{ id: number; company: string; position: string; status: string }>) => void;
}) {
  const toast = useToast();
  const isEdit = Boolean(initial);
  const [saving, setSaving] = useState(false);
  const [company, setCompany] = useState(initial?.company ?? "");
  const [position, setPosition] = useState(initial?.position ?? "");
  const [url, setUrl] = useState(initial?.url ?? "");
  const [priority, setPriority] = useState(initial?.priority ?? "中");
  const [deadline, setDeadline] = useState(initial?.deadline ?? "");
  const [notes, setNotes] = useState(initial?.notes ?? "");
  const [jdText, setJdText] = useState(initial?.jd_text ?? "");
  const [genScorecard, setGenScorecard] = useState(false);

  const submit = async () => {
    if (!company.trim() || !position.trim()) {
      toast.error("请填写公司名与岗位名");
      return;
    }
    setSaving(true);
    try {
      const body = {
        company: company.trim(),
        position: position.trim(),
        url: url.trim() || undefined,
        priority,
        deadline: deadline || undefined,
        notes: notes.trim() || undefined,
        jd_text: jdText.trim() || undefined,
        generate_scorecard: genScorecard && jdText.trim().length > 0,
      };
      if (isEdit && initial) {
        const res = await updateJobApplication(initial.id, body);
        onSaved(res.duplicates);
      } else {
        const res = await createJobApplication(body);
        onSaved(res.duplicates);
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  return (
    <ModalShell title={isEdit ? "编辑投递" : "新建投递"} onClose={onClose}>
      <div className="flex flex-col gap-3.5">
        <div className="grid grid-cols-2 gap-3">
          <Field label="公司名 *">
            <input value={company} onChange={(e) => setCompany(e.target.value)} placeholder="如：腾讯" className={inputCls} />
          </Field>
          <Field label="岗位名 *">
            <input value={position} onChange={(e) => setPosition(e.target.value)} placeholder="如：前端工程师" className={inputCls} />
          </Field>
        </div>
        <Field label="招聘链接 URL">
          <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://…（可粘贴 JD 页面链接）" className={inputCls} />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="优先级">
            <select value={priority} onChange={(e) => setPriority(e.target.value)} className={inputCls}>
              {APPLICATION_PRIORITIES.map((p) => (
                <option key={p} value={p}>{p}</option>
              ))}
            </select>
          </Field>
          <Field label="截止日期">
            <input type="date" value={deadline} onChange={(e) => setDeadline(e.target.value)} className={inputCls} />
          </Field>
        </div>
        <Field label="JD 文本（可选，可生成评分卡）">
          <textarea value={jdText} onChange={(e) => setJdText(e.target.value)} rows={4} placeholder="粘贴岗位 JD…" className={`${inputCls} resize-none`} />
        </Field>
        {jdText.trim() && (
          <label className="flex items-center gap-2 text-sm text-[var(--color-text-secondary)] cursor-pointer">
            <input
              type="checkbox"
              checked={genScorecard}
              onChange={(e) => setGenScorecard(e.target.checked)}
              className="accent-[var(--color-brand)]"
            />
            生成 JD 评分卡（grade A-F / 薪资范围 / 痛点 / 差距）
          </label>
        )}
        <Field label="备注">
          <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={2} placeholder="备注…" className={`${inputCls} resize-none`} />
        </Field>
      </div>
      <div className="flex justify-end gap-2 mt-5">
        <button onClick={onClose} className="px-4 py-2 rounded-action text-sm text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-secondary)] transition-colors cursor-pointer">
          取消
        </button>
        <button
          onClick={() => void submit()}
          disabled={saving}
          className="flex items-center gap-1.5 px-4 py-2 rounded-action bg-brand text-white text-sm font-medium hover:bg-brand-hover transition-colors cursor-pointer disabled:opacity-50"
        >
          {saving && <LoaderCircle size={14} className="animate-spin" />}
          {isEdit ? "保存" : "创建"}
        </button>
      </div>
    </ModalShell>
  );
}

// ── 状态流转弹窗 ──

function StatusFlowModal({
  app,
  onClose,
  onDone,
}: {
  app: JobApplication;
  onClose: () => void;
  onDone: () => void;
}) {
  const toast = useToast();
  const allowed = APPLICATION_STATUS_FLOW[app.status] ?? [];
  const [next, setNext] = useState<ApplicationStatus | "">(allowed[0] ?? "");
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);

  const submit = async () => {
    if (!next) {
      toast.error("请选择目标状态");
      return;
    }
    setSaving(true);
    try {
      await transitionJobApplicationStatus(app.id, { new_status: next as ApplicationStatus, note: note.trim() || undefined });
      toast.success(`已流转：${app.status} → ${next}`);
      onDone();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "流转失败");
    } finally {
      setSaving(false);
    }
  };

  return (
    <ModalShell title={`状态流转 — ${app.company} · ${app.position}`} onClose={onClose}>
      <div className="flex flex-col gap-4">
        <div className="flex items-center gap-2 text-sm">
          <StatusBadge status={app.status} />
          <ArrowRight size={16} className="text-[var(--color-text-muted)]" />
          <span className="text-[var(--color-text-muted)]">→ 下一步</span>
        </div>
        <Field label="目标状态（面试轮次可跳过）">
          <select value={next} onChange={(e) => setNext(e.target.value as ApplicationStatus)} className={inputCls}>
            {allowed.map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        </Field>
        <Field label="流转备注（自动追加到时间线）">
          <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="如：一面通过，约二面" className={inputCls} />
        </Field>
      </div>
      <div className="flex justify-end gap-2 mt-5">
        <button onClick={onClose} className="px-4 py-2 rounded-action text-sm text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-secondary)] transition-colors cursor-pointer">
          取消
        </button>
        <button
          onClick={() => void submit()}
          disabled={saving || !next}
          className="flex items-center gap-1.5 px-4 py-2 rounded-action bg-brand text-white text-sm font-medium hover:bg-brand-hover transition-colors cursor-pointer disabled:opacity-50"
        >
          {saving && <LoaderCircle size={14} className="animate-spin" />}
          确认流转
        </button>
      </div>
    </ModalShell>
  );
}

// ── 详情弹窗 ──

function ApplicationDetailModal({
  app,
  onClose,
  onChanged,
}: {
  app: JobApplication;
  onClose: () => void;
  onChanged: (d: JobApplication) => void;
}) {
  const toast = useToast();
  const dl = deadlineInfo(app);
  const [editOpen, setEditOpen] = useState(false);
  const [archiving, setArchiving] = useState(false);

  const handleArchive = async () => {
    setArchiving(true);
    try {
      await archiveJobApplication(app.id);
      toast.success("已归档到知识库");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "归档失败");
    } finally {
      setArchiving(false);
    }
  };

  return (
    <ModalShell
      title={`${app.company} · ${app.position}`}
      onClose={onClose}
      footer={
        <div className="flex gap-2">
          {!app.deleted_at && (app.jd_text || app.jd_scorecard) && (
            <button
              onClick={() => void handleArchive()}
              disabled={archiving}
              title="把 JD 文本归档为知识资产，Agent 可检索"
              className="flex items-center gap-1.5 px-4 py-2 rounded-action border border-brand/30 text-sm text-brand hover:bg-brand/10 transition-colors cursor-pointer disabled:opacity-50"
            >
              {archiving && <LoaderCircle size={14} className="animate-spin" />}
              归档到知识库
            </button>
          )}
          {!app.deleted_at && (
            <button
              onClick={() => setEditOpen(true)}
              className="flex items-center gap-1.5 px-4 py-2 rounded-action border border-[var(--color-border)] text-sm text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-secondary)] transition-colors cursor-pointer"
            >
              <Luggage size={14} />
              编辑
            </button>
          )}
          {app.deleted_at && (
            <button
              onClick={() => {
                void restoreJobApplication(app.id)
                  .then((d) => {
                    toast.success("已恢复");
                    onChanged(d);
                  })
                  .catch((e) => toast.error(e.message));
              }}
              className="flex items-center gap-1.5 px-4 py-2 rounded-action bg-brand text-white text-sm font-medium transition-colors cursor-pointer"
            >
              <CornerUpLeft size={14} />
              恢复
            </button>
          )}
        </div>
      }
    >
      <div className="flex flex-col gap-4">
        {/* 概览 */}
        <div className="grid grid-cols-2 gap-2 text-sm">
          <InfoRow label="状态"><StatusBadge status={app.status} /></InfoRow>
          <InfoRow label="优先级">
            <span className="text-[var(--color-text)]">{app.priority}</span>
          </InfoRow>
          <InfoRow label="截止日期"><span className={dl.cls}>{dl.text}</span></InfoRow>
          <InfoRow label="停留">
            {app.stay_days != null && app.stay_days > 14 ? (
              <span className="text-warning font-medium">{app.stay_days} 天（&gt;14 天提醒）</span>
            ) : (
              <span className="text-[var(--color-text)]">{app.stay_days != null ? `${app.stay_days} 天` : "—"}</span>
            )}
          </InfoRow>
        </div>
        {app.url && (
          <p className="text-sm">
            <a href={app.url} target="_blank" rel="noopener noreferrer" className="text-brand hover:underline break-all">
              {app.url}
            </a>
          </p>
        )}

        {/* JD 评分卡 */}
        {app.jd_scorecard && (
          <div className="rounded-list border border-[var(--color-border)] bg-[var(--color-bg-secondary)] p-3">
            <p className="text-xs font-medium text-[var(--color-text-muted)] mb-2">JD 评分卡</p>
            <div className="flex items-center gap-3 mb-1.5">
              <span className="text-2xl font-bold text-[var(--color-text)]">Grade {app.jd_scorecard.grade ?? "C"}</span>
              {app.jd_scorecard.comp_min != null && app.jd_scorecard.comp_max != null && (
                <span className="text-sm text-[var(--color-text-secondary)]">
                  {app.jd_scorecard.comp_min}–{app.jd_scorecard.comp_max} 万/年
                </span>
              )}
            </div>
            {app.jd_scorecard.pain_line && (
              <p className="text-sm text-[var(--color-text-secondary)] mb-1">
                <span className="text-[var(--color-text-muted)]">痛点：</span>{app.jd_scorecard.pain_line}
              </p>
            )}
            {app.jd_scorecard.gaps && app.jd_scorecard.gaps.length > 0 && (
              <div className="text-sm text-[var(--color-text-secondary)]">
                <span className="text-[var(--color-text-muted)]">差距：</span>
                {app.jd_scorecard.gaps.join("；")}
              </div>
            )}
          </div>
        )}

        {/* 时间线 */}
        <div>
          <p className="text-xs font-medium text-[var(--color-text-muted)] mb-2">时间线</p>
          <div className="flex flex-col gap-1.5">
            {(app.timeline ?? []).map((t, i) => (
              <div key={i} className="flex items-start gap-2 text-sm">
                <CalendarDays size={14} className="mt-0.5 shrink-0 text-[var(--color-text-muted)]" />
                <div className="min-w-0">
                  <span className="text-xs text-[var(--color-text-muted)]">{fmtDate(t.at)}</span>
                  <span className="mx-1.5 text-[var(--color-text)]">
                    {t.from ? `${t.from} → ` : ""}{t.to}
                  </span>
                  {t.note && <span className="text-[var(--color-text-muted)]">· {t.note}</span>}
                </div>
              </div>
            ))}
          </div>
        </div>

        {app.notes && (
          <div>
            <p className="text-xs font-medium text-[var(--color-text-muted)] mb-1">备注</p>
            <p className="text-sm text-[var(--color-text-secondary)] whitespace-pre-wrap">{app.notes}</p>
          </div>
        )}
      </div>

      {editOpen && (
        <ApplicationFormModal
          initial={app}
          onClose={() => setEditOpen(false)}
          onSaved={(dup) => {
            setEditOpen(false);
            if (dup && dup.length > 0) toast.info(`检测到 ${dup.length} 条近似记录，请核对是否重复。`);
            void getJobApplication(app.id).then(onChanged).catch(() => {});
          }}
        />
      )}
    </ModalShell>
  );
}

// ── 通用小部件 ──

const inputCls =
  "w-full rounded-action border border-[var(--color-border)] bg-[var(--color-bg-secondary)] px-3 py-1.5 text-sm text-[var(--color-text)] outline-none focus:border-brand";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-xs font-medium text-[var(--color-text-muted)]">{label}</span>
      {children}
    </label>
  );
}

function InfoRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-xs text-[var(--color-text-muted)]">{label}</span>
      {children}
    </div>
  );
}

function ModalShell({
  title,
  children,
  onClose,
  footer,
}: {
  title: string;
  children: React.ReactNode;
  onClose: () => void;
  footer?: React.ReactNode;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/45 backdrop-blur-sm p-2 sm:p-4" onClick={onClose}>
      <div
        className="modal-mobile-sheet relative w-full max-w-lg rounded-input border border-[var(--color-border)] bg-[var(--color-surface)] shadow-2xl p-5 max-h-[calc(100dvh-1rem)] sm:max-h-[88vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="sticky top-0 z-10 -mx-5 -mt-5 mb-4 px-5 pt-5 pb-3 flex items-center justify-between bg-[var(--color-surface)]/95 backdrop-blur-sm">
          <h3 className="text-base font-semibold text-[var(--color-text)]">{title}</h3>
          <button onClick={onClose} className="p-1 rounded-action text-[var(--color-text-muted)] hover:bg-[var(--color-bg-secondary)] transition-colors cursor-pointer" aria-label="关闭">
            <X size={16} />
          </button>
        </div>
        {children}
        {footer && <div className="mt-5">{footer}</div>}
      </div>
    </div>
  );
}
