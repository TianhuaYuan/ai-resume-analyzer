import { useEffect, useState, useRef, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { Upload, FileText, Spinner, Trash } from "@phosphor-icons/react";
import {
  listResumes,
  uploadResume,
  deleteResume,
  generateIdempotencyKey,
  type ResumeItem,
} from "../api/resumes";
import { useToast } from "./Toast";
import ConfirmDialog from "./ConfirmDialog";

interface SidebarProps {
  /** 当前选中的简历 ID，用于高亮 */
  activeResumeId?: number;
}

/**
 * T20: 左侧简历列表 Sidebar。
 *
 * 功能：
 * - 顶部上传按钮（复用 uploadResume API + 幂等键）
 * - 简历列表（状态指示 + 文件名 + 分块数）
 * - 点击简历导航到 /resumes/:id
 * - 每项 hover 显示删除按钮（ConfirmDialog 确认；删除当前简历则回首页智能分流）
 * - WebSocket 事件驱动刷新（分析完成/状态变更）
 *
 * 布局：w-64 shrink-0，固定在 AppLayout 左侧
 */
export default function Sidebar({ activeResumeId }: SidebarProps) {
  const navigate = useNavigate();
  const toast = useToast();

  const [resumes, setResumes] = useState<ResumeItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<ResumeItem | null>(null);
  const [deleting, setDeleting] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const fetchResumes = useCallback(async () => {
    try {
      const data = await listResumes(50);
      setResumes(data.items);
    } catch {
      // 静默失败，不打断用户
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchResumes();
  }, [fetchResumes]);

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

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    e.target.value = "";

    // 校验
    const validTypes = [
      "application/pdf",
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ];
    const ext = file.name.split(".").pop()?.toLowerCase();
    if (!validTypes.includes(file.type) && ext !== "pdf" && ext !== "docx") {
      toast.error("仅支持 PDF / DOCX 格式");
      return;
    }
    if (file.size > 10 * 1024 * 1024) {
      toast.error("文件大小不能超过 10MB");
      return;
    }

    setUploading(true);
    try {
      const key = await generateIdempotencyKey(file);
      const result = await uploadResume(file, key);
      toast.success(`「${result.filename}」上传成功`);
      await fetchResumes();
      // 导航到新简历
      navigate(`/resumes/${result.id}`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "上传失败");
    } finally {
      setUploading(false);
    }
  };

  // 删除简历：删除当前正在查看的简历时回首页（智能分流到最近一份），否则留在原页
  const handleDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await deleteResume(deleteTarget.id);
      toast.success("已删除");
      if (deleteTarget.id === activeResumeId) {
        navigate("/");
      }
      await fetchResumes();
    } catch {
      toast.error("删除失败");
    } finally {
      setDeleting(false);
      setDeleteTarget(null);
    }
  };

  // 状态指示色
  const statusColor = (status: string) => {
    if (status === "processing") return "bg-sky-400 animate-pulse";
    if (status === "failed") return "bg-red-400";
    return "bg-emerald-400";
  };

  return (
    <>
      <aside className="w-64 shrink-0 border-r border-[var(--color-border)] bg-[var(--color-bg)] flex flex-col h-full">
      {/* ── 上传按钮 ── */}
      <div className="shrink-0 p-3 border-b border-[var(--color-border)]">
        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
          onChange={handleUpload}
          className="hidden"
        />
        <button
          onClick={() => fileInputRef.current?.click()}
          disabled={uploading}
          className="w-full inline-flex items-center justify-center gap-2 px-3 py-2 rounded-lg
            text-xs font-medium text-white
            bg-linear-to-br from-indigo-500 to-purple-600
            hover:brightness-110 hover:shadow-lg hover:shadow-indigo-500/20
            active:scale-[0.98] motion-reduce:active:scale-100
            transition-all cursor-pointer
            disabled:opacity-50 disabled:cursor-not-allowed"
          aria-label="上传简历"
        >
          {uploading ? (
            <>
              <Spinner size={14} className="animate-spin" aria-hidden="true" />
              上传中...
            </>
          ) : (
            <>
              <Upload size={14} weight="bold" aria-hidden="true" />
              上传简历
            </>
          )}
        </button>
      </div>

      {/* ── 简历列表 ── */}
      <div className="flex-1 overflow-y-auto py-2">
        {loading ? (
          <div className="flex items-center justify-center py-8">
            <Spinner size={20} className="animate-spin text-[var(--color-text-muted)]" aria-hidden="true" />
          </div>
        ) : resumes.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-8 px-4 text-center">
            <FileText size={24} weight="duotone" className="text-[var(--color-text-muted)] mb-2" aria-hidden="true" />
            <p className="text-xs text-[var(--color-text-muted)]">暂无简历</p>
            <p className="text-[10px] text-[var(--color-text-muted)] mt-1">点击上方按钮上传</p>
          </div>
        ) : (
          <ul className="space-y-0.5 px-2">
            {resumes.map((r) => {
              const isActive = r.id === activeResumeId;
              const isEditable = r.status === "ready" || r.status === "draft";
              return (
                <li key={r.id} className="group relative">
                  <div
                    className={`flex items-center rounded-lg transition-all
                      ${isActive
                        ? "bg-indigo-500/15 border border-indigo-500/30"
                        : "border border-transparent hover:bg-white/5"
                      }`}
                  >
                    <button
                      onClick={() => isEditable && navigate(`/resumes/${r.id}`)}
                      disabled={!isEditable}
                      className={`flex-1 flex items-center gap-2.5 px-2.5 py-2 rounded-lg text-left min-w-0
                        ${isEditable ? "cursor-pointer" : "cursor-not-allowed opacity-50"}`}
                      aria-label={r.filename}
                      aria-current={isActive ? "page" : undefined}
                    >
                      {/* 状态指示点 */}
                      <span
                        className={`w-2 h-2 shrink-0 rounded-full ${statusColor(r.status)}`}
                        aria-hidden="true"
                      />
                      <div className="flex-1 min-w-0">
                        <p className={`text-xs truncate ${
                          isActive ? "text-indigo-300 font-medium" : "text-[var(--color-text-secondary)]"
                        }`}>
                          {r.filename}
                        </p>
                        <p className="text-[10px] text-[var(--color-text-muted)] mt-0.5">
                          {r.status === "processing"
                            ? "解析中..."
                            : r.status === "failed"
                            ? "解析失败"
                            : r.status === "draft"
                            ? "草稿"
                            : `${r.chunk_count} 分块`}
                        </p>
                      </div>
                    </button>
                    {/* hover 显示删除按钮 */}
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        setDeleteTarget(r);
                      }}
                      className="shrink-0 mr-1 p-1.5 rounded text-[var(--color-text-muted)]
                        hover:text-red-400 hover:bg-red-500/10
                        opacity-0 group-hover:opacity-100 focus:opacity-100
                        transition-all cursor-pointer"
                      aria-label={`删除 ${r.filename}`}
                      title="删除"
                    >
                      <Trash size={12} weight="bold" aria-hidden="true" />
                    </button>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </aside>

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
    </>
  );
}
