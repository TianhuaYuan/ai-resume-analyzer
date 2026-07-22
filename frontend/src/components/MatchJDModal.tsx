import { useState, useCallback, useEffect, useRef } from "react";
import { X, ArrowClockwise, Target } from "@phosphor-icons/react";
import { matchJD } from "../api/resumes";

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

  // Esc 关闭
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

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
      aria-label={`JD 匹配分析: ${resumeFilename}`}
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
              JD 匹配分析
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
          {/* idle / loading: 显示输入框 */}
          {(status === "idle" || status === "loading") && (
            <>
              <label className="block text-sm text-slate-400 mb-2">
                职位描述（JD）
              </label>
              <textarea
                value={jdText}
                onChange={(e) => setJdText(e.target.value)}
                placeholder="粘贴职位描述（JD）文本..."
                disabled={status === "loading"}
                rows={6}
                className="w-full px-3 py-2.5 text-sm text-slate-200
                  bg-white/5 border border-white/10 rounded-lg
                  placeholder:text-slate-600
                  focus:outline-none focus:border-indigo-500/50
                  resize-y disabled:opacity-50
                  transition-colors"
              />
              <button
                onClick={handleMatch}
                disabled={status === "loading" || !jdText.trim()}
                className="mt-3 inline-flex items-center gap-1.5 px-4 py-2
                  text-sm font-medium rounded-lg
                  bg-linear-to-r from-indigo-500 to-purple-600
                  text-white
                  hover:brightness-110 hover:shadow-lg hover:shadow-indigo-500/25
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
              <div
                className="text-sm text-slate-300 leading-relaxed whitespace-pre-wrap"
                aria-live="polite"
              >
                {result}
              </div>
              <button
                onClick={() => {
                  setStatus("idle");
                  setResult("");
                }}
                className="mt-4 inline-flex items-center gap-1.5 px-3 py-1.5
                  text-xs font-medium rounded-lg
                  bg-white/5 border border-white/10
                  text-slate-400 hover:text-slate-200
                  active:scale-[0.98] motion-reduce:active:scale-100
                  transition-all cursor-pointer"
              >
                重新输入
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
