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
    <div className="border border-[var(--color-border)] p-5">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3 flex-1">
          <div className="w-8 h-8 animate-skeleton" />
          <div className="flex-1 space-y-2">
            <div className="h-4 w-48 animate-skeleton" />
            <div className="h-3 w-32 animate-skeleton" />
          </div>
        </div>
        <div className="h-6 w-16 animate-skeleton" />
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
      <span className="inline-flex items-center gap-1.5 px-3 py-1 text-xs font-medium
        font-mono-label tracking-widest uppercase
        border border-[var(--color-text)] text-[var(--color-text-secondary)]">
        <span className="w-1.5 h-1.5 bg-[var(--color-text-muted)] animate-progress-pulse" />
        处理中
      </span>
    );
  }
  if (status === "failed") {
    return (
      <span className="inline-flex items-center px-3 py-1 text-xs font-medium
        font-mono-label tracking-widest uppercase
        border-b-2 border-[var(--color-text)] text-[var(--color-text-secondary)]">
        失败
      </span>
    );
  }
  return (
    <span className="inline-flex items-center px-3 py-1 text-xs font-medium
      font-mono-label tracking-widest uppercase
      text-[var(--color-text)]">
      就绪
    </span>
  );
}

function FileIcon({ status }: { status: string }) {
  const borderClass =
    status === "failed"
      ? "border-b-2 border-[var(--color-text)]"
      : status === "processing"
      ? "border border-[var(--color-border)]"
      : "border border-[var(--color-text)]";
  const symbol = status === "failed" ? "!" : status === "processing" ? "..." : "#";

  return (
    <div className={`w-9 h-9 flex items-center justify-center text-sm font-mono-label font-bold text-[var(--color-text)] ${borderClass}`}>
      {symbol}
    </div>
  );
}

// ── 空状态 ──────────────────────────────────────────────

