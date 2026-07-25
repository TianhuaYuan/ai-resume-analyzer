import { useEffect, useState, useRef } from "react";
import { Link } from "react-router-dom";
import { Sparkle, ListBullets, FileText, Target } from "@phosphor-icons/react";
import {
  listResumes,
  uploadResume,
  deleteResume,
  getResume,
  type ResumeItem,
} from "../api/resumes";
import AnalysisModal from "../components/AnalysisModal";
import ChunksModal from "../components/ChunksModal";
import ResumeViewer from "../components/ResumeViewer";
import MatchJDModal from "../components/MatchJDModal";

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

// ── 确认删除弹窗 ────────────────────────────────────────

function ConfirmDialog({
  filename,
  onConfirm,
  onCancel,
}: {
  filename: string;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="bg-[#1e293b] border border-white/10 rounded-2xl p-6 max-w-sm w-full mx-4
        animate-fade-in-up shadow-2xl">
        <h3 className="text-lg font-semibold text-slate-100 mb-2">确认删除</h3>
        <p className="text-sm text-slate-400 mb-6">
          确定删除「<span className="text-slate-200">{filename}</span>」吗？此操作不可撤销。
        </p>
        <div className="flex gap-3 justify-end">
          <button
            onClick={onCancel}
            className="px-4 py-2 text-sm text-slate-400 hover:text-slate-200
              bg-white/5 border border-white/10 rounded-lg transition-colors cursor-pointer"
          >
            取消
          </button>
          <button
            onClick={onConfirm}
            className="px-4 py-2 text-sm text-white bg-red-500/80 hover:bg-red-500
              rounded-lg transition-colors cursor-pointer"
          >
            删除
          </button>
        </div>
      </div>
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
      <h3 className="text-lg font-medium text-slate-200 mb-2">还没有简历</h3>
      <p className="text-sm text-slate-500 mb-6">上传你的第一份简历，开始 AI 智能分析</p>
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

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setError("");
    setUploading(true);

    // 拖拽上传后，清空 input 值允许重复上传同一文件
    if (fileInputRef.current) fileInputRef.current.value = "";

    try {
      const result = await uploadResume(file);
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
    } catch {
      setError("上传失败，请重试");
    } finally {
      setUploading(false);
    }
  };

  const handleDrop = async (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragging(false);
    const file = e.dataTransfer.files?.[0];
    if (!file) return;
    if (file.type !== "application/pdf") {
      setError("仅支持 PDF 文件");
      return;
    }
    // 复用 handleUpload 的逻辑
    setError("");
    setUploading(true);
    try {
      const result = await uploadResume(file);
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
    } catch {
      setError("上传失败，请重试");
    } finally {
      setUploading(false);
    }
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

  return (
    <div
      className={`min-h-screen bg-[#0f172a] drop-zone transition-all ${
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
            <h1 className="text-xl font-semibold text-slate-100">
              我的简历
              <span className="text-sm font-normal text-slate-500 ml-2">
                ({total} 份)
              </span>
            </h1>
          </div>
          <div>
            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf,.docx"
              onChange={handleUpload}
              style={{position:"absolute",opacity:0,pointerEvents:"none",width:0,height:0,overflow:"hidden"}}
            />
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
          </div>
        </div>

        {/* ── 错误提示 ── */}
        {error && (
          <div className="mb-6 p-3.5 rounded-xl bg-red-500/10 border border-red-500/20 text-red-400 text-sm animate-shake">
            {error}
            <button
              onClick={() => setError("")}
              className="ml-3 text-red-500 hover:text-red-400 cursor-pointer"
            >
              ✕
            </button>
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
                className={`block group ${r.status !== "ready" ? "pointer-events-none" : ""}`}
              >
                <div
                  className={`flex items-center justify-between p-5 rounded-2xl
                    border transition-all duration-200
                    ${r.status === "ready"
                      ? "bg-white/4 border-white/8 hover:border-indigo-500/30 hover:bg-white/6 hover:-translate-y-px cursor-pointer"
                      : r.status === "failed"
                      ? "bg-white/4 border-red-500/15"
                      : "bg-white/4 border-white/8"
                    }
                    ${r.id === newCardId ? "animate-slide-in-top" : ""}
                  `}
                  style={
                    r.id !== newCardId
                      ? { animationDelay: `${index * 60}ms` }
                      : undefined
                  }
                >
                  {/* 左侧 */}
                  <div className="flex items-center gap-3.5 flex-1 min-w-0">
                    <FileIcon status={r.status} />
                    <div className="flex-1 min-w-0">
                      <p className={`text-sm font-medium truncate ${
                        r.status === "ready" ? "text-slate-200 group-hover:text-white" : "text-slate-400"
                      }`}>
                        {r.filename}
                      </p>
                      <div className="flex items-center gap-2 mt-1">
                        {r.status === "processing" ? (
                          <div className="flex items-center gap-2">
                            <div className="h-1 w-24 rounded-full bg-white/6 overflow-hidden">
                              <div className="h-full w-3/5 rounded-full bg-linear-to-r from-amber-500 to-amber-400 animate-progress-pulse" />
                            </div>
                            <span className="text-xs text-slate-500">解析中...</span>
                          </div>
                        ) : r.status === "failed" ? (
                          <span className="text-xs text-red-400/80">
                            {r.status_message || "处理失败"}
                          </span>
                        ) : (
                          <>
                            <span className="text-xs text-slate-500">
                              {r.chunk_count} 个分块
                            </span>
                            <span className="text-xs text-slate-600">·</span>
                            <span className="text-xs text-slate-500">
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
                    {r.status === "ready" && (
                      <>
                        <button
                          onClick={(e) => {
                            e.preventDefault();
                            e.stopPropagation();
                            setViewerTarget(r);
                          }}
                          className="inline-flex items-center gap-1 px-2.5 py-1.5 text-xs
                            text-slate-400 hover:text-emerald-300
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
                          className="inline-flex items-center gap-1 px-2.5 py-1.5 text-xs
                            text-slate-400 hover:text-sky-300
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
                          className="inline-flex items-center gap-1 px-2.5 py-1.5 text-xs
                            text-slate-400 hover:text-indigo-300
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
                          className="inline-flex items-center gap-1 px-2.5 py-1.5 text-xs
                            text-slate-400 hover:text-purple-300
                            hover:bg-purple-500/10 rounded-lg
                            active:scale-[0.98] motion-reduce:active:scale-100
                            transition-all cursor-pointer"
                        >
                          <Target size={13} weight="bold" aria-hidden="true" />
                          JD匹配
                        </button>
                      </>
                    )}
                    <button
                      onClick={(e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        setDeleteTarget(r);
                      }}
                      className="px-2.5 py-1.5 text-xs text-slate-500 hover:text-red-400
                        hover:bg-red-500/10 rounded-lg transition-colors cursor-pointer"
                    >
                      删除
                    </button>
                  </div>
                </div>
              </Link>
            ))}
          </div>
        )}
      </div>

      {/* ── 删除确认弹窗 ── */}
      {deleteTarget && (
        <ConfirmDialog
          filename={deleteTarget.filename}
          onConfirm={handleDelete}
          onCancel={() => setDeleteTarget(null)}
        />
      )}

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
