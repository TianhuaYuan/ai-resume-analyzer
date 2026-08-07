import { useEffect, useState, useRef, useCallback, type ChangeEvent } from "react";
import { useNavigate } from "react-router-dom";
import { Upload, FileText, Sparkle, Trash, Plus, Spinner, TrendUp, X, ClipboardText, Copy } from "@phosphor-icons/react";
import { listResumes, uploadResume, deleteResume, copyResume, generateIdempotencyKey, analyzeResume, matchJD, roleScore, type ResumeItem, type AnalyzeResult, type MatchJDResult, type RoleScoreResult } from "../api/resumes";
import { createBuilderResume } from "../api/builder";
import { useToast } from "../components/Toast";
import ConfirmDialog from "../components/ConfirmDialog";
import ScoreCard, { scoreBandKey, BAND_META } from "../components/ScoreCard";
import JDMatchReport from "../components/JDMatchReport";
import { ResumeTemplateView } from "../components/templates";
import { A4PreviewContainer } from "../components/builder/A4PreviewContainer";
import type { ResumeModule, ResumeStyle } from "../api/builder";

// 允许 PDF + DOCX，单文件上限 10MB（与 HomePage / Sidebar 校验一致）
const MAX_FILE_SIZE = 10 * 1024 * 1024;
const ACCEPTED_TYPES = [
  "application/pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
];
const ACCEPTED_EXTS = [".pdf", ".docx"];

function validateFile(file: File): string | null {
  const lowerName = file.name.toLowerCase();
  const extOk = ACCEPTED_EXTS.some((ext) => lowerName.endsWith(ext));
  const typeOk = ACCEPTED_TYPES.includes(file.type);
  if (!extOk && !typeOk) return "仅支持 PDF / DOCX 文件";
  if (file.size > MAX_FILE_SIZE) return "文件大小不能超过 10MB";
  return null;
}

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

/** E3 多角色评分：三角色名映射（peer/lead/HRBP） */
const ROLE_LABELS: Record<string, string> = {
  peer: "同级 Peer",
  lead: "主管 Lead",
  hrbp: "HRBP",
};

function clampScore(v: number): number {
  return Math.max(0, Math.min(100, Number.isFinite(v) ? v : 0));
}

/**
 * E3 多角色评分视图 — peer/lead/HRBP 三角色分数条 + 摘要 + aggregate + 分析文本。
 * 风格与 ScoreCard 保持一致（分数条 + 摘要块 + 解读区）。
 */
function RoleScoreView({ result }: { result: RoleScoreResult }) {
  const agg = result.aggregate;
  const band = scoreBandKey(agg.score ?? 0);
  const meta = BAND_META[band];
  const roles = Object.entries(result.roles ?? {});

  return (
    <div className="space-y-4">
      {/* 总分 + 档位 */}
      <div className="flex items-center gap-5">
        <div className="flex-1 min-w-0">
          <div className={`text-[15px] font-medium ${meta.className}`}>
            {meta.label}
            <span className="text-xs text-[var(--color-text-muted)] ml-2">多角色综合</span>
          </div>
          <p className="text-xs text-[var(--color-text-muted)] mt-1 leading-relaxed">
            同级 / 主管 / HRBP 三角色打分后按权重聚合
          </p>
        </div>
        <span className="text-2xl font-semibold tabular-nums text-[var(--color-text)] shrink-0">
          {Math.round(clampScore(agg.score ?? 0))}
        </span>
      </div>

      {/* 三角色分数条 */}
      <div className="space-y-3">
        {roles.map(([key, item]) => (
          <div key={key} className="flex items-center gap-3">
            <span className="text-xs text-[var(--color-text-secondary)] w-24 shrink-0">
              {ROLE_LABELS[key] ?? key}
            </span>
            <div className="flex-1 h-1.5 rounded-full bg-[var(--color-bg-secondary)] overflow-hidden">
              <div
                className="h-full rounded-full bg-brand/70 transition-all duration-700"
                style={{ width: `${clampScore(item.score)}%` }}
              />
            </div>
            <span className="text-xs font-medium text-[var(--color-text)] w-7 text-right tabular-nums">
              {Math.round(clampScore(item.score))}
            </span>
          </div>
        ))}
      </div>

      {/* 角色摘要 */}
      {roles.length > 0 && (
        <div className="space-y-2">
          {roles.map(([key, item]) => (
            <div key={key} className="rounded-xl bg-[var(--color-bg-secondary)]/60 px-3.5 py-2.5">
              <p className="text-[11px] font-medium text-[var(--color-text-secondary)]">
                {ROLE_LABELS[key] ?? key}
              </p>
              <p className="text-xs text-[var(--color-text-muted)] mt-1 leading-relaxed">
                {item.summary || "（无摘要）"}
              </p>
            </div>
          ))}
        </div>
      )}

      {/* 分析文本 */}
      {result.analysis && (
        <div className="rounded-xl bg-[var(--color-bg-secondary)]/60 px-3.5 py-3 text-xs text-[var(--color-text-secondary)] leading-relaxed whitespace-pre-wrap max-h-48 overflow-y-auto">
          {result.analysis}
        </div>
      )}
    </div>
  );
}

