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

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  const handleRetry = () => load();

  const handleOverlayClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if (e.target === e.currentTarget) onClose();
  };

  if (!open) return null;

  return (
    <div
      onClick={handleOverlayClick}
      className="fixed inset-0 z-50 flex items-center justify-center
        bg-black/60 backdrop-blur-sm motion-reduce:backdrop-blur-none"
      role="dialog"
      aria-modal="true"
      aria-label={`简历预览: ${resumeFilename}`}
    >
      <div
        className="bg-[#1e293b] border border-white/10 rounded-2xl
          max-w-2xl w-full mx-4 shadow-2xl
          animate-fade-in-up motion-reduce:animate-none
          flex flex-col max-h-[85dvh]"
      >
        {/* 头部 */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-white/8 shrink-0">
          <div className="min-w-0 flex-1">
            <h3 className="text-base font-semibold text-slate-100 truncate">
              简历预览
            </h3>
            <p className="text-xs text-slate-500 truncate mt-0.5">
              {resumeFilename}
            </p>
          </div>
          <button
            onClick={onClose}
            aria-label="关闭"
            className="ml-3 p-1.5 rounded-lg text-slate-400
              hover:text-slate-100 hover:bg-white/8
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

          {status === "success" && resume && !resume.parsed_text && (
            <div className="text-center py-12 text-slate-500 text-sm">
              简历内容为空，可能还在解析中
            </div>
          )}

          {status === "success" && resume && resume.parsed_text && (
            <pre className="text-sm text-slate-300 leading-relaxed whitespace-pre-wrap font-mono">
              {resume.parsed_text}
            </pre>
          )}
        </div>

        {/* 底部信息 */}
        {status === "success" && resume && (
          <div className="px-6 py-3 border-t border-white/8 shrink-0">
            <div className="flex items-center gap-2 text-xs text-slate-500">
              <FileText size={12} weight="bold" aria-hidden="true" />
              <span>{resume.chunk_count} 个分块</span>
              <span className="text-slate-600">·</span>
              <span>{new Date(resume.created_at).toLocaleDateString("zh-CN")}</span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
