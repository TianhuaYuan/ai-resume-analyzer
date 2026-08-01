import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { getCachedProgress } from "../stores/progressStore";

interface Props {
  open: boolean;
  resumeFilename: string;
  resumeId: number;
  onClose: () => void;
}

type ProgressInfo = {
  completed: number;
  total: number;
  current_type: string;
  current_type_label: string;
};

const ANALYSIS_TYPES: { key: string; label: string }[] = [
  { key: "summary", label: "总结" },
  { key: "skills", label: "技能" },
  { key: "experience", label: "经历" },
  { key: "score", label: "评分" },
];

export default function AnalysisWaitingDialog({
  open,
  resumeFilename,
  resumeId,
  onClose,
}: Props) {
  // 从全局缓存读取最新进度（WS 事件实时写入），零网络延迟
  const cached = getCachedProgress(resumeId);
  const [progress, setProgress] = useState<ProgressInfo | null>(cached ?? null);
  const [completed, setCompleted] = useState(false);

  // 渲染阶段即算出显示值：progress > 全局缓存 > 打开时的占位 > null
  let displayProgress: ProgressInfo | null = progress ?? cached ?? null;
  if (displayProgress === null && open) {
    displayProgress = {
      completed: 0,
      total: 4,
      current_type: "pending",
      current_type_label: "",
    };
  }
  const displayCompleted = completed;

  // 监听实时进度事件
  useEffect(() => {
    if (!open) return;
    const handleProgress = (e: Event) => {
      const detail = (e as CustomEvent).detail;
      if (detail?.resume_id === resumeId) {
        setProgress({
          completed: detail.completed,
          total: detail.total,
          current_type: detail.current_type,
          current_type_label: detail.current_type_label,
        });
      }
    };
    window.addEventListener("resume:analysis-progress", handleProgress as EventListener);
    return () => window.removeEventListener("resume:analysis-progress", handleProgress as EventListener);
  }, [open, resumeId]);

  // 监听完成事件
  useEffect(() => {
    if (!open) return;
    const handleComplete = (e: Event) => {
      const detail = (e as CustomEvent).detail;
      if (detail?.resume_id === resumeId) {
        setProgress({ completed: 4, total: 4, current_type: "", current_type_label: "" });
        setCompleted(true);
      }
    };
    window.addEventListener("resume:analysis-complete", handleComplete as EventListener);
    return () => window.removeEventListener("resume:analysis-complete", handleComplete as EventListener);
  }, [open, resumeId]);

  // 重置状态
  useEffect(() => {
    if (open) {
      const cached = getCachedProgress(resumeId);
      setProgress(cached ?? { completed: 0, total: 4, current_type: "pending", current_type_label: "" });
      setCompleted(false);
    }
  }, [open]);

  // 轮询兜底
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    const poll = async () => {
      while (!cancelled) {
        await new Promise((r) => setTimeout(r, 5000));
        if (cancelled) break;
        try {
          const { getAnalysisStatus } = await import("../api/resumes");
          const status = await getAnalysisStatus(resumeId);
          if (status.has_cache) {
            setProgress({ completed: 4, total: 4, current_type: "", current_type_label: "" });
            return;
          }
          if (status.cached_types.length > 0) {
            setProgress({
              completed: status.cached_types.length,
              total: 4,
              current_type: status.cached_types[status.cached_types.length - 1] || "",
              current_type_label: "",
            });
          }
        } catch {}
      }
    };
    poll();
    return () => { cancelled = true; };
  }, [open, resumeId]);

  // 超时兜底
  useEffect(() => {
    if (!open) return;
    const timer = setTimeout(() => {
      if (!displayProgress || (displayProgress.completed === 0 && !displayCompleted)) {
        onClose();
      }
    }, 30000);
    return () => clearTimeout(timer);
  }, [open, displayProgress, displayCompleted, onClose]);

  const completedCount = displayProgress?.completed ?? 0;
  const percent = displayProgress ? Math.round((completedCount / displayProgress.total) * 100) : 0;

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4"
          onClick={onClose}
        >
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 20 }}
            transition={{ duration: 0.2 }}
            className="w-full max-w-sm bg-[var(--color-bg)] border border-[var(--color-border)] rounded-2xl shadow-2xl overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="p-6 space-y-5">
              <div className="text-center space-y-1">
                <p className="text-base font-semibold text-[var(--color-text)]">
                  AI 正在分析简历
                </p>
                <p className="text-xs text-[var(--color-text-muted)] truncate px-4">
                  {resumeFilename}
                </p>
              </div>

              <div className="space-y-1.5">
                <div className="flex justify-between text-xs">
                  <span className="text-[var(--color-text-secondary)]">总体进度</span>
                  <span className="text-[var(--color-text)] font-medium tabular-nums">{percent}%</span>
                </div>
                <div className="h-2 bg-[var(--color-border)] rounded-full overflow-hidden">
                  <motion.div
                    className="h-full bg-[var(--color-text)] rounded-full"
                    initial={{ width: 0 }}
                    animate={{ width: `${percent}%` }}
                    transition={{ duration: 0.3 }}
                  />
                </div>
              </div>

              <div className="space-y-2">
                {ANALYSIS_TYPES.map((t, i) => {
                  const isCompleted = i < completedCount;
                  const isCurrent = i === completedCount && displayProgress !== null;
                  const isPending = i > completedCount || (i === completedCount && displayProgress === null);

                  return (
                    <div
                      key={t.key}
                      className={`flex items-center gap-3 px-3 py-2 rounded-lg text-sm
                        ${isCompleted ? "text-emerald-400" : ""}
                        ${isCurrent ? "text-[var(--color-text)] bg-[var(--color-bg-secondary)]" : ""}
                        ${isPending ? "text-[var(--color-text-muted)]" : ""}
                      `}
                    >
                      <div className="w-5 h-5 flex items-center justify-center shrink-0">
                        {isCompleted ? (
                          <svg className="w-4 h-4" viewBox="0 0 16 16" fill="none">
                            <circle cx="8" cy="8" r="7" stroke="currentColor" strokeWidth="1.5" />
                            <path d="M5 8l2 2 4-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                          </svg>
                        ) : isCurrent ? (
                          <div className="w-4 h-4 border-2 border-[var(--color-text)] border-t-transparent rounded-full animate-spin" />
                        ) : (
                          <div className="w-4 h-4 rounded-full border border-[var(--color-border)]" />
                        )}
                      </div>
                      <span className="flex-1">{t.label}</span>
                      {isCurrent && (
                        <span className="text-[10px] font-mono-label text-[var(--color-text-muted)]">
                          进行中
                        </span>
                      )}
                    </div>
                  );
                })}
              </div>

              <div className="text-center space-y-3">
                <p className="text-xs text-[var(--color-text-muted)]">
                  {displayCompleted
                    ? "当前的分析结果已完成，可点击分析功能查看"
                    : displayProgress
                    ? <span className="tabular-nums">{`已完成 ${completedCount}/${displayProgress.total} 项分析`}</span>
                    : "正在启动分析..."}
                </p>
                <button
                  onClick={onClose}
                  className="px-4 py-2 text-xs font-medium text-[var(--color-text-secondary)]
                    hover:text-[var(--color-text)] border border-[var(--color-border)]
                    rounded-lg transition-colors cursor-pointer"
                >
                  {displayCompleted ? "知道了" : "后台运行"}
                </button>
              </div>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
