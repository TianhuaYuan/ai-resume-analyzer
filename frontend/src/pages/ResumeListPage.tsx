import { useEffect, useState, useRef } from "react";
import { Link } from "react-router-dom";
import { Sparkle, ListBullets, FileText, Target, ArrowClockwise, CheckSquare, TrashSimple, X } from "@phosphor-icons/react";
import {
  listResumes,
  uploadResume,
  deleteResume,
  getResume,
  retryResume,
  generateIdempotencyKey,
  type ResumeItem,
} from "../api/resumes";
import AnalysisModal from "../components/AnalysisModal";
import ChunksModal from "../components/ChunksModal";
import ResumeViewer from "../components/ResumeViewer";
import MatchJDModal from "../components/MatchJDModal";
import MoreMenu from "../components/MoreMenu";
import ConfirmDialog from "../components/ConfirmDialog";
import { useToast } from "../components/Toast";

// ── 骨架屏 ──────────────────────────────────────────────

function SkeletonCard() {
  return (
    <div className="bg-white/4 border border-white/8 rounded-2xl p-5">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3 flex-1">
          <div className="w-8 h-8 rounded-lg animate-skeleton" />
          <div className="flex-1 space-y-2">
            <div className="h-4 w-48 rounded animate-skeleton" />
            <div className="h-3 w-32 rounded animate-skeleton" />
          </div>
        </div>
        <div className="h-6 w-16 rounded-full animate-skeleton" />
      </div>
    </div>
  );
}

function SkeletonList() {
  return (
    <div className="space-y-3">
      {[0, 1, 2].map((i) => (
        <SkeletonCard key={i} />
      ))}
    </div>
  );
}

// ── 状态 Badge ──────────────────────────────────────────

function StatusBadge({ status }: { status: string }) {
  if (status === "processing") {
    return (
      <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium
        bg-amber-500/12 border border-amber-500/20 text-amber-400">
        <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-progress-pulse" />
        处理中
      </span>
    );
  }
  if (status === "failed") {
    return (
      <span className="inline-flex items-center px-3 py-1 rounded-full text-xs font-medium
        bg-red-500/12 border border-red-500/20 text-red-400">
        失败
      </span>
    );
  }
  return (
    <span className="inline-flex items-center px-3 py-1 rounded-full text-xs font-medium
      bg-emerald-500/12 border border-emerald-500/20 text-emerald-400">
      就绪
    </span>
  );
}

function FileIcon({ status }: { status: string }) {
  const bg =
    status === "failed"
      ? "bg-red-500/12"
      : status === "processing"
      ? "bg-amber-500/12"
      : "bg-indigo-500/12";
  const emoji = status === "failed" ? "⚠️" : status === "processing" ? "⏳" : "📄";

  return (
    <div className={`w-9 h-9 rounded-lg flex items-center justify-center text-base ${bg}`}>
      {emoji}
    </div>
  );
}

// ── 空状态 ──────────────────────────────────────────────

function EmptyState({ onUpload }: { onUpload: () => void }) {
  return (
    <div className="text-center py-20">
      <div className="w-20 h-20 mx-auto mb-6 rounded-2xl bg-indigo-500/10 border border-indigo-500/15
        flex items-center justify-center text-4xl">
        📋
      </div>
      <h3 className="text-lg font-medium text-[var(--color-text)] mb-2">还没有简历</h3>
      <p className="text-sm text-[var(--color-text-muted)] mb-6">上传你的第一份简历，开始 AI 智能分析</p>
      <button
        onClick={onUpload}
        className="px-5 py-2.5 rounded-xl text-sm font-semibold text-white
          bg-linear-to-r from-indigo-500 to-purple-600
          hover:brightness-110 hover:shadow-lg hover:shadow-indigo-500/25
          active:scale-[0.98] transition-all duration-200 cursor-pointer"
      >
        上传简历
      </button>
    </div>
  );
}

// ── 主组件 ──────────────────────────────────────────────