/**
 * 简历卡片缩略预览 — 统一走 A4PreviewContainer。
 */
function ResumeThumbnail({
  modules,
  style,
}: {
  modules: ResumeModule[];
  style: ResumeStyle;
}) {
  return (
    <A4PreviewContainer className="absolute inset-0">
      <ResumeTemplateView modules={modules} style={style} />
    </A4PreviewContainer>
  );
}

/**
 * 简历管理页面 — 集中管理所有简历。
 *
 * 功能：
 * - 标题区：导入现有简历 / 新建简历 / AI 创建简历
 * - 网格卡片列表：缩略图预览 + 文件名 + 更新时间 + 状态指示
 * - 点击卡片导航到 /resumes/:id/edit
 * - hover 显示删除按钮（ConfirmDialog 确认）
 * - WebSocket 事件驱动刷新（分析完成/状态变更）
 */
export default function ResumeManagementPage() {
  const navigate = useNavigate();
  const toast = useToast();

  const [resumes, setResumes] = useState<ResumeItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [creating, setCreating] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<ResumeItem | null>(null);
  const [deleting, setDeleting] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  // A3 评分卡：评分弹窗状态（analyzeResume("score") 消费结构化四维分数）
  const [scoreTarget, setScoreTarget] = useState<ResumeItem | null>(null);
  const [scoreResult, setScoreResult] = useState<AnalyzeResult | null>(null);
  const [scoreLoading, setScoreLoading] = useState(false);
  const [scoreError, setScoreError] = useState<string | null>(null);
  // E3 多角色评分：peer/lead/HRBP 三角色评分（roleScore 消费），评分弹窗内 tab 切换
  const [scoreView, setScoreView] = useState<"single" | "roles">("single");
  const [roleResult, setRoleResult] = useState<RoleScoreResult | null>(null);
  const [roleLoading, setRoleLoading] = useState(false);
  const [roleError, setRoleError] = useState<string | null>(null);
  // JD 匹配弹窗（A3 结构化匹配报告，Magic-Resume FitReport 对照）
  const [jdTarget, setJdTarget] = useState<ResumeItem | null>(null);
  const [jdText, setJdText] = useState("");
  const [jdResult, setJdResult] = useState<MatchJDResult | null>(null);
  const [jdLoading, setJdLoading] = useState(false);
  const [jdError, setJdError] = useState<string | null>(null);

  const handleScore = async (r: ResumeItem) => {
    setScoreTarget(r);
    setScoreResult(null);
    setScoreError(null);
    setScoreLoading(true);
    // E3: 打开弹窗默认综合评分视图，并重置多角色状态
    setScoreView("single");
    setRoleResult(null);
    setRoleError(null);
    try {
      const result = await analyzeResume(r.id, "score");
      setScoreResult(result);
    } catch (e) {
      setScoreError(e instanceof Error ? e.message : "评分失败");
    } finally {
      setScoreLoading(false);
    }
  };

  const handleRoleScore = async (r: ResumeItem) => {
    setScoreView("roles");
    setRoleResult(null);
    setRoleError(null);
    setRoleLoading(true);
    try {
      const result = await roleScore(r.id);
      setRoleResult(result);
    } catch (e) {
      setRoleError(e instanceof Error ? e.message : "多角色评分失败");
    } finally {
      setRoleLoading(false);
    }
  };

  const handleJDMatch = async () => {
    if (!jdTarget || !jdText.trim()) return;
    setJdLoading(true);
    setJdResult(null);
    setJdError(null);
    try {
      const result = await matchJD(jdTarget.id, jdText.trim());
      setJdResult(result);
    } catch (e) {
      setJdError(e instanceof Error ? e.message : "匹配失败");
    } finally {
      setJdLoading(false);
    }
  };

  // 解析进度：resume_id → {stage, percent, message}（WebSocket parse_progress 驱动）
  const [parseProgress, setParseProgress] = useState<Record<number, { stage: string; percent: number; message: string }>>({});

  const fetchResumes = useCallback(async () => {
    try {
      const data = await listResumes(50);
      setResumes(data.items);
      return data.items;
    } catch {
      // 静默失败，不打断用户
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchResumes();
  }, [fetchResumes]);

  // 解析兜底轮询（JobHunter app.js 2s 轮询状态机对照）：
  // 存在解析中的简历时每 3s 刷新列表——WS 断连期间进度/状态也不丢失
  useEffect(() => {
    const hasActive = Object.keys(parseProgress).length > 0;
    if (!hasActive) return;
    const timer = setInterval(() => {
      void fetchResumes().then((items) => {
        if (!items) return;
        // 终态兜底：WS 断连导致 done/failed 事件丢失时，轮询拿到的真实列表里
        // 若该简历已离开 processing（ready/partial/failed），则清理进度项，
        // parseProgress 清空后本轮询 effect 自动停止，避免 3s 轮询永续
        setParseProgress((prev) => {
          const next = { ...prev };
          let changed = false;
          for (const idStr of Object.keys(next)) {
            const id = Number(idStr);
            const item = items.find((r) => r.id === id);
            if (item && item.status !== "processing") {
              delete next[id];
              changed = true;
            }
          }
          return changed ? next : prev;
        });
      });
    }, 3000);
    return () => clearInterval(timer);
  }, [parseProgress, fetchResumes]);

  // 监听分析状态变化 / Builder 保存成功 → 刷新列表
  useEffect(() => {
    const handleRefresh = () => fetchResumes();
    window.addEventListener("resume:analysis-complete", handleRefresh as EventListener);
    window.addEventListener("resume:analysis-failed", handleRefresh as EventListener);
    window.addEventListener("resume:list-refresh", handleRefresh as EventListener);
    return () => {
      window.removeEventListener("resume:analysis-complete", handleRefresh as EventListener);
      window.removeEventListener("resume:analysis-failed", handleRefresh as EventListener);
      window.removeEventListener("resume:list-refresh", handleRefresh as EventListener);
    };
  }, [fetchResumes]);

  // 监听解析进度（parsing → materializing → done），驱动卡片进度条
  useEffect(() => {
    const handleParseProgress = (e: Event) => {
      const detail = (e as CustomEvent).detail as {
        resume_id: number;
        stage: string;
        percent: number;
        message: string;
      } | null;
      if (!detail || !detail.resume_id) return;
      setParseProgress((prev) => ({
        ...prev,
        [detail.resume_id]: {
          stage: detail.stage,
          percent: detail.percent ?? 0,
          message: detail.message ?? "",
        },
      }));
      // 终态（done/failed）短暂显示后刷新列表，进度条让位于真实状态徽章
      if (detail.stage === "done" || detail.stage === "failed") {
        setTimeout(() => {
          setParseProgress((prev) => {
            const next = { ...prev };
            delete next[detail.resume_id];
            return next;
          });
          fetchResumes();
        }, 2000);
      }
    };
    window.addEventListener("resume:parse-progress", handleParseProgress as EventListener);
    return () =>
      window.removeEventListener("resume:parse-progress", handleParseProgress as EventListener);
  }, [fetchResumes]);

  const handleUpload = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    // 清空 input 值允许重复上传同一文件
    e.target.value = "";

    const invalidReason = validateFile(file);
    if (invalidReason) {
      toast.error(invalidReason);
      return;
    }

    setUploading(true);
    try {
      const key = await generateIdempotencyKey(file);
      const result = await uploadResume(file, key);
      // 上传后提醒预计等待时间（解析文本 + AI 生成表单）
      const estimated = result.estimated_seconds ?? 120;
      const waitMin = Math.max(1, Math.ceil(estimated / 60));
      toast.success(`「${result.filename}」上传成功，预计约 ${waitMin} 分钟完成，请稍候...`);
      // 留在管理页，用户可实时看到解析状态变化（processing → ready）
      await fetchResumes();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "上传失败");
    } finally {
      setUploading(false);
    }
  };

  const handleCreate = async () => {
    setCreating(true);
    try {
      const resume = await createBuilderResume({ filename: "未命名简历" });
      toast.success("已创建新简历，开始编辑吧");
      navigate("/qa", { state: { resumeId: resume.id } });
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "创建简历失败");
    } finally {
      setCreating(false);
    }
  };

  const handleAICreate = async () => {
    setCreating(true);
    try {
      const resume = await createBuilderResume({ filename: "未命名简历" });
      toast.success("已创建新简历，AI 助手已就绪");
      // ?ai=true → BuilderPage 可据此自动打开 AI 面板
      navigate("/qa", { state: { resumeId: resume.id } });
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "创建简历失败");
    } finally {
      setCreating(false);
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await deleteResume(deleteTarget.id);
      toast.success("已删除");
      await fetchResumes();
    } catch {
      toast.error("删除失败");
    } finally {
      setDeleting(false);
      setDeleteTarget(null);
    }
  };

  const handleCopy = async (r: ResumeItem) => {
    try {
      await copyResume(r.id);
      toast.success("已复制为草稿副本（可在编辑器中另存语言版本）");
      await fetchResumes();
    } catch {
      toast.error("复制失败");
    }
  };

  // 状态徽章：processing → "解析中"，failed → "解析失败"，draft → "草稿"
  // T17: ready 后按索引新鲜度展示 —— 未建索引 / 索引待重建 / 分块数
  const statusBadge = (r: ResumeItem) => {
    if (r.status === "processing") {
      // 有 WebSocket 进度 → 显示阶段文案 + 进度条；否则退化为静态"解析中"
      const prog = parseProgress[r.id] ?? (r.parse_progress as typeof parseProgress[number] | undefined);
      const percent = prog?.percent ?? 0;
      const label = prog?.message ?? "正在解析...";
      return (
        <div className="inline-flex flex-col gap-1 px-2 py-1 rounded-lg bg-sky-500/15 text-sky-600 border border-sky-500/30 min-w-[96px]">
          <span className="inline-flex items-center gap-1 text-[10px] font-medium">
            <Spinner size={10} className="animate-spin" aria-hidden="true" />
            <span className="truncate">{label}</span>
          </span>
          <div className="h-1 w-full bg-sky-500/15 rounded-full overflow-hidden">
            <div
              className="h-full bg-sky-500 rounded-full transition-all duration-300"
              style={{ width: `${percent}%` }}
            />
          </div>
        </div>
      );
    }
    if (r.status === "failed") {
      return (
        <span className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-medium bg-red-500/15 text-red-500 border border-red-500/30">
          解析失败
        </span>
      );
    }
    if (r.status === "draft") {
      return (
        <span className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-medium bg-amber-500/15 text-amber-600 border border-amber-500/30">
          草稿
        </span>
      );
    }
    if (r.is_indexed === false) {
      return (
        <span
          className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-medium bg-sky-500/15 text-sky-600 border border-sky-500/30"
          title="尚未建立检索索引，首次问答时会自动建立"
        >
          未建索引
        </span>
      );
    }
    if (r.is_stale) {
      return (
        <span
          className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-medium bg-amber-500/15 text-amber-600 border border-amber-500/30"
          title="内容已更新，检索将自动重建"
        >
          索引待重建
        </span>
      );
    }
    return (
      <span className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-medium bg-emerald-500/15 text-emerald-600 border border-emerald-500/30">
        已就绪
      </span>
    );
  };

  // 点击卡片：processing/failed 不跳转（Agent 空档期保持"无简历/无法问答"），仅 ready/draft 可进入
  const handleCardClick = (r: ResumeItem) => {
    if (r.status === "processing") {
      toast.info("简历正在解析中，完成后即可打开，请稍候...");
      return;
    }
    if (r.status === "failed") {
      toast.error("简历解析失败，请删除后重新上传");
      return;
    }
    navigate("/qa", { state: { resumeId: r.id } });
  };

  return (
    <>
      <div className="min-h-screen bg-[var(--color-bg)]">
        <div className="max-w-7xl mx-auto px-6 md:px-8 lg:px-12 py-8">
          {/* ── 标题区 ── */}
          <header className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 mb-8">
            <div>
              <h1 className="text-2xl font-bold text-[var(--color-text)]">简历</h1>
              <p className="text-sm text-[var(--color-text-secondary)] mt-1">
                管理和创建你的专业简历
              </p>
            </div>

            <div className="flex flex-wrap items-center gap-2.5">
              {/* 隐藏文件输入（始终在 DOM 中） */}
              <input
                ref={fileInputRef}
                type="file"
                accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                className="hidden"
                onChange={handleUpload}
              />

              {/* 导入现有简历 */}
              <button
                onClick={() => fileInputRef.current?.click()}
                disabled={uploading || creating}
                className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg
                  text-sm font-medium text-[var(--color-text)]
                  bg-[var(--color-bg-secondary)] hover:bg-[#E5E5EA]
                  active:scale-[0.98] motion-reduce:active:scale-100
                  transition-all cursor-pointer
                  disabled:opacity-50 disabled:cursor-not-allowed"
                aria-label="导入现有简历"
              >
                {uploading ? (
                  <>
                    <Spinner size={14} className="animate-spin" aria-hidden="true" />
                    导入中...
                  </>
                ) : (
                  <>
                    <Upload size={14} weight="bold" aria-hidden="true" />
                    导入现有简历
                  </>
                )}
              </button>

              {/* 新建简历 */}
              <button
                onClick={handleCreate}
                disabled={uploading || creating}
                className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg
                  text-sm font-medium text-[var(--color-text)]
                  bg-[var(--color-bg-secondary)] hover:bg-[#E5E5EA]
                  active:scale-[0.98] motion-reduce:active:scale-100
                  transition-all cursor-pointer
                  disabled:opacity-50 disabled:cursor-not-allowed"
                aria-label="新建简历"
              >
                <Plus size={14} weight="bold" aria-hidden="true" />
                新建简历
              </button>

              {/* AI 创建简历 */}
              <button
                onClick={handleAICreate}
                disabled={uploading || creating}
                className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-full
                  text-sm font-medium text-white
                  bg-brand
                  hover:bg-[#0077ed] hover:scale-[1.02] hover:shadow-lg hover:shadow-brand/25
                  active:scale-[0.98] motion-reduce:active:scale-100
                  transition-all duration-300 cursor-pointer
                  disabled:opacity-50 disabled:cursor-not-allowed"
                aria-label="AI 创建简历"
              >
                {creating ? (
                  <>
                    <Spinner size={14} className="animate-spin" aria-hidden="true" />
                    创建中...
                  </>
                ) : (
                  <>
                    <Sparkle size={14} weight="fill" aria-hidden="true" />
                    AI 创建简历
                  </>
                )}
              </button>
            </div>
          </header>

          {/* ── 简历卡片列表 ── */}
          {loading ? (
            <div className="flex items-center justify-center py-32">
              <Spinner
                size={24}
                className="animate-spin text-[var(--color-text-muted)] mr-2"
                aria-hidden="true"
              />
              <span className="text-sm text-[var(--color-text-secondary)]">加载中...</span>
            </div>
          ) : resumes.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-32 text-center">
              <FileText
                size={48}
                weight="duotone"
                className="text-[var(--color-text-muted)] mb-4"
                aria-hidden="true"
              />
              <p className="text-base text-[var(--color-text-secondary)]">还没有简历</p>
              <p className="text-sm text-[var(--color-text-muted)] mt-1.5">
                点击「导入现有简历」上传文件，或「新建简历」从零开始
              </p>
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-5">
              {resumes.map((r) => (
                <div key={r.id} className="group relative">
                  {/* 卡片（可点击） */}
                  <div
                    onClick={() => handleCardClick(r)}
                    className="cursor-pointer
                      bg-white/80 backdrop-blur-xl border border-[var(--color-border)]
                      rounded-2xl overflow-hidden
                      hover:-translate-y-1 hover:border-brand/40 hover:shadow-xl hover:shadow-black/5
                      transition-all duration-300"
                    role="button"
                    tabIndex={0}
                    aria-label={`编辑 ${r.filename}`}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        handleCardClick(r);
                      }
                    }}
                  >
                    {/* 缩略图预览区 */}
                    <div className="aspect-[3/4] bg-white relative overflow-hidden">
                      {r.modules_data && r.modules_data.modules.length > 0 ? (
                        <>
                          <ResumeThumbnail
                            modules={r.modules_data.modules as ResumeModule[]}
                            style={(r.modules_data.style as unknown as ResumeStyle) ?? ({} as ResumeStyle)}
                          />
                          {/* 底部渐变遮罩 — 暗示下方还有更多内容 */}
                          <div
                            className="absolute bottom-0 left-0 right-0 h-10 pointer-events-none"
                            style={{
                              background: `linear-gradient(to bottom, transparent, white)`,
                            }}
                          />
                        </>
                      ) : (
                        <div className="flex items-center justify-center w-full h-full">
                          <FileText
                            size={40}
                            weight="duotone"
                            className="text-[var(--color-text-muted)] opacity-50"
                            aria-hidden="true"
                          />
                        </div>
                      )}
                      {/* 状态徽章 — 左下角 */}
                      <div className="absolute bottom-2.5 left-2.5 z-10">
                        {statusBadge(r)}
                      </div>
                    </div>

                    {/* 文件信息 */}
                    <div className="p-3.5">
                      <p
                        className="text-sm font-medium text-[var(--color-text)] truncate"
                        title={r.filename}
                      >
                        {r.filename}
                      </p>
                      <p className="text-xs text-[var(--color-text-muted)] mt-1">
                        更新于 {formatTimestamp(r.updated_at)}
                      </p>
                    </div>
                  </div>

                  {/* JD 匹配按钮 — hover 显示（A3 结构化匹配报告入口） */}
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      setJdTarget(r);
                      setJdResult(null);
                      setJdText("");
                      setJdError(null);
                    }}
                    disabled={r.status !== "ready"}
                    className="absolute top-2.5 right-20 z-10 p-1.5 rounded-md
                      bg-[var(--color-bg)]/80 backdrop-blur-sm
                      text-[var(--color-text-muted)]
                      hover:text-violet-400 hover:bg-violet-500/10
                      opacity-0 group-hover:opacity-100 focus:opacity-100
                      disabled:opacity-0 disabled:cursor-not-allowed
                      transition-all cursor-pointer"
                    aria-label={`JD 匹配 ${r.filename}`}
                    title={r.status === "ready" ? "JD 匹配" : "简历未就绪"}
                  >
                    <ClipboardText size={14} weight="bold" aria-hidden="true" />
                  </button>

                  {/* 评分按钮 — hover 显示（A3 评分卡入口，消费 analyzeResume 结构化四维分数） */}
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      void handleScore(r);
                    }}
                    disabled={r.status !== "ready"}
                    className="absolute top-2.5 right-11 z-10 p-1.5 rounded-md
                      bg-[var(--color-bg)]/80 backdrop-blur-sm
                      text-[var(--color-text-muted)]
                      hover:text-sky-400 hover:bg-sky-500/10
                      opacity-0 group-hover:opacity-100 focus:opacity-100
                      disabled:opacity-0 disabled:cursor-not-allowed
                      transition-all cursor-pointer"
                    aria-label={`评分 ${r.filename}`}
                    title={r.status === "ready" ? "AI 评分" : "简历未就绪"}
                  >
                    <TrendUp size={14} weight="bold" aria-hidden="true" />
                  </button>

                  {/* 复制按钮 — hover 显示（多语言版本：复制副本后编辑器中翻译） */}
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      void handleCopy(r);
                    }}
                    className="absolute top-2.5 right-10 z-10 p-1.5 rounded-md
                      bg-[var(--color-bg)]/80 backdrop-blur-sm
                      text-[var(--color-text-muted)]
                      hover:text-brand hover:bg-brand/10
                      opacity-0 group-hover:opacity-100 focus:opacity-100
                      transition-all cursor-pointer"
                    aria-label={`复制 ${r.filename}`}
                    title="复制为草稿副本（可另存语言版本）"
                  >
                    <Copy size={14} weight="bold" aria-hidden="true" />
                  </button>

                  {/* 删除按钮 — hover 显示（与卡片为兄弟元素，避免嵌套 interactive） */}
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      setDeleteTarget(r);
                    }}
                    className="absolute top-2.5 right-2.5 z-10 p-1.5 rounded-md
                      bg-[var(--color-bg)]/80 backdrop-blur-sm
                      text-[var(--color-text-muted)]
                      hover:text-red-400 hover:bg-red-500/10
                      opacity-0 group-hover:opacity-100 focus:opacity-100
                      transition-all cursor-pointer"
                    aria-label={`删除 ${r.filename}`}
                    title="删除"
                  >
                    <Trash size={14} weight="bold" aria-hidden="true" />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* ── 删除确认弹窗 ── */}
      <ConfirmDialog
        open={deleteTarget !== null}
        title="确认删除"
        description={`确定删除「${deleteTarget?.filename ?? ""}」吗？此操作不可撤销。`}
        confirmText="删除"
        danger
        loading={deleting}
        onConfirm={handleDelete}
        onCancel={() => setDeleteTarget(null)}
      />

      {/* ── AI 评分弹窗（A3 评分卡）── */}
      {scoreTarget !== null && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm"
          onClick={() => setScoreTarget(null)}
          role="dialog"
          aria-modal="true"
          aria-label={`${scoreTarget.filename} 评分`}
        >
          <div
            className="w-full max-w-md rounded-2xl bg-[var(--color-bg)] border border-[var(--color-border)] p-5 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between mb-4">
              <div className="min-w-0">
                <h3 className="text-base font-semibold text-[var(--color-text)] truncate">
                  {scoreTarget.filename}
                </h3>
                {/* E3: 综合评分 / 多角色评分 tab 切换 */}
                <div className="mt-1.5 flex items-center gap-1">
                  <button
                    onClick={() => setScoreView("single")}
                    className={`px-2.5 py-1 rounded-full text-xs font-medium transition-colors cursor-pointer ${
                      scoreView === "single"
                        ? "bg-sky-500/15 text-sky-500 border border-sky-500/30"
                        : "text-[var(--color-text-muted)] hover:text-[var(--color-text-secondary)] border border-transparent"
                    }`}
                  >
                    综合评分
                  </button>
                  <button
                    onClick={() => {
                      if (scoreView !== "roles" && !roleResult && scoreTarget) {
                        void handleRoleScore(scoreTarget);
                      } else {
                        setScoreView("roles");
                      }
                    }}
                    className={`px-2.5 py-1 rounded-full text-xs font-medium transition-colors cursor-pointer ${
                      scoreView === "roles"
                        ? "bg-sky-500/15 text-sky-500 border border-sky-500/30"
                        : "text-[var(--color-text-muted)] hover:text-[var(--color-text-secondary)] border border-transparent"
                    }`}
                  >
                    多角色评分
                  </button>
                </div>
              </div>
              <button
                onClick={() => setScoreTarget(null)}
                className="p-1.5 rounded-md text-[var(--color-text-muted)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-secondary)] transition-colors cursor-pointer"
                aria-label="关闭"
              >
                <X size={16} weight="bold" aria-hidden="true" />
              </button>
            </div>

            {scoreView === "single" ? (
              scoreLoading ? (
                <div className="flex items-center justify-center py-16">
                  <Spinner size={22} className="animate-spin text-[var(--color-text-muted)]" aria-hidden="true" />
                  <span className="text-sm text-[var(--color-text-secondary)] ml-2.5">AI 评分中...</span>
                </div>
              ) : scoreError ? (
                <div className="py-8 text-center">
                  <p className="text-sm text-rose-400">{scoreError}</p>
                  <p className="text-xs text-[var(--color-text-muted)] mt-2">请确认简历已完成分析后再试</p>
                </div>
              ) : scoreResult?.scores ? (
                <ScoreCard scores={scoreResult.scores} />
              ) : (
                <div className="py-8 text-center text-sm text-[var(--color-text-secondary)]">
                  暂未获取到评分结果，请稍后重试
                </div>
              )
            ) : roleLoading ? (
              <div className="flex items-center justify-center py-16">
                <Spinner size={22} className="animate-spin text-[var(--color-text-muted)]" aria-hidden="true" />
                <span className="text-sm text-[var(--color-text-secondary)] ml-2.5">多角色评分中...</span>
              </div>
            ) : roleError ? (
              <div className="py-8 text-center">
                <p className="text-sm text-rose-400">{roleError}</p>
                <p className="text-xs text-[var(--color-text-muted)] mt-2">请确认简历已完成分析后再试</p>
              </div>
            ) : roleResult ? (
              <RoleScoreView result={roleResult} />
            ) : (
              <div className="py-8 text-center text-sm text-[var(--color-text-secondary)]">
                暂未获取到多角色评分结果，请稍后重试
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── JD 匹配弹窗（A3 结构化匹配报告）── */}
      {jdTarget !== null && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm"
          onClick={() => setJdTarget(null)}
          role="dialog"
          aria-modal="true"
          aria-label={`${jdTarget.filename} JD 匹配`}
        >
          <div
            className="w-full max-w-lg rounded-2xl bg-[var(--color-bg)] border border-[var(--color-border)] p-5 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between mb-4">
              <div className="min-w-0">
                <h3 className="text-base font-semibold text-[var(--color-text)] truncate">
                  JD 匹配 · {jdTarget.filename}
                </h3>
                <p className="text-xs text-[var(--color-text-muted)] mt-0.5">
                  粘贴目标岗位描述，AI 分析匹配度
                </p>
              </div>
              <button
                onClick={() => setJdTarget(null)}
                className="p-1.5 rounded-md text-[var(--color-text-muted)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-secondary)] transition-colors cursor-pointer"
                aria-label="关闭"
              >
                <X size={16} weight="bold" aria-hidden="true" />
              </button>
            </div>

            {!jdResult && (
              <>
                <textarea
                  value={jdText}
                  onChange={(e) => setJdText(e.target.value)}
                  placeholder="粘贴 JD 文本（如岗位职责、任职要求）..."
                  rows={5}
                  className="w-full px-3 py-2.5 rounded-xl text-sm bg-[var(--color-bg-secondary)] border border-[var(--color-border)] text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] outline-none focus:border-brand/50 focus:ring-4 focus:ring-brand/15 transition-all resize-none"
                />
                <button
                  onClick={() => void handleJDMatch()}
                  disabled={jdLoading || !jdText.trim()}
                  className="mt-3 w-full inline-flex items-center justify-center gap-1.5 px-3.5 py-2 rounded-lg text-sm font-medium text-white bg-brand hover:bg-[#0077ed] active:scale-[0.98] transition-all cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {jdLoading ? (
                    <>
                      <Spinner size={14} className="animate-spin" aria-hidden="true" />
                      匹配分析中...
                    </>
                  ) : (
                    <>
                      <ClipboardText size={14} weight="bold" aria-hidden="true" />
                      开始匹配
                    </>
                  )}
                </button>
                {jdError && (
                  <p className="mt-2.5 text-xs text-rose-400">{jdError}</p>
                )}
              </>
            )}

            {jdResult && (
              <>
                <JDMatchReport
                  result={jdResult}
                  resumeName={jdTarget.filename}
                  jdSnippet={jdText.slice(0, 200)}
                />
                <button
                  onClick={() => {
                    setJdResult(null);
                    setJdText("");
                  }}
                  className="mt-4 w-full px-3.5 py-2 rounded-lg text-sm font-medium text-[var(--color-text)] bg-[var(--color-bg-secondary)] hover:bg-[#E5E5EA] active:scale-[0.98] transition-all cursor-pointer"
                >
                  重新匹配
                </button>
              </>
            )}
          </div>
        </div>
      )}
    </>
  );
}
