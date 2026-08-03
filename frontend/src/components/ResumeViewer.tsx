import { useEffect, useRef, useState, useCallback } from "react";
import { X, ArrowClockwise, FileText } from "@phosphor-icons/react";
import { getResume, type ResumeItem } from "../api/resumes";

interface ResumeViewerProps {
  resumeId: number;
  resumeFilename: string;
  open: boolean;
  onClose: () => void;
}

type Status = "loading" | "error" | "success";

export default function ResumeViewer({
  resumeId,
  resumeFilename,
  open,
  onClose,
}: ResumeViewerProps) {
  const [status, setStatus] = useState<Status>("loading");
  const [resume, setResume] = useState<ResumeItem | null>(null);
  const [error, setError] = useState("");
  const cancelledRef = useRef(false);
  const dialogRef = useRef<HTMLDialogElement>(null);

  const load = useCallback(async () => {
    cancelledRef.current = false;
    setStatus("loading");
    setError("");
    try {
      const res = await getResume(resumeId);
      if (cancelledRef.current) return;
      setResume(res);
      setStatus("success");
    } catch (err: unknown) {
      if (cancelledRef.current) return;
      setError(err instanceof Error ? err.message : "加载简历失败");
      setStatus("error");
    }
  }, [resumeId]);

  useEffect(() => {
    if (!open) return;
    setResume(null);
    setError("");
    load();
    return () => {
      cancelledRef.current = true;
    };
  }, [open, load]);

  // P3-6：使用原生 <dialog>，showModal/close 控制，Esc 原生支持
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

  const handleRetry = () => load();

  const handleCancel = (e: React.FormEvent<HTMLDialogElement>) => {
    e.preventDefault();
    onClose();
  };

  if (!open) return null;

  return (
    <dialog
      ref={dialogRef}
      onCancel={handleCancel}
      onClose={handleCancel}
      className="fixed inset-0 z-50 m-0 w-full h-full p-0
        bg-black/60 backdrop-blur-sm motion-reduce:backdrop-blur-none"
      role="dialog"
      aria-modal="true"
      aria-label={`简历预览: ${resumeFilename}`}
    >
      <div
        className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2
          bg-[var(--color-surface)] border border-[var(--color-border)] rounded-2xl
          max-w-2xl w-full mx-4 shadow-2xl
          animate-fade-in-up motion-reduce:animate-none
          flex flex-col max-h-[85dvh]"
      >
        {/* 头部 */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--color-border)] shrink-0">
          <div className="min-w-0 flex-1">
            <h3 className="text-base font-semibold text-[var(--color-text)] truncate">
              简历预览
            </h3>
            <p className="text-xs text-[var(--color-text-muted)] truncate mt-0.5">
              {resumeFilename}
            </p>
          </div>
          <button
            onClick={onClose}
            aria-label="关闭"
            className="ml-3 p-1.5 rounded-lg text-[var(--color-text-secondary)]
              hover:text-[var(--color-text)] hover:bg-[var(--color-bg-secondary)]
              active:scale-[0.95] motion-reduce:active:scale-100
              transition-all cursor-pointer shrink-0"
          >
            <X size={18} weight="bold" aria-hidden="true" />
          </button>
        </div>

        {/* 内容区 */}
        <div className="flex-1 overflow-y-auto px-6 py-5">
          {status === "loading" && (
            <div className="space-y-3" aria-busy="true" aria-live="polite">
              <div className="h-4 w-3/4 rounded animate-skeleton" />
              <div className="h-4 w-full rounded animate-skeleton" />
              <div className="h-4 w-5/6 rounded animate-skeleton" />
              <div className="h-4 w-2/3 rounded animate-skeleton" />
            </div>
          )}

          {status === "error" && (
            <div
              className="p-4 rounded-xl bg-red-500/10 border border-red-500/20 text-red-400"
              role="alert"
            >
              <p className="text-sm mb-3">{error}</p>
              <button
                onClick={handleRetry}
                className="inline-flex items-center gap-1.5 px-3 py-1.5
                  text-xs font-medium rounded-lg
                  bg-red-500/15 hover:bg-red-500/25
                  border border-red-500/30
                  text-red-300
                  active:scale-[0.98] motion-reduce:active:scale-100
                  transition-all cursor-pointer"
              >
                <ArrowClockwise size={14} weight="bold" aria-hidden="true" />
                重试
              </button>
            </div>
          )}

          {/* Task 2.7: 空 parsed_text 按 status 区分文案，避免误导 */}
          {status === "success" && resume && !resume.parsed_text && (
            <div className="text-center py-12">
              {resume.status === "processing" && (
                <div className="space-y-3">
                  <p className="text-[var(--color-text-muted)] text-sm">
                    简历正在解析中，请稍后刷新
                  </p>
                  <button
                    onClick={handleRetry}
                    aria-label="刷新"
                    className="inline-flex items-center gap-1.5 px-3 py-1.5
                      text-xs font-medium rounded-lg
                      bg-brand/15 hover:bg-brand/25
                      border border-brand/30 text-brand
                      active:scale-[0.98] motion-reduce:active:scale-100
                      transition-all cursor-pointer"
                  >
                    <ArrowClockwise size={14} weight="bold" aria-hidden="true" />
                    刷新
                  </button>
                </div>
              )}
              {resume.status === "failed" && (
                <div className="space-y-2">
                  <p className="text-red-400 text-sm font-medium">简历解析失败</p>
                  <p className="text-[var(--color-text-muted)] text-xs">
                    {resume.status_message || "未知错误"}
                  </p>
                </div>
              )}
              {resume.status === "ready" && (
                <p className="text-[var(--color-text-muted)] text-sm">
                  解析完成，但未提取到文本内容（可能是图片型 PDF）
                </p>
              )}
            </div>
          )}

          {status === "success" && resume && resume.parsed_text && (
            <pre className="text-sm text-[var(--color-text-secondary)] leading-relaxed whitespace-pre-wrap font-mono">
              {resume.parsed_text}
            </pre>
          )}
        </div>

        {/* 底部信息 */}
        {status === "success" && resume && (
          <div className="px-6 py-3 border-t border-[var(--color-border)] shrink-0">
            <div className="flex items-center gap-2 text-xs text-[var(--color-text-muted)]">
              <FileText size={12} weight="bold" aria-hidden="true" />
              <span>更新于 {new Date(resume.updated_at ?? resume.created_at).toLocaleDateString("zh-CN")}</span>
            </div>
          </div>
        )}
      </div>
    </dialog>
  );
}
