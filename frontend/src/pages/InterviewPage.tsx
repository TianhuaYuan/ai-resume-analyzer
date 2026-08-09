/**
 * InterviewPage — 面试记录 + 复盘页（G）。
 *
 * 数据源：/api/v1/interviews（列表/详情/新建/评分卡/删除）
 *         + /api/v1/interviews/review/summary（复盘概览）
 *
 * 功能：
 * - 顶部复盘概览：高频薄弱点 badge、训练推荐卡片、面试次数趋势（简易条状图）
 * - 面试记录列表：公司 / 岗位 / 状态 badge / 备注摘要 / 创建时间；查看详情 + 删除（ConfirmDialog）
 * - 新建面试弹窗：公司、岗位、关联简历（下拉）、JD 文本、问题列表、答案列表、备注
 * - 详情弹窗：问题 / 答案 / 备注 + 「录入评分卡」（JSON textarea + 保存，保存后展示 weak_competencies badge）
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { Plus, LoaderCircle, Trash2, X, Eye, Building2, Luggage, Target, ListChecks, TrendingUp, MessagesSquare, ChevronLeft, ChevronRight } from "lucide-react";
import {
  listInterviews,
  getInterview,
  createInterview,
  updateInterviewScorecard,
  deleteInterview,
  getReviewSummary,
  archiveInterview,
  type InterviewSession,
  type InterviewSummary,
  type InterviewReviewSummary,
  type InterviewScorecard,
} from "../api/interviews";
import { listResumes } from "../api/resumes";
import { listJobApplications } from "../api/jobApplications";
import { useToast } from "../components/Toast";
import ConfirmDialog from "../components/ConfirmDialog";

// ── 常量 ──

const PAGE_SIZE = 10;

/** 趋势条状图最高条对应像素（容器固定高度 = MAX_BAR_PX + 计数/日期行高） */
const MAX_BAR_PX = 72;

