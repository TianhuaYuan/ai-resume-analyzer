import { useState, useCallback, useEffect, useRef } from "react";
import { X, ArrowClockwise, Target } from "@phosphor-icons/react";
import { matchJD } from "../api/resumes";
import MarkdownRenderer from "./MarkdownRenderer";

interface MatchJDModalProps {
  resumeId: number;
  resumeFilename: string;
  open: boolean;
  onClose: () => void;
}

type Status = "idle" | "loading" | "error" | "success";

export default function MatchJDModal({
  resumeId,
  resumeFilename,
  open,
  onClose,
}: MatchJDModalProps) {
  const [jdText, setJdText] = useState("");
  const [status, setStatus] = useState<Status>("idle");
  const [result, setResult] = useState("");
  const [error, setError] = useState("");
  const cancelledRef = useRef(false);
  const dialogRef = useRef<HTMLDialogElement>(null);

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

  // open 变化时重置状态
  useEffect(() => {
    if (!open) return;
    setJdText("");
    setStatus("idle");
    setResult("");
    setError("");
    return () => {
      cancelledRef.current = true;
    };
  }, [open]);

  const handleMatch = useCallback(async () => {
    if (!jdText.trim()) return;
    cancelledRef.current = false;
    setStatus("loading");
    setError("");
    try {
      const res = await matchJD(resumeId, jdText);
      if (cancelledRef.current) return;
      setResult(res.analysis);
      setStatus("success");
    } catch (err: unknown) {
      if (cancelledRef.current) return;
      setError(err instanceof Error ? err.message : "匹配分析失败");
      setStatus("error");
    }
  }, [resumeId, jdText]);

  const handleRetry = () => handleMatch();

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
      aria-label={`JD 匹配分析: ${resumeFilename}`}
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
              JD 匹配分析
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
          {/* idle / loading: 显示输入框 */}
          {(status === "idle" || status === "loading") && (
            <>
              <label className="block text-sm text-[var(--color-text-secondary)] mb-2">
                职位描述（JD）
              </label>
              <textarea
                value={jdText}
                onChange={(e) => setJdText(e.target.value)}
                placeholder="粘贴职位描述（JD）文本..."
                disabled={status === "loading"}
                rows={6}
                className="w-full px-3 py-2.5 text-sm text-[var(--color-text)]
                  bg-[#F2F2F7] border border-transparent rounded-xl
                  placeholder:text-[var(--color-text-muted)]
                  focus:outline-none focus:bg-white focus:border-brand/40 focus:ring-4 focus:ring-brand/15
                  resize-y disabled:opacity-50
                  transition-all duration-200"
              />
              <button
                onClick={handleMatch}
                disabled={status === "loading" || !jdText.trim()}
                className="mt-3 inline-flex items-center gap-1.5 px-4 py-2
                  text-sm font-medium rounded-full
                  bg-brand
                  text-white
                  hover:bg-[#0077ed] hover:shadow-lg hover:shadow-brand/25
                  active:scale-[0.98] motion-reduce:active:scale-100
                  disabled:opacity-50 disabled:cursor-not-allowed
                  transition-all cursor-pointer"
              >
                <Target size={14} weight="bold" aria-hidden="true" />
                {status === "loading" ? "分析中..." : "开始匹配"}
              </button>
            </>
          )}

          {/* error */}
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

          {/* success */}
          {status === "success" && (
            <>
              {/* Task 2.4: 替换纯文本 div 为 Markdown 渲染（GFM + sanitize + 单换行） */}
              <div aria-live="polite">
                <MarkdownRenderer>{result}</MarkdownRenderer>
              </div>
              <button
                onClick={() => {
                  setStatus("idle");
                  setResult("");
                }}
                className="mt-4 inline-flex items-center gap-1.5 px-3 py-1.5
                  text-xs font-medium rounded-lg
                  bg-[var(--color-bg-secondary)] hover:bg-[#E5E5EA] border border-[var(--color-border)]
                  text-[var(--color-text-secondary)] hover:text-[var(--color-text)]
                  active:scale-[0.98] motion-reduce:active:scale-100
                  transition-all cursor-pointer"
              >
                重新输入
              </button>
            </>
          )}
        </div>
      </div>
    </dialog>
  );
}