function EmptyState({ onUpload }: { onUpload: () => void }) {
  return (
    <div className="py-16 md:py-32 flex flex-col md:flex-row md:items-center md:justify-between gap-12">
      <div className="flex-1">
        <hr className="mono-rule mb-8 max-w-xs" />
        <p className="font-display text-3xl md:text-5xl font-bold tracking-tight text-[var(--color-text)] mb-6 leading-tight">
          开始你的<br />简历之旅
        </p>
        <p className="text-base md:text-lg text-[var(--color-text-secondary)] mb-8 max-w-md leading-relaxed" style={{ fontFamily: "var(--font-body)" }}>
          上传你的第一份简历，AI 将自动分析内容、提取关键信息，并生成专业的优化建议。
        </p>
        <button
          onClick={onUpload}
          className="mono-btn-primary"
        >
          上传简历 →
        </button>
      </div>
      <div className="flex-1 flex justify-center">
        <div className="w-48 h-48 md:w-64 md:h-64 border-2 border-[var(--color-text)] flex items-center justify-center">
          <svg viewBox="0 0 64 64" className="w-24 h-24 md:w-32 md:h-32">
            <polygon points="32,6 54,18 32,30 10,18" fill="var(--color-text)" opacity="0.1"/>
            <polygon points="10,18 32,30 32,54 10,42" fill="var(--color-text)" opacity="0.1"/>
            <polygon points="32,30 54,18 54,42 32,54" fill="var(--color-text)" opacity="0.1"/>
            <polygon points="32,6 54,18 32,30 10,18" fill="none" stroke="var(--color-text)" strokeWidth="1"/>
            <polygon points="10,18 32,30 32,54 10,42" fill="none" stroke="var(--color-text)" strokeWidth="1"/>
            <polygon points="32,30 54,18 54,42 32,54" fill="none" stroke="var(--color-text)" strokeWidth="1"/>
          </svg>
        </div>
      </div>
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
      setTotal((prev) => Math.max(0, prev - 1));
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
      setTotal((prev) => Math.max(0, prev - deletedCount));
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
    <>
      <div
        className={`min-h-screen bg-[var(--color-bg)] drop-zone ${
          isDragging ? "ring-4 ring-[var(--color-text)] ring-inset" : ""
        }`}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
      >
        <div className="max-w-4xl mx-auto">
        {/* ── 顶部栏 ── */}
        <div className="sticky top-[49px] z-30 bg-[var(--color-bg)] px-6 md:px-8 lg:px-12 py-4 border-b border-[var(--color-border)] flex items-center justify-between">
          <div>
            <h1 className="font-display text-4xl md:text-5xl font-bold tracking-tight text-[var(--color-text)]">
              我的简历
              <span className="font-mono-label text-sm font-normal tracking-widest text-[var(--color-text-muted)] ml-3 uppercase">
                {total} 份
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
                className="mono-btn-primary"
              >
                {uploading ? "上传中..." : "上传简历 →"}
              </button>
            )}
          </div>
        </div>

        {/* ── 内容区 ── */}
        <div className="px-6 md:px-8 lg:px-12 py-8 md:py-12">
          {/* ── 错误提示 ── */}
          {error && (
            <div className="mb-6 p-3.5 border-b-2 border-[var(--color-text)] text-[var(--color-text)] text-sm animate-shake flex items-center justify-between gap-3">
              <span className="font-mono-label tracking-widest uppercase text-xs">{error}</span>
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
                  className={`flex items-center justify-between p-5
                    border transition-colors duration-100
                    ${r.status === "ready"
                      ? "border-[var(--color-text)] mono-hover-border cursor-pointer"
                      : r.status === "failed"
                      ? "border-[var(--color-text)] border-b-2"
                      : "border-[var(--color-border)]"
                    }
                    ${r.id === newCardId ? "animate-slide-in-top" : ""}
                    ${selectMode && selectedIds.has(r.id) ? "border-2 border-[var(--color-text)] bg-[var(--color-text)]/5" : ""}
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
                            <div className="h-0.5 w-24 bg-[var(--color-border)] overflow-hidden">
                              <div className="h-full w-3/5 bg-[var(--color-text)] animate-progress-pulse" />
                            </div>
                            <span className="text-xs font-mono-label tracking-widest text-[var(--color-text-muted)] uppercase">解析中</span>
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
                          font-mono-label tracking-widest uppercase
                          text-[var(--color-text-secondary)] hover:text-[var(--color-text)]
                          hover:bg-[var(--color-bg)]
                          border-b border-transparent hover:border-[var(--color-text)]
                          disabled:opacity-50 disabled:cursor-not-allowed
                          transition-colors duration-100 cursor-pointer"
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
                            font-mono-label tracking-widest uppercase
                            text-[var(--color-text-secondary)] hover:text-[var(--color-text)]
                            hover:border-b hover:border-[var(--color-text)]
                            border-b border-transparent
                            transition-colors duration-100 cursor-pointer"
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
                            font-mono-label tracking-widest uppercase
                            text-[var(--color-text-secondary)] hover:text-[var(--color-text)]
                            hover:border-b hover:border-[var(--color-text)]
                            border-b border-transparent
                            transition-colors duration-100 cursor-pointer"
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
                            font-mono-label tracking-widest uppercase
                            text-[var(--color-text-secondary)] hover:text-[var(--color-text)]
                            hover:border-b hover:border-[var(--color-text)]
                            border-b border-transparent
                            transition-colors duration-100 cursor-pointer"
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
                            font-mono-label tracking-widest uppercase
                            text-[var(--color-text-secondary)] hover:text-[var(--color-text)]
                            hover:border-b hover:border-[var(--color-text)]
                            border-b border-transparent
                            transition-colors duration-100 cursor-pointer"
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
                          className="hidden sm:inline-flex px-2.5 py-1.5 text-xs font-mono-label tracking-widest uppercase
                            text-[var(--color-text-muted)] hover:text-[var(--color-text)]
                            hover:border-b-2 hover:border-[var(--color-text)]
                            border-b border-transparent
                            transition-colors duration-100 cursor-pointer"
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
                          className="hidden sm:inline-flex px-2.5 py-1.5 text-xs font-mono-label tracking-widest uppercase
                            text-[var(--color-text-muted)] hover:text-[var(--color-text)]
                            hover:border-b-2 hover:border-[var(--color-text)]
                            border-b border-transparent
                            transition-colors duration-100 cursor-pointer"
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
    </div>
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
    </>
  );
}