export default function ResumeListPage() {
  const [resumes, setResumes] = useState<ResumeItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [newCardId, setNewCardId] = useState<number | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<ResumeItem | null>(null);
  const [analyzeTarget, setAnalyzeTarget] = useState<ResumeItem | null>(null);
  const [chunksTarget, setChunksTarget] = useState<ResumeItem | null>(null);
  const [viewerTarget, setViewerTarget] = useState<ResumeItem | null>(null);
  const [jdMatchTarget, setJdMatchTarget] = useState<ResumeItem | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  // Task 1.3: 正在重试中的简历 id 集合，用于禁用按钮防止重复点击
  const [retryingIds, setRetryingIds] = useState<Set<number>>(new Set());
  // Task 2.6: 上传幂等键 + 上次失败的 file，用于"重试上传"复用同 key
  const lastUploadKeyRef = useRef<string | null>(null);
  const lastFileRef = useRef<File | null>(null);
  const [uploadFailed, setUploadFailed] = useState(false);
  // Task 5.5: 批量操作
  const [selectMode, setSelectMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [batchDeleteOpen, setBatchDeleteOpen] = useState(false);
  const [batchDeleting, setBatchDeleting] = useState(false);
  const toast = useToast();

  const fetchResumes = async () => {
    setLoading(true);
    try {
      const data = await listResumes();
      setResumes(data.items);
      setTotal(data.total);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "加载失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchResumes();
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  const startPoll = (resumeId: number) => {
    // H8：先清掉可能还在跑的旧轮询。否则连续上传多份简历时，
    // 上一份还在 processing 的轮询会被直接覆盖且不清除 → 定时器泄漏、状态永不更新。
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    let attempts = 0;
    pollRef.current = setInterval(async () => {
      attempts++;
      try {
        const r = await getResume(resumeId);
        if (r.status === "ready") {
          clearInterval(pollRef.current!);
          pollRef.current = null;
          setResumes((prev) =>
            prev.map((item) => (item.id === resumeId ? r : item))
          );
          return;
        }
        if (r.status === "failed" || attempts > 30) {
          clearInterval(pollRef.current!);
          pollRef.current = null;
          setResumes((prev) =>
            prev.map((item) =>
              item.id === resumeId
                ? { ...item, status: r.status, status_message: r.status_message }
                : item
            )
          );
          if (r.status === "failed")
            setError(`处理失败：${r.status_message || "未知错误"}`);
          return;
        }
        setResumes((prev) =>
          prev.map((item) =>
            item.id === resumeId ? { ...item, status: r.status } : item
          )
        );
      } catch {
        clearInterval(pollRef.current!);
        pollRef.current = null;
      }
    }, 1500);
  };

  const triggerUpload = () => fileInputRef.current?.click();

  // P0.4 + P2-13 + P3-4: 统一类型/大小校验，按钮与拖拽入口行为一致
  // 允许 PDF + DOCX，单文件上限 10MB
  const MAX_FILE_SIZE = 10 * 1024 * 1024;
  const ACCEPTED_TYPES = ["application/pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"];
  const ACCEPTED_EXTS = [".pdf", ".docx"];

  function validateFile(file: File): string | null {
    const lowerName = file.name.toLowerCase();
    const extOk = ACCEPTED_EXTS.some((ext) => lowerName.endsWith(ext));
    const typeOk = ACCEPTED_TYPES.includes(file.type);
    if (!extOk && !typeOk) return "仅支持 PDF / DOCX 文件";
    if (file.size > MAX_FILE_SIZE) return "文件大小不能超过 10MB";
    return null;
  }

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []);
    if (files.length === 0) return;

    // 清空 input 值允许重复上传同一文件
    if (fileInputRef.current) fileInputRef.current.value = "";

    if (files.length === 1) {
      // 单文件：保持原有逻辑
      const invalidReason = validateFile(files[0]);
      if (invalidReason) {
        setError(invalidReason);
        return;
      }
      await doUpload(files[0]);
      return;
    }

    // Task 5.5: 多文件批量上传
    setUploading(true);
    setError("");
    let successCount = 0;
    let failCount = 0;

    for (const file of files) {
      const invalidReason = validateFile(file);
      if (invalidReason) {
        failCount++;
        continue;
      }
      try {
        const key = await generateIdempotencyKey(file);
        const result = await uploadResume(file, key);
        setNewCardId(result.id);
        setResumes((prev) => [
          {
            id: result.id,
            filename: result.filename,
            parsed_text: "",
            chunk_count: 0,
            status: result.status,
            status_message: "解析中...",
            created_at: new Date().toISOString(),
          },
          ...prev,
        ]);
        startPoll(result.id);
        successCount++;
      } catch {
        failCount++;
      }
    }

    setUploading(false);
    if (failCount > 0) {
      setError(`${failCount} 个文件上传失败`);
      setUploadFailed(true);
    }
    if (successCount > 0) {
      toast.success(`成功上传 ${successCount} 份简历`);
    }
  };

  // Task 2.6: 实际执行上传，先算 key 保存到 ref，再调 uploadResume(file, key)
  // 重试场景调用 doUpload(lastFile, lastUploadKey) 复用同 key
  const doUpload = async (file: File, overrideKey?: string) => {
    setError("");
    setUploadFailed(false);
    setUploading(true);

    try {
      // 首次上传：算 key 并保存；重试：复用上次 key
      const key = overrideKey ?? (await generateIdempotencyKey(file));
      lastUploadKeyRef.current = key;
      lastFileRef.current = file;

      const result = await uploadResume(file, key);
      setNewCardId(result.id);
      setResumes((prev) => [
        {
          id: result.id,
          filename: result.filename,
          parsed_text: "",
          chunk_count: 0,
          status: result.status,
          status_message: "解析中...",
          created_at: new Date().toISOString(),
        },
        ...prev,
      ]);
      startPoll(result.id);
      // 上传成功后清空 retry 状态
      lastUploadKeyRef.current = null;
      lastFileRef.current = null;
      setUploadFailed(false);
    } catch {
      setError("上传失败，请重试");
      setUploadFailed(true);
    } finally {
      setUploading(false);
    }
  };

  // Task 2.6: 重试上传，复用 lastUploadKey 实现真正幂等
  const handleRetryUpload = () => {
    const lastFile = lastFileRef.current;
    const lastKey = lastUploadKeyRef.current;
    if (!lastFile || !lastKey) return;
    void doUpload(lastFile, lastKey);
  };

  const handleDrop = async (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragging(false);
    const file = e.dataTransfer.files?.[0];
    if (!file) return;

    const invalidReason = validateFile(file);
    if (invalidReason) {
      setError(invalidReason);
      return;
    }

    await doUpload(file);
  };

  const handleDragOver = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragging(false);
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    try {
      await deleteResume(deleteTarget.id);
      setResumes((prev) => prev.filter((r) => r.id !== deleteTarget.id));
      setTotal((prev) => prev - 1);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "删除失败");
    } finally {
      setDeleteTarget(null);
    }
  };

  // Task 5.5: 批量删除
  const handleBatchDelete = async () => {
    setBatchDeleting(true);
    let deletedCount = 0;
    let failCount = 0;
    for (const id of selectedIds) {
      try {
        await deleteResume(id);
        deletedCount++;
      } catch {
        failCount++;
      }
    }
    setBatchDeleting(false);
    setBatchDeleteOpen(false);
    setSelectMode(false);
    setSelectedIds(new Set());
    if (deletedCount > 0) {
      setResumes((prev) => prev.filter((r) => !selectedIds.has(r.id)));
      setTotal((prev) => prev - deletedCount);
      toast.success(`已删除 ${deletedCount} 份简历`);
    }
    if (failCount > 0) {
      setError(`${failCount} 份简历删除失败`);
    }
  };

  const toggleSelect = (id: number) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleSelectAll = () => {
    if (selectedIds.size === resumes.length) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(resumes.map((r) => r.id)));
    }
  };

  const exitSelectMode = () => {
    setSelectMode(false);
    setSelectedIds(new Set());
  };

  // Task 1.3: 重试失败的简历。调用 retryResume → 状态改回 processing → 重新轮询
  const handleRetry = async (resume: ResumeItem) => {
    // 防重复点击
    if (retryingIds.has(resume.id)) return;
    setRetryingIds((prev) => new Set(prev).add(resume.id));
    try {
      const result = await retryResume(resume.id);
      // 立即把卡片状态改成 processing，让用户看到反馈
      setResumes((prev) =>
        prev.map((r) =>
          r.id === resume.id
            ? { ...r, status: "processing", status_message: "重新解析中..." }
            : r
        )
      );
      toast.success(`已重新提交「${result.filename}」解析`);
      startPoll(result.id);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "重试失败";
      toast.error(msg);
    } finally {
      setRetryingIds((prev) => {
        const next = new Set(prev);
        next.delete(resume.id);
        return next;
      });
    }
  };

  return (
    <div
      className={`min-h-screen bg-[var(--color-bg)] drop-zone transition-all ${
        isDragging ? "ring-4 ring-indigo-500 ring-inset bg-indigo-500/5" : ""
      }`}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      <div className="max-w-3xl mx-auto px-4 sm:px-6 py-8">
        {/* ── 顶部栏 ── */}
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-xl font-semibold text-[var(--color-text)]">
              我的简历
              <span className="text-sm font-normal text-[var(--color-text-muted)] ml-2">
                ({total} 份)
              </span>
            </h1>
          </div>
          <div className="flex items-center gap-2">
            {/* 隐藏文件输入（始终在 DOM 中） */}
            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf,.docx"
              multiple
              onChange={handleUpload}
              style={{position:"absolute",opacity:0,pointerEvents:"none",width:0,height:0,overflow:"hidden"}}
            />
            {resumes.length > 0 && !selectMode && (
              <button
                onClick={() => setSelectMode(true)}
                className="px-3 py-2 rounded-lg text-sm text-[var(--color-text-secondary)]
                  hover:text-[var(--color-text)] hover:bg-white/8
                  transition-colors cursor-pointer"
                aria-label="管理"
              >
                <CheckSquare size={18} weight="regular" aria-hidden="true" />
              </button>
            )}
            {selectMode && (
              <>
                <label className="inline-flex items-center gap-1.5 px-2 py-1.5 text-xs text-[var(--color-text-secondary)] cursor-pointer">
                  <input
                    type="checkbox"
                    checked={selectedIds.size === resumes.length && resumes.length > 0}
                    onChange={toggleSelectAll}
                    className="rounded border-[var(--color-border)]"
                    aria-label="全选"
                  />
                  全选
                </label>
                <button
                  onClick={() => setBatchDeleteOpen(true)}
                  disabled={selectedIds.size === 0}
                  className="inline-flex items-center gap-1 px-3 py-1.5 text-xs font-medium
                    text-red-400 hover:text-red-300 hover:bg-red-500/10 rounded-lg
                    disabled:opacity-40 disabled:cursor-not-allowed
                    transition-colors cursor-pointer"
                  aria-label="删除所选"
                >
                  <TrashSimple size={14} weight="bold" aria-hidden="true" />
                  删除所选{selectedIds.size > 0 ? ` (${selectedIds.size})` : ""}
                </button>
                <button
                  onClick={exitSelectMode}
                  className="p-1.5 rounded-lg text-[var(--color-text-secondary)]
                    hover:text-[var(--color-text)] hover:bg-white/8
                    transition-colors cursor-pointer"
                  aria-label="取消"
                >
                  <X size={16} weight="bold" aria-hidden="true" />
                </button>
              </>
            )}
            {!selectMode && (
              <button
                onClick={triggerUpload}
                disabled={uploading}
                className="px-5 py-2.5 rounded-xl text-sm font-semibold text-white
                  bg-linear-to-r from-indigo-500 to-purple-600
                  hover:brightness-110 hover:shadow-lg hover:shadow-indigo-500/25
                  active:scale-[0.98] disabled:opacity-50 disabled:cursor-not-allowed
                  transition-all duration-200 cursor-pointer"
              >
                {uploading ? "上传中..." : "+ 上传简历"}
              </button>
            )}
          </div>
        </div>

        {/* ── 错误提示 ── */}
        {error && (
          <div className="mb-6 p-3.5 rounded-xl bg-red-500/10 border border-red-500/20 text-red-400 text-sm animate-shake flex items-center justify-between gap-3">
            <span>{error}</span>
            <div className="flex items-center gap-2 shrink-0">
              {/* Task 2.6: 上传失败时显示「重试上传」按钮，复用 lastUploadKey */}
              {uploadFailed && (
                <button
                  onClick={handleRetryUpload}
                  disabled={uploading}
                  className="px-2.5 py-1 rounded-md text-xs font-medium
                    bg-red-500/20 hover:bg-red-500/30 text-red-300
                    disabled:opacity-50 disabled:cursor-not-allowed
                    transition-colors cursor-pointer"
                >
                  重试上传
                </button>
              )}
              <button
                onClick={() => setError("")}
                className="text-red-500 hover:text-red-400 cursor-pointer"
              >
                ✕
              </button>
            </div>
          </div>
        )}

        {/* ── 内容区 ── */}
        {loading ? (
          <SkeletonList />
        ) : resumes.length === 0 ? (
          <EmptyState onUpload={triggerUpload} />
        ) : (
          <div className="space-y-3">
            {resumes.map((r, index) => (
              <Link
                key={r.id}
                to={r.status === "ready" ? `/resumes/${r.id}` : "#"}
                onClick={(e) => {
                  // P0.2: 失败/处理中状态点击卡片不再跳转，但保留按钮可点击
                  // 不使用 pointer-events-none，否则会连带禁用删除等操作按钮
                  if (r.status !== "ready") e.preventDefault();
                }}
                className="block group"
              >
                <div
                  className={`flex items-center justify-between p-5 rounded-2xl
                    border transition-all duration-200
                    ${r.status === "ready"
                      ? "bg-white/4 border-[var(--color-border)] hover:border-indigo-500/30 hover:bg-white/6 hover:-translate-y-px cursor-pointer"
                      : r.status === "failed"
                      ? "bg-white/4 border-red-500/15"
                      : "bg-white/4 border-[var(--color-border)]"
                    }
                    ${r.id === newCardId ? "animate-slide-in-top" : ""}
                    ${selectMode && selectedIds.has(r.id) ? "ring-1 ring-indigo-500/40 bg-indigo-500/5" : ""}
                  `}
                  style={
                    r.id !== newCardId
                      ? { animationDelay: `${index * 60}ms` }
                      : undefined
                  }
                >
                  {/* 左侧 */}
                  <div className="flex items-center gap-3.5 flex-1 min-w-0">
                    {selectMode && (
                      <input
                        type="checkbox"
                        checked={selectedIds.has(r.id)}
                        onChange={() => toggleSelect(r.id)}
                        onClick={(e) => e.stopPropagation()}
                        className="shrink-0 rounded border-[var(--color-border)]"
                        aria-label={`选择 ${r.filename}`}
                      />
                    )}
                    <FileIcon status={r.status} />
                    <div className="flex-1 min-w-0">
                      <p className={`text-sm font-medium truncate ${
                        r.status === "ready" ? "text-[var(--color-text)] group-hover:text-[var(--color-text)]" : "text-[var(--color-text-secondary)]"
                      }`}>
                        {r.filename}
                      </p>
                      <div className="flex items-center gap-2 mt-1">
                        {r.status === "processing" ? (
                          <div className="flex items-center gap-2">
                            <div className="h-1 w-24 rounded-full bg-white/6 overflow-hidden">
                              <div className="h-full w-3/5 rounded-full bg-linear-to-r from-amber-500 to-amber-400 animate-progress-pulse" />
                            </div>
                            <span className="text-xs text-[var(--color-text-muted)]">解析中...</span>
                          </div>
                        ) : r.status === "failed" ? (
                          <span className="text-xs text-red-400/80">
                            {r.status_message || "处理失败"}
                          </span>
                        ) : (
                          <>
                            <span className="text-xs text-[var(--color-text-muted)]">
                              {r.chunk_count} 个分块
                            </span>
                            <span className="text-xs text-[var(--color-text-muted)]">·</span>
                            <span className="text-xs text-[var(--color-text-muted)]">
                              {new Date(r.created_at).toLocaleDateString("zh-CN")}
                            </span>
                          </>
                        )}
                      </div>
                    </div>
                  </div>

                  {/* 右侧 */}
                  <div className="flex items-center gap-3 ml-4 shrink-0">
                    <StatusBadge status={r.status} />
                    {r.status === "failed" && (
                      <button
                        onClick={(e) => {
                          e.preventDefault();
                          e.stopPropagation();
                          handleRetry(r);
                        }}
                        disabled={retryingIds.has(r.id)}
                        className="inline-flex items-center gap-1 px-2.5 py-1.5 text-xs
                          text-[var(--color-text-secondary)] hover:text-amber-300
                          hover:bg-amber-500/10 rounded-lg
                          active:scale-[0.98] motion-reduce:active:scale-100
                          disabled:opacity-50 disabled:cursor-not-allowed
                          transition-all cursor-pointer"
                        aria-label="重试"
                      >
                        <ArrowClockwise size={13} weight="bold" aria-hidden="true" />
                        重试
                      </button>
                    )}
                    {r.status === "ready" && (
                      <>
                        {/* 大屏按钮组（≥640px） */}
                        <button
                          onClick={(e) => {
                            e.preventDefault();
                            e.stopPropagation();
                            setViewerTarget(r);
                          }}
                          className="hidden sm:inline-flex items-center gap-1 px-2.5 py-1.5 text-xs
                            text-[var(--color-text-secondary)] hover:text-emerald-300
                            hover:bg-emerald-500/10 rounded-lg
                            active:scale-[0.98] motion-reduce:active:scale-100
                            transition-all cursor-pointer"
                        >
                          <FileText size={13} weight="bold" aria-hidden="true" />
                          预览
                        </button>
                        <button
                          onClick={(e) => {
                            e.preventDefault();
                            e.stopPropagation();
                            setChunksTarget(r);
                          }}
                          className="hidden sm:inline-flex items-center gap-1 px-2.5 py-1.5 text-xs
                            text-[var(--color-text-secondary)] hover:text-sky-300
                            hover:bg-sky-500/10 rounded-lg
                            active:scale-[0.98] motion-reduce:active:scale-100
                            transition-all cursor-pointer"
                        >
                          <ListBullets size={13} weight="bold" aria-hidden="true" />
                          分块
                        </button>
                        <button
                          onClick={(e) => {
                            e.preventDefault();
                            e.stopPropagation();
                            setAnalyzeTarget(r);
                          }}
                          className="hidden sm:inline-flex items-center gap-1 px-2.5 py-1.5 text-xs
                            text-[var(--color-text-secondary)] hover:text-indigo-300
                            hover:bg-indigo-500/10 rounded-lg
                            active:scale-[0.98] motion-reduce:active:scale-100
                            transition-all cursor-pointer"
                        >
                          <Sparkle size={13} weight="bold" aria-hidden="true" />
                          分析
                        </button>
                        <button
                          onClick={(e) => {
                            e.preventDefault();
                            e.stopPropagation();
                            setJdMatchTarget(r);
                          }}
                          className="hidden sm:inline-flex items-center gap-1 px-2.5 py-1.5 text-xs
                            text-[var(--color-text-secondary)] hover:text-purple-300
                            hover:bg-purple-500/10 rounded-lg
                            active:scale-[0.98] motion-reduce:active:scale-100
                            transition-all cursor-pointer"
                        >
                          <Target size={13} weight="bold" aria-hidden="true" />
                          JD匹配
                        </button>
                        <button
                          onClick={(e) => {
                            e.preventDefault();
                            e.stopPropagation();
                            setDeleteTarget(r);
                          }}
                          className="hidden sm:inline-flex px-2.5 py-1.5 text-xs text-[var(--color-text-muted)] hover:text-red-400
                            hover:bg-red-500/10 rounded-lg transition-colors cursor-pointer"
                        >
                          删除
                        </button>

                        {/* 小屏 MoreMenu（<640px）：折叠预览/分块/分析/JD匹配/删除 */}
                        <div className="sm:hidden">
                          <MoreMenu
                            label="更多操作"
                            items={[
                              {
                                key: "preview",
                                label: "预览",
                                onClick: () => setViewerTarget(r),
                              },
                              {
                                key: "chunks",
                                label: "分块",
                                onClick: () => setChunksTarget(r),
                              },
                              {
                                key: "analyze",
                                label: "分析",
                                onClick: () => setAnalyzeTarget(r),
                              },
                              {
                                key: "jd-match",
                                label: "JD匹配",
                                onClick: () => setJdMatchTarget(r),
                              },
                              {
                                key: "delete",
                                label: "删除",
                                danger: true,
                                onClick: () => setDeleteTarget(r),
                              },
                            ]}
                          />
                        </div>
                      </>
                    )}
                    {/* processing / failed 状态：仅提供删除（failed 已有重试按钮） */}
                    {r.status !== "ready" && (
                      <>
                        <button
                          onClick={(e) => {
                            e.preventDefault();
                            e.stopPropagation();
                            setDeleteTarget(r);
                          }}
                          className="hidden sm:inline-flex px-2.5 py-1.5 text-xs text-[var(--color-text-muted)] hover:text-red-400
                            hover:bg-red-500/10 rounded-lg transition-colors cursor-pointer"
                        >
                          删除
                        </button>
                        <div className="sm:hidden">
                          <MoreMenu
                            label="更多操作"
                            items={[
                              {
                                key: "delete",
                                label: "删除",
                                danger: true,
                                onClick: () => setDeleteTarget(r),
                              },
                            ]}
                          />
                        </div>
                      </>
                    )}
                  </div>
                </div>
              </Link>
            ))}
          </div>
        )}
      </div>

      {/* ── 删除确认弹窗（共享 ConfirmDialog + focus trap） ── */}
      <ConfirmDialog
        open={deleteTarget !== null}
        title="确认删除"
        description={`确定删除「${deleteTarget?.filename ?? ""}」吗？此操作不可撤销。`}
        confirmText="删除"
        danger
        onConfirm={handleDelete}
        onCancel={() => setDeleteTarget(null)}
      />

      {/* ── 批量删除确认弹窗 ── */}
      <ConfirmDialog
        open={batchDeleteOpen}
        title="批量删除"
        description={`确定删除选中的 ${selectedIds.size} 份简历吗？此操作不可撤销。`}
        confirmText="删除"
        danger
        loading={batchDeleting}
        onConfirm={handleBatchDelete}
        onCancel={() => setBatchDeleteOpen(false)}
      />

      {/* ── 简历分析弹窗 ── */}
      <AnalysisModal
        resumeId={analyzeTarget?.id ?? 0}
        resumeFilename={analyzeTarget?.filename ?? ""}
        open={analyzeTarget !== null}
        onClose={() => setAnalyzeTarget(null)}
      />

      {/* ── 分块预览弹窗 ── */}
      <ChunksModal
        resumeId={chunksTarget?.id ?? 0}
        resumeFilename={chunksTarget?.filename ?? ""}
        open={chunksTarget !== null}
        onClose={() => setChunksTarget(null)}
      />

      {/* ── 简历原文预览弹窗 ── */}
      <ResumeViewer
        resumeId={viewerTarget?.id ?? 0}
        resumeFilename={viewerTarget?.filename ?? ""}
        open={viewerTarget !== null}
        onClose={() => setViewerTarget(null)}
      />

      {/* ── JD 匹配分析弹窗 ── */}
      <MatchJDModal
        resumeId={jdMatchTarget?.id ?? 0}
        resumeFilename={jdMatchTarget?.filename ?? ""}
        open={jdMatchTarget !== null}
        onClose={() => setJdMatchTarget(null)}
      />
    </div>
  );
}