/** ISO → "MM-DD HH:mm"（北京时间）。后端 naive datetime 视为 UTC。 */
function formatTimestamp(dateStr?: string): string {
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

/** ISO → "MM-DD"（趋势图横轴标签） */
function formatDay(dateStr?: string): string {
  if (!dateStr) return "-";
  const normalized = /[Z+]/.test(dateStr) ? dateStr : dateStr + "Z";
  const d = new Date(normalized);
  if (isNaN(d.getTime())) return dateStr.slice(0, 10);
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "Asia/Shanghai",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(d);
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? "";
  return `${get("month")}-${get("day")}`;
}

/**
 * 面试状态 badge。status 取值由后端定义（契约未枚举），
 * 已知值映射中文文案，未知值原样降级展示。
 */
const STATUS_META: Record<string, { label: string; className: string }> = {
  completed: {
    label: "已完成",
    className: "bg-success/15 text-success border-success/30",
  },
  pending: {
    label: "待复盘",
    className: "bg-warning/15 text-warning border-warning/30",
  },
  scored: {
    label: "已评分",
    className: "bg-sky-500/15 text-sky-600 border-sky-500/30",
  },
  evaluated: {
    label: "已评分",
    className: "bg-sky-500/15 text-sky-600 border-sky-500/30",
  },
};

function statusBadge(status: string) {
  const meta = STATUS_META[status];
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded text-[10px] font-medium border ${
        meta?.className ??
        "bg-zinc-500/15 text-zinc-500 border-zinc-500/30"
      }`}
    >
      {meta?.label ?? status}
    </span>
  );
}

/** 新建弹窗表单状态 */
interface CreateFormState {
  company: string;
  position: string;
  resume_id: string;
  job_application_id: string;
  jd_text: string;
  questions: string;
  answers: string;
  notes: string;
}

const EMPTY_FORM: CreateFormState = {
  company: "",
  position: "",
  resume_id: "",
  job_application_id: "",
  jd_text: "",
  questions: "",
  answers: "",
  notes: "",
};

/** 输入类 className（与其他页面一致的表单样式） */
const INPUT_CLS =
  "w-full px-3 py-2.5 rounded-list text-sm bg-[var(--color-bg-secondary)] border border-[var(--color-border)] " +
  "text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] outline-none " +
  "focus:border-brand/50 focus:ring-4 focus:ring-brand/15 transition-all";

/** 评分卡分数颜色 */
function scoreColor(score: number): string {
  if (score >= 80) return "bg-success";
  if (score >= 70) return "bg-warning";
  if (score >= 60) return "bg-orange-500";
  return "bg-danger";
}

function scoreLabel(score: number): string {
  if (score >= 80) return "优秀";
  if (score >= 70) return "良好";
  if (score >= 60) return "及格";
  return "待加强";
}

/**
 * ScorecardView — 面试评分卡结构化展示（替代 JSON 原样，普通用户可读）。
 *
 * 支持标准形状：
 *   { overall_score: 72, competency_scores: [{competency, score}], weak_competencies: [...], notes }
 * 兼容简写 { overall: 72, weak: [...], strong: [...] }；未知形状兜底 JSON 折叠展示。
 */
function ScorecardView({ scorecard }: { scorecard: Record<string, unknown> }) {
  const overall =
    (typeof scorecard.overall_score === "number" && scorecard.overall_score) ||
    (typeof scorecard.overall === "number" && (scorecard.overall as number)) ||
    null;
  const competencies = Array.isArray(scorecard.competency_scores)
    ? (scorecard.competency_scores as Record<string, unknown>[])
    : [];
  const weak = Array.isArray(scorecard.weak_competencies)
    ? (scorecard.weak_competencies as string[])
    : Array.isArray(scorecard.weak)
    ? (scorecard.weak as string[])
    : [];
  const notes = typeof scorecard.notes === "string" ? scorecard.notes : "";

  return (
    <div className="rounded-list bg-[var(--color-bg-secondary)]/60 border border-[var(--color-border)] p-4 mb-3 space-y-4">
      {/* 总分 */}
      <div className="flex items-center gap-3">
        {overall !== null && (
          <div
            className={`w-16 h-16 rounded-input ${scoreColor(overall)} text-white flex flex-col items-center justify-center shrink-0`}
          >
            <span className="text-xl font-bold leading-none">{overall}</span>
            <span className="text-[9px] mt-1 opacity-90">总分</span>
          </div>
        )}
        <div className="min-w-0">
          {overall !== null && (
            <div className="text-sm font-medium text-[var(--color-text)]">
              总体评价：{scoreLabel(overall)}
            </div>
          )}
          {weak.length > 0 && (
            <div className="text-xs text-rose-500 mt-0.5">
              待加强维度：{weak.join("、")}
            </div>
          )}
          {competencies.length > 0 && (
            <div className="text-[10px] text-[var(--color-text-muted)] mt-0.5">
              {competencies.length} 个评分维度
            </div>
          )}
        </div>
      </div>

      {/* 各维度进度条 */}
      {competencies.length > 0 && (
        <div className="space-y-2">
          {competencies.map((c, idx) => {
            const name = (c.competency ?? c.name ?? `维度 ${idx + 1}`) as string;
            const score = c.score as number | undefined;
            if (typeof score !== "number") return null;
            return (
              <div key={idx}>
                <div className="flex items-center justify-between text-xs mb-1">
                  <span className="text-[var(--color-text)] truncate pr-2">{name}</span>
                  <span className="text-[var(--color-text-secondary)] shrink-0">{score}</span>
                </div>
                <div className="h-1.5 rounded-full bg-[var(--color-bg-tertiary)] overflow-hidden">
                  <div
                    className={`h-full rounded-full ${scoreColor(score)} transition-all`}
                    style={{ width: `${Math.min(100, Math.max(0, score))}%` }}
                  />
                </div>
              </div>
            );
          })}
        </div>
      )}

      {notes && (
        <p className="text-xs text-[var(--color-text-secondary)] leading-relaxed whitespace-pre-wrap">
          {notes}
        </p>
      )}

      {/* 未知字段兜底（高级用户可展开原始 JSON） */}
      {overall === null && competencies.length === 0 && (
        <details className="text-[11px] text-[var(--color-text-muted)]">
          <summary className="cursor-pointer text-[var(--color-text-secondary)]">查看原始评分数据</summary>
          <pre className="mt-2 whitespace-pre-wrap break-words font-mono max-h-40 overflow-y-auto">
            {JSON.stringify(scorecard, null, 2)}
          </pre>
        </details>
      )}
    </div>
  );
}

/**
 * 面试记录 + 复盘页 — 主组件。
 */
export default function InterviewPage() {
  const toast = useToast();

  // 列表
  const [interviews, setInterviews] = useState<InterviewSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);

  // 复盘概览
  const [review, setReview] = useState<InterviewReviewSummary | null>(null);
  const [reviewLoading, setReviewLoading] = useState(true);

  // 新建弹窗
  const [createOpen, setCreateOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [resumeOptions, setResumeOptions] = useState<
    Array<{ id: number; filename: string }>
  >([]);
  const [jobAppOptions, setJobAppOptions] = useState<
    Array<{ id: number; label: string }>
  >([]);
  const [form, setForm] = useState<CreateFormState>(EMPTY_FORM);

  // 详情弹窗
  const [detailId, setDetailId] = useState<number | null>(null);
  const [detail, setDetail] = useState<InterviewSession | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);

  // 评分卡录入
  const [scorecardText, setScorecardText] = useState("");
  const [scorecardNotes, setScorecardNotes] = useState("");
  const [scorecardSaving, setScorecardSaving] = useState(false);
  const [weakCompetencies, setWeakCompetencies] = useState<string[]>([]);

  // 归档到知识库
  const [archiving, setArchiving] = useState(false);

  // 删除确认
  const [deleteTarget, setDeleteTarget] = useState<InterviewSummary | null>(
    null
  );
  const [deleting, setDeleting] = useState(false);

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  // 趋势图最高值（避免除 0）
  const maxTrend = useMemo(() => {
    if (!review || review.trend.length === 0) return 1;
    return Math.max(...review.trend.map((t) => t.count));
  }, [review]);

  const fetchList = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listInterviews({ page, limit: PAGE_SIZE });
      setInterviews(data.items);
      setTotal(data.total);
    } catch {
      // 静默失败，不打断用户
    } finally {
      setLoading(false);
    }
  }, [page]);

  const fetchReview = useCallback(async () => {
    setReviewLoading(true);
    try {
      const data = await getReviewSummary();
      setReview(data);
    } catch {
      setReview(null);
    } finally {
      setReviewLoading(false);
    }
  }, []);

  const loadResumeOptions = useCallback(async () => {
    try {
      const data = await listResumes(100);
      setResumeOptions(
        data.items.map((r) => ({ id: r.id, filename: r.filename }))
      );
    } catch {
      setResumeOptions([]);
    }
  }, []);

  const loadJobApplicationOptions = useCallback(async () => {
    try {
      const data = await listJobApplications({ limit: 100 });
      setJobAppOptions(
        data.items.map((a) => ({
          id: a.id,
          label: `${a.company} · ${a.position}`,
        }))
      );
    } catch {
      setJobAppOptions([]);
    }
  }, []);

  useEffect(() => {
    void fetchList();
    void fetchReview();
    void loadResumeOptions();
    void loadJobApplicationOptions();
  }, [fetchList, fetchReview, loadResumeOptions, loadJobApplicationOptions]);

  // ── 新建 ──

  const openCreate = () => {
    setForm(EMPTY_FORM);
    setCreateOpen(true);
  };

  const closeCreate = () => {
    if (saving) return;
    setCreateOpen(false);
  };

  const handleCreate = async () => {
    if (!form.company.trim() || !form.position.trim()) {
      toast.error("公司和岗位不能为空");
      return;
    }
    setSaving(true);
    try {
      const questions = form.questions.trim()
        ? form.questions.split("\n").map((s) => s.trim()).filter(Boolean)
        : undefined;
      const answers = form.answers.trim()
        ? form.answers.split("\n").map((s) => s.trim()).filter(Boolean)
        : undefined;
      await createInterview({
        company: form.company.trim(),
        position: form.position.trim(),
        resume_id: form.resume_id ? Number(form.resume_id) : undefined,
        job_application_id: form.job_application_id
          ? Number(form.job_application_id)
          : undefined,
        jd_text: form.jd_text.trim() || undefined,
        questions,
        answers,
        notes: form.notes.trim() || undefined,
      });
      toast.success("面试记录已创建");
      setCreateOpen(false);
      setForm(EMPTY_FORM);
      setPage(1);
      void fetchList();
      void fetchReview();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "创建失败");
    } finally {
      setSaving(false);
    }
  };

  // ── 详情 ──

  const openDetail = async (id: number) => {
    setDetailId(id);
    setDetail(null);
    setDetailError(null);
    setDetailLoading(true);
    setWeakCompetencies([]);
    setScorecardText("");
    setScorecardNotes("");
    try {
      const d = await getInterview(id);
      setDetail(d);
      // 已有评分卡 → 回填 JSON 文本 + 备注，便于二次编辑
      if (d.scorecard) setScorecardText(JSON.stringify(d.scorecard, null, 2));
      setScorecardNotes(d.notes ?? "");
    } catch (e) {
      setDetailError(e instanceof Error ? e.message : "加载详情失败");
    } finally {
      setDetailLoading(false);
    }
  };

  const closeDetail = () => {
    if (scorecardSaving) return;
    setDetailId(null);
    setDetail(null);
    setScorecardText("");
    setScorecardNotes("");
    setWeakCompetencies([]);
  };

  const handleSaveScorecard = async () => {
    if (!detail) return;
    let parsed: unknown;
    try {
      parsed = JSON.parse(scorecardText);
    } catch {
      toast.error("评分卡需为合法 JSON");
      return;
    }
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
      toast.error("评分卡需为 JSON 对象，如 {\"overall\": 80, \"weak\": [\"系统设计\"]}");
      return;
    }
    setScorecardSaving(true);
    try {
      const result = await updateInterviewScorecard(detail.id, {
        scorecard: parsed as InterviewScorecard,
        notes: scorecardNotes.trim() || undefined,
      });
      setWeakCompetencies(result.weak_competencies ?? []);
      setDetail((prev) =>
        prev
          ? {
              ...prev,
              scorecard: result.scorecard,
              notes: result.notes,
              status: result.status,
              updated_at: result.updated_at,
            }
          : prev
      );
      toast.success("评分卡已保存");
      void fetchList();
      void fetchReview();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "保存评分卡失败");
    } finally {
      setScorecardSaving(false);
    }
  };

  // ── 归档到知识库 ──

  const handleArchive = async () => {
    if (!detail) return;
    setArchiving(true);
    try {
      await archiveInterview(detail.id);
      toast.success("已归档到知识库");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "归档失败");
    } finally {
      setArchiving(false);
    }
  };

  // ── 删除 ──

  const handleDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await deleteInterview(deleteTarget.id);
      toast.success("已删除");
      // 当前页删空且非第一页 → 回退一页
      if (interviews.length === 1 && page > 1) setPage(page - 1);
      else void fetchList();
      void fetchReview();
    } catch {
      toast.error("删除失败");
    } finally {
      setDeleting(false);
      setDeleteTarget(null);
    }
  };

  const detailResumeName = detail?.resume_id
    ? resumeOptions.find((r) => r.id === detail.resume_id)?.filename ??
      `简历 #${detail.resume_id}`
    : "-";

  const qaQuestions = detail?.questions ?? [];

  return (
    <>
      <div className="min-h-screen bg-[var(--color-bg)]">
        <div className="max-w-7xl mx-auto px-6 md:px-8 lg:px-12 py-8">
          {/* ── 标题区 ── */}
          <header className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 mb-8">
            <div>
              <h1 className="text-2xl font-bold text-[var(--color-text)]">
                面试复盘
              </h1>
              <p className="text-sm text-[var(--color-text-secondary)] mt-1">
                记录面试过程，沉淀高频薄弱点与针对性训练计划
              </p>
            </div>

            <button
              onClick={openCreate}
              className="inline-flex items-center justify-center gap-1.5 px-3.5 py-2 rounded-full
                text-sm font-medium text-white
                bg-brand
                hover:bg-brand-hover hover:scale-[1.02] hover:shadow-lg hover:shadow-brand/25
                active:scale-[0.98] motion-reduce:active:scale-100
                transition-all duration-300 cursor-pointer"
              aria-label="新建面试记录"
            >
              <Plus size={14} strokeWidth={2.25} aria-hidden="true" />
              新建面试记录
            </button>
          </header>

          {/* ── 复盘概览区 ── */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-8">
            {/* 高频薄弱点 */}
            <div className="glass-card p-5">
              <div className="flex items-center gap-2 mb-4">
                <Target size={16} fill="currentColor" className="text-rose-400" aria-hidden="true" />
                <h2 className="text-sm font-semibold text-[var(--color-text)]">
                  高频薄弱点
                </h2>
              </div>
              {reviewLoading ? (
                <div className="flex items-center gap-2 py-4">
                  <LoaderCircle size={14} className="animate-spin text-[var(--color-text-muted)]" aria-hidden="true" />
                  <span className="text-xs text-[var(--color-text-muted)]">加载中...</span>
                </div>
              ) : !review || review.frequent_weaknesses.length === 0 ? (
                <p className="text-xs text-[var(--color-text-muted)] leading-relaxed">
                  暂无数据，录入评分卡后自动汇总
                </p>
              ) : (
                <div className="flex flex-wrap gap-2">
                  {review.frequent_weaknesses.map((w) => (
                    <span
                      key={w.competency}
                      className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full
                        bg-rose-500/10 border border-rose-500/30 text-xs text-rose-500"
                    >
                      {w.competency}
                      <span className="text-[10px] text-[var(--color-text-muted)] tabular-nums">
                        ×{w.count}
                      </span>
                    </span>
                  ))}
                </div>
              )}
            </div>

            {/* 训练推荐 */}
            <div className="glass-card p-5">
              <div className="flex items-center gap-2 mb-4">
                <ListChecks size={16} fill="currentColor" className="text-sky-400" aria-hidden="true" />
                <h2 className="text-sm font-semibold text-[var(--color-text)]">
                  训练推荐
                </h2>
              </div>
              {reviewLoading ? (
                <div className="flex items-center gap-2 py-4">
                  <LoaderCircle size={14} className="animate-spin text-[var(--color-text-muted)]" aria-hidden="true" />
                  <span className="text-xs text-[var(--color-text-muted)]">加载中...</span>
                </div>
              ) : !review || review.training_plan.modules.length === 0 ? (
                <p className="text-xs text-[var(--color-text-muted)] leading-relaxed">
                  {review?.training_plan.summary || "暂无推荐，基于薄弱点自动生成训练计划"}
                </p>
              ) : (
                <ul className="space-y-2.5">
                  {review.training_plan.modules.slice(0, 4).map((p) => (
                    <li
                      key={p.id + p.title}
                      className="rounded-list border border-[var(--color-border)] bg-[var(--color-bg-secondary)]/60 px-3 py-2.5"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span
                          className="text-xs font-medium text-[var(--color-text)] truncate"
                          title={p.title}
                        >
                          {p.title}
                        </span>
                        <span className="text-[10px] text-[var(--color-text-muted)] whitespace-nowrap tabular-nums">
                          约 {p.est_min} 分钟
                        </span>
                      </div>
                      <p
                        className="text-[10px] text-[var(--color-text-muted)] mt-1 truncate"
                        title={`${p.competency} · ${p.rationale}`}
                      >
                        {p.competency} · {p.rationale}
                      </p>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            {/* 面试次数趋势 */}
            <div className="glass-card p-5">
              <div className="flex items-center gap-2 mb-4">
                <TrendingUp size={16} fill="currentColor" className="text-success" aria-hidden="true" />
                <h2 className="text-sm font-semibold text-[var(--color-text)]">
                  面试次数趋势
                </h2>
              </div>
              {reviewLoading ? (
                <div className="flex items-center gap-2 py-4">
                  <LoaderCircle size={14} className="animate-spin text-[var(--color-text-muted)]" aria-hidden="true" />
                  <span className="text-xs text-[var(--color-text-muted)]">加载中...</span>
                </div>
              ) : !review || review.trend.length === 0 ? (
                <p className="text-xs text-[var(--color-text-muted)] leading-relaxed">
                  暂无趋势，完成更多面试后自动生成
                </p>
              ) : (
                <div className="h-32 flex items-end gap-2">
                  {review.trend.map((t) => {
                    const h =
                      maxTrend > 0
                        ? Math.max(6, Math.round((t.count / maxTrend) * MAX_BAR_PX))
                        : 6;
                    return (
                      <div
                        key={t.period}
                        className="flex-1 min-w-0 h-full flex flex-col items-center justify-end gap-1"
                      >
                        <span className="text-[10px] text-[var(--color-text-muted)] tabular-nums leading-none">
                          {t.count}
                        </span>
                        <div
                          className="w-full max-w-[22px] rounded-md bg-brand/70 hover:bg-brand transition-colors"
                          style={{ height: `${h}px` }}
                          title={`${t.period}：面试 ${t.count} 次`}
                        />
                        <span className="text-[10px] text-[var(--color-text-muted)] truncate max-w-full">
                          {formatDay(t.period)}
                        </span>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </div>

          {/* ── 结果统计 ── */}
          <div className="flex items-center justify-between mb-4">
            <span className="text-xs text-[var(--color-text-muted)] tabular-nums">
              {loading ? "加载中..." : `${total.toLocaleString()} 条面试记录`}
            </span>
          </div>

          {/* ── 面试记录列表 ── */}
          {loading ? (
            <div className="flex items-center justify-center py-32">
              <LoaderCircle
                size={24}
                className="animate-spin text-[var(--color-text-muted)] mr-2"
                aria-hidden="true"
              />
              <span className="text-sm text-[var(--color-text-secondary)]">
                加载中...
              </span>
            </div>
          ) : interviews.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-32 text-center">
              <MessagesSquare
                size={48}
                fill="currentColor"
                className="text-[var(--color-text-muted)] mb-4"
                aria-hidden="true"
              />
              <p className="text-base text-[var(--color-text-secondary)]">
                还没有面试记录
              </p>
              <p className="text-sm text-[var(--color-text-muted)] mt-1.5">
                点击「新建面试记录」，记录公司、岗位与面试问题
              </p>
            </div>
          ) : (
            <div className="flex flex-col gap-4">
              {interviews.map((it) => (
                <div
                  key={it.id}
                  className="group rounded-input bg-white/80 backdrop-blur-xl border border-[var(--color-border)]
                    p-4 hover:border-brand/40 hover:shadow-lg hover:shadow-black/5
                    transition-all duration-300"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-x-2 gap-y-1.5">
                        <span className="inline-flex items-center gap-1 text-sm font-semibold text-[var(--color-text)] truncate max-w-[180px]">
                          <Building2
                            size={14}
                            fill="currentColor"
                            className="text-brand shrink-0"
                            aria-hidden="true"
                          />
                          <span className="truncate" title={it.company}>
                            {it.company}
                          </span>
                        </span>
                        <span className="inline-flex items-center gap-1 text-xs text-[var(--color-text-secondary)] truncate max-w-[160px]">
                          <Luggage
                            size={12}
                            fill="currentColor"
                            className="text-sky-500 shrink-0"
                            aria-hidden="true"
                          />
                          <span className="truncate" title={it.position}>
                            {it.position}
                          </span>
                        </span>
                        {statusBadge(it.status)}
                        {it.weak_count !== undefined && it.weak_count > 0 && (
                          <span
                            className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-medium
                              bg-rose-500/10 text-rose-500 border border-rose-500/30"
                            title={`${it.weak_count} 个薄弱维度`}
                          >
                            {it.weak_count} 个薄弱点
                          </span>
                        )}
                      </div>
                      {it.notes && (
                        <p className="text-xs text-[var(--color-text-secondary)] mt-1.5 line-clamp-2 leading-relaxed break-words">
                          {it.notes}
                        </p>
                      )}
                    </div>

                    {/* 行操作 */}
                    <div className="flex items-center gap-1 shrink-0">
                      <button
                        onClick={() => void openDetail(it.id)}
                        className="p-1.5 rounded-md text-[var(--color-text-muted)] hover:text-sky-400 hover:bg-sky-500/10 transition-all cursor-pointer"
                        aria-label={`查看 ${it.company} ${it.position} 详情`}
                        title="查看详情"
                      >
                        <Eye size={14} strokeWidth={2.25} aria-hidden="true" />
                      </button>
                      <button
                        onClick={() => setDeleteTarget(it)}
                        className="p-1.5 rounded-md text-[var(--color-text-muted)] hover:text-danger hover:bg-danger/10 transition-all cursor-pointer"
                        aria-label={`删除 ${it.company} ${it.position}`}
                        title="删除"
                      >
                        <Trash2 size={14} strokeWidth={2.25} aria-hidden="true" />
                      </button>
                    </div>
                  </div>

                  {/* 元信息 */}
                  <div className="flex flex-wrap items-center gap-3 mt-3 pt-3 border-t border-[var(--color-border)]">
                    <span className="text-[10px] text-[var(--color-text-muted)]">
                      创建于 {formatTimestamp(it.created_at)}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* ── 分页 ── */}
          {!loading && totalPages > 1 && (
            <div className="flex items-center justify-between mt-6">
              <span className="text-xs text-[var(--color-text-muted)]">
                第 {page}/{totalPages} 页，共 {total.toLocaleString()} 条
              </span>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page <= 1}
                  className="p-2 rounded-full bg-[var(--color-bg-secondary)] text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-secondary)] disabled:opacity-30 disabled:cursor-not-allowed transition-all cursor-pointer"
                  aria-label="上一页"
                >
                  <ChevronLeft size={14} strokeWidth={2.25} aria-hidden="true" />
                </button>
                {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
                  const start = Math.max(
                    1,
                    Math.min(page - 2, totalPages - 4)
                  );
                  const p = start + i;
                  if (p > totalPages) return null;
                  return (
                    <button
                      key={p}
                      onClick={() => setPage(p)}
                      className={`w-8 h-8 rounded-full text-xs font-medium transition-all cursor-pointer
                        ${p === page
                          ? "bg-brand/10 text-brand border border-brand/30"
                          : "bg-[var(--color-bg-secondary)] text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-secondary)]"
                        }`}
                      aria-label={`第 ${p} 页`}
                    >
                      {p}
                    </button>
                  );
                })}
                <button
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  disabled={page >= totalPages}
                  className="p-2 rounded-full bg-[var(--color-bg-secondary)] text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-secondary)] disabled:opacity-30 disabled:cursor-not-allowed transition-all cursor-pointer"
                  aria-label="下一页"
                >
                  <ChevronRight size={14} strokeWidth={2.25} aria-hidden="true" />
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ── 新建面试弹窗 ── */}
      {createOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm"
          onClick={closeCreate}
          role="dialog"
          aria-modal="true"
          aria-label="新建面试记录"
        >
          <div
            className="w-full max-w-xl rounded-input bg-[var(--color-bg)] border border-[var(--color-border)] p-5 shadow-2xl max-h-[88vh] overflow-y-auto"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between mb-5">
              <div className="min-w-0">
                <h3 className="text-base font-semibold text-[var(--color-text)]">
                  新建面试记录
                </h3>
                <p className="text-xs text-[var(--color-text-muted)] mt-0.5">
                  记录一次面试的公司、岗位与问答，便于事后复盘
                </p>
              </div>
              <button
                onClick={closeCreate}
                disabled={saving}
                className="p-1.5 rounded-md text-[var(--color-text-muted)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-secondary)] transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                aria-label="关闭"
              >
                <X size={16} strokeWidth={2.25} aria-hidden="true" />
              </button>
            </div>

            {/* 公司 / 岗位 */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-4">
              <div>
                <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">
                  公司 <span className="text-rose-400">*</span>
                </label>
                <input
                  type="text"
                  value={form.company}
                  onChange={(e) => setForm((f) => ({ ...f, company: e.target.value }))}
                  placeholder="如：字节跳动"
                  className={INPUT_CLS}
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">
                  岗位 <span className="text-rose-400">*</span>
                </label>
                <input
                  type="text"
                  value={form.position}
                  onChange={(e) => setForm((f) => ({ ...f, position: e.target.value }))}
                  placeholder="如：后端开发工程师"
                  className={INPUT_CLS}
                />
              </div>
            </div>

            {/* 关联简历 */}
            <div className="mb-4">
              <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">
                关联简历（可选）
              </label>
              <select
                value={form.resume_id}
                onChange={(e) => setForm((f) => ({ ...f, resume_id: e.target.value }))}
                className={`${INPUT_CLS} cursor-pointer`}
              >
                <option value="">不关联简历</option>
                {resumeOptions.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.filename}
                  </option>
                ))}
              </select>
            </div>

            {/* 关联投递 */}
            <div className="mb-4">
              <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">
                关联投递（可选）
              </label>
              <select
                value={form.job_application_id}
                onChange={(e) =>
                  setForm((f) => ({ ...f, job_application_id: e.target.value }))
                }
                className={`${INPUT_CLS} cursor-pointer`}
              >
                <option value="">不关联投递</option>
                {jobAppOptions.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.label}
                  </option>
                ))}
              </select>
              <p className="text-[10px] text-[var(--color-text-muted)] mt-1">
                关联后未填 JD 时自动带出该投递的 JD 文本
              </p>
            </div>

            {/* JD 文本 */}
            <div className="mb-4">
              <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">
                JD 文本（可选）
              </label>
              <textarea
                value={form.jd_text}
                onChange={(e) => setForm((f) => ({ ...f, jd_text: e.target.value }))}
                placeholder="粘贴岗位描述（职责、任职要求）..."
                rows={3}
                className={`${INPUT_CLS} resize-none`}
              />
            </div>

            {/* 问题 / 答案 */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-4">
              <div>
                <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">
                  问题列表（每行一个）
                </label>
                <textarea
                  value={form.questions}
                  onChange={(e) => setForm((f) => ({ ...f, questions: e.target.value }))}
                  placeholder={"自我介绍\n讲讲项目难点\n..."}
                  rows={5}
                  className={`${INPUT_CLS} resize-none`}
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">
                  答案列表（每行一个，与问题顺序对应）
                </label>
                <textarea
                  value={form.answers}
                  onChange={(e) => setForm((f) => ({ ...f, answers: e.target.value }))}
                  placeholder={"针对自我介绍的回答\n针对项目难点的回答\n..."}
                  rows={5}
                  className={`${INPUT_CLS} resize-none`}
                />
              </div>
            </div>

            {/* 备注 */}
            <div className="mb-5">
              <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">
                备注（可选）
              </label>
              <textarea
                value={form.notes}
                onChange={(e) => setForm((f) => ({ ...f, notes: e.target.value }))}
                placeholder="面试感受、复盘要点、结果进展..."
                rows={3}
                className={`${INPUT_CLS} resize-none`}
              />
            </div>

            <div className="flex items-center justify-end gap-2">
              <button
                onClick={closeCreate}
                disabled={saving}
                className="px-3.5 py-2 rounded-action text-sm font-medium text-[var(--color-text-secondary)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-secondary)] active:scale-[0.98] transition-all cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
              >
                取消
              </button>
              <button
                onClick={() => void handleCreate()}
                disabled={saving}
                className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-action text-sm font-medium text-white bg-brand hover:bg-brand-hover active:scale-[0.98] transition-all cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {saving && (
                  <LoaderCircle size={14} className="animate-spin" aria-hidden="true" />
                )}
                保存
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── 详情弹窗 ── */}
      {detailId !== null && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm"
          onClick={closeDetail}
          role="dialog"
          aria-modal="true"
          aria-label="面试详情"
        >
          <div
            className="w-full max-w-2xl rounded-input bg-[var(--color-bg)] border border-[var(--color-border)] p-5 shadow-2xl max-h-[88vh] overflow-y-auto"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-start justify-between gap-3 mb-4">
              <div className="min-w-0">
                <h3 className="text-base font-semibold text-[var(--color-text)] truncate">
                  {detail
                    ? `${detail.company} · ${detail.position}`
                    : "面试详情"}
                </h3>
                <div className="flex flex-wrap items-center gap-2 mt-1.5">
                  {detail ? statusBadge(detail.status) : null}
                  <span className="text-[10px] text-[var(--color-text-muted)]">
                    创建于 {formatTimestamp(detail?.created_at)}
                  </span>
                </div>
              </div>
              <button
                onClick={closeDetail}
                disabled={scorecardSaving}
                className="p-1.5 rounded-md text-[var(--color-text-muted)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-secondary)] transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                aria-label="关闭"
              >
                <X size={16} strokeWidth={2.25} aria-hidden="true" />
              </button>
            </div>

            {detailLoading ? (
              <div className="flex items-center justify-center py-16">
                <LoaderCircle
                  size={22}
                  className="animate-spin text-[var(--color-text-muted)]"
                  aria-hidden="true"
                />
                <span className="text-sm text-[var(--color-text-secondary)] ml-2.5">
                  加载详情中...
                </span>
              </div>
            ) : detailError ? (
              <div className="py-8 text-center">
                <p className="text-sm text-rose-400">{detailError}</p>
              </div>
            ) : detail ? (
              <>
                {/* 关联信息 */}
                <div className="flex flex-wrap items-center gap-x-4 gap-y-1 mb-4 text-xs text-[var(--color-text-secondary)]">
                  <span>
                    关联简历：
                    <span className="text-[var(--color-text-muted)]">
                      {detailResumeName}
                    </span>
                  </span>
                  <span>
                    关联投递：
                    <span className="text-[var(--color-text-muted)]">
                      {detail.job_application_id
                        ? jobAppOptions.find(
                            (a) => a.id === detail.job_application_id
                          )?.label ?? `投递 #${detail.job_application_id}`
                        : "未关联"}
                    </span>
                  </span>
                  <span>
                    更新时间：
                    <span className="text-[var(--color-text-muted)]">
                      {formatTimestamp(detail.updated_at)}
                    </span>
                  </span>
                </div>

                {/* 归档到知识库 */}
                <div className="flex items-center justify-between gap-3 mb-4 rounded-list border border-[var(--color-border)] bg-[var(--color-bg-secondary)]/60 px-3 py-2.5">
                  <span className="text-xs text-[var(--color-text-muted)]">
                    归档后进入知识库，Agent 可检索到本次复盘
                  </span>
                  <button
                    onClick={() => void handleArchive()}
                    disabled={archiving}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-action text-xs font-medium
                      text-brand border border-brand/30 hover:bg-brand/10 active:scale-[0.98]
                      transition-all cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed shrink-0"
                  >
                    {archiving && (
                      <LoaderCircle size={12} className="animate-spin" aria-hidden="true" />
                    )}
                    归档到知识库
                  </button>
                </div>

                {/* 问题 / 答案 */}
                {qaQuestions.length > 0 && (
                  <div className="mb-4">
                    <h4 className="text-xs font-medium text-[var(--color-text-secondary)] mb-2">
                      面试问题
                    </h4>
                    <ol className="space-y-2.5">
                      {qaQuestions.map((q, i) => (
                        <li
                          key={i}
                          className="rounded-list border border-[var(--color-border)] bg-[var(--color-bg-secondary)]/60 px-3 py-2.5"
                        >
                          <p className="text-sm text-[var(--color-text)] break-words">
                            <span className="font-medium text-brand mr-1.5">
                              {i + 1}.
                            </span>
                            {q}
                          </p>
                          {detail.answers?.[i] && (
                            <p className="text-xs text-[var(--color-text-secondary)] mt-1.5 leading-relaxed break-words whitespace-pre-wrap">
                              {detail.answers[i]}
                            </p>
                          )}
                        </li>
                      ))}
                    </ol>
                  </div>
                )}

                {/* JD 文本 */}
                {detail.jd_text && (
                  <div className="mb-4">
                    <h4 className="text-xs font-medium text-[var(--color-text-secondary)] mb-2">
                      JD 文本
                    </h4>
                    <pre className="whitespace-pre-wrap break-words text-xs text-[var(--color-text-secondary)] leading-relaxed bg-[var(--color-bg-secondary)]/60 rounded-list px-3 py-2.5 max-h-40 overflow-y-auto font-sans">
                      {detail.jd_text}
                    </pre>
                  </div>
                )}

                {/* 备注 */}
                {detail.notes && (
                  <div className="mb-4">
                    <h4 className="text-xs font-medium text-[var(--color-text-secondary)] mb-2">
                      备注
                    </h4>
                    <p className="text-xs text-[var(--color-text-secondary)] leading-relaxed break-words whitespace-pre-wrap bg-[var(--color-bg-secondary)]/60 rounded-list px-3 py-2.5">
                      {detail.notes}
                    </p>
                  </div>
                )}

                {/* 评分卡 */}
                <div className="mb-4">
                  <div className="flex items-center justify-between mb-2">
                    <h4 className="text-xs font-medium text-[var(--color-text-secondary)]">
                      评分卡
                    </h4>
                    {weakCompetencies.length > 0 && (
                      <span className="text-[10px] text-[var(--color-text-muted)]">
                        已保存，{weakCompetencies.length} 个薄弱维度
                      </span>
                    )}
                  </div>

                  {/* weak_competencies badge */}
                  {weakCompetencies.length > 0 && (
                    <div className="flex flex-wrap gap-1.5 mb-2">
                      {weakCompetencies.map((w) => (
                        <span
                          key={w}
                          className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-medium
                            bg-rose-500/10 text-rose-500 border border-rose-500/30"
                        >
                          {w}
                        </span>
                      ))}
                    </div>
                  )}

                  {/* 已有评分卡：结构化视图（普通用户可读，非 JSON 原样） */}
                  {detail.scorecard && (
                    <ScorecardView scorecard={detail.scorecard} />
                  )}

                  {/* 录入评分卡 */}
                  <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">
                    录入 / 更新评分卡（JSON 对象）
                  </label>
                  <textarea
                    value={scorecardText}
                    onChange={(e) => setScorecardText(e.target.value)}
                    placeholder='{"overall": 80, "weak": ["系统设计"], "strong": ["算法基础"]}'
                    rows={4}
                    className={`${INPUT_CLS} resize-none font-mono text-xs`}
                  />
                  <input
                    type="text"
                    value={scorecardNotes}
                    onChange={(e) => setScorecardNotes(e.target.value)}
                    placeholder="评分备注（可选，会同步更新面试备注）"
                    className={`${INPUT_CLS} mt-2`}
                  />
                  <button
                    onClick={() => void handleSaveScorecard()}
                    disabled={scorecardSaving}
                    className="mt-3 inline-flex items-center gap-1.5 px-3.5 py-2 rounded-action text-sm font-medium
                      text-white bg-brand hover:bg-brand-hover active:scale-[0.98]
                      transition-all cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {scorecardSaving && (
                      <LoaderCircle size={14} className="animate-spin" aria-hidden="true" />
                    )}
                    保存评分卡
                  </button>
                </div>
              </>
            ) : null}
          </div>
        </div>
      )}

      {/* ── 删除确认弹窗 ── */}
      <ConfirmDialog
        open={deleteTarget !== null}
        title="确认删除"
        description={`确定删除「${deleteTarget?.company ?? ""} · ${deleteTarget?.position ?? ""}」这条面试记录吗？此操作不可撤销。`}
        confirmText="删除"
        danger
        loading={deleting}
        onConfirm={() => void handleDelete()}
        onCancel={() => setDeleteTarget(null)}
      />
    </>
  );
}
