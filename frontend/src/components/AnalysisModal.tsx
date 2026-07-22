import { useEffect, useRef, useState, useCallback } from "react";
import { X, ArrowClockwise, Download } from "@phosphor-icons/react";
import {
  analyzeResume,
  exportResume,
  type AnalysisType,
  type ScoreDetail,
} from "../api/resumes";

interface AnalysisModalProps {
  resumeId: number;
  resumeFilename: string;
  open: boolean;
  onClose: () => void;
}

const TABS: { key: AnalysisType; label: string }[] = [
  { key: "summary", label: "总结" },
  { key: "skills", label: "技能" },
  { key: "experience", label: "经历" },
  { key: "score", label: "评分" },
];

type Status = "loading" | "error" | "success";

function ScoreBar({ label, value }: { label: string; value: number }) {
  const color =
    value >= 80 ? "bg-emerald-500" : value >= 60 ? "bg-yellow-500" : "bg-red-500";
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-xs">
        <span className="text-slate-400">{label}</span>
        <span className="text-slate-200 font-medium">{value}/100</span>
      </div>
      <div className="h-2 rounded-full bg-white/8 overflow-hidden">
        <div
          className={`h-full rounded-full ${color} transition-all`}
          style={{ width: `${value}%` }}
        />
      </div>
    </div>
  );
}

export default function AnalysisModal({
  resumeId,
  resumeFilename,
  open,
  onClose,
}: AnalysisModalProps) {
  const [activeTab, setActiveTab] = useState<AnalysisType>("summary");
  const [status, setStatus] = useState<Status>("loading");
  const [result, setResult] = useState("");
  const [scores, setScores] = useState<ScoreDetail | null>(null);
  const [error, setError] = useState("");
  const cancelledRef = useRef(false);

  const load = useCallback(
    async (type: AnalysisType) => {
      cancelledRef.current = false;
      setStatus("loading");
      setError("");
      setScores(null);
      try {
        const res = await analyzeResume(resumeId, type);
        if (cancelledRef.current) return;
        setResult(res.analysis);
        setScores(res.scores);
        setStatus("success");
      } catch (err: unknown) {
        if (cancelledRef.current) return;
        setError(err instanceof Error ? err.message : "分析失败");
        setStatus("error");
      }
    },
    [resumeId]
  );

  useEffect(() => {
    if (!open) return;
    setActiveTab("summary");
    setStatus("loading");
    setResult("");
    setScores(null);
    setError("");
    load("summary");
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

  const handleTabSwitch = (type: AnalysisType) => {
    if (type === activeTab) return;
    setActiveTab(type);
    load(type);
  };

  const handleRetry = () => load(activeTab);

  const handleOverlayClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if (e.target === e.currentTarget) onClose();
  };

  const handleExport = async () => {
    try {
      const md = await exportResume(resumeId, "markdown");
      const blob = new Blob([md], { type: "text/markdown;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `resume_${resumeId}_report.md`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch {
      // 导出失败静默处理，不影响分析体验
    }
  };

  if (!open) return null;

  return (
    <div
      onClick={handleOverlayClick}
      className="fixed inset-0 z-50 flex items-center justify-center
        bg-black/60 backdrop-blur-sm motion-reduce:backdrop-blur-none"
      role="dialog"
      aria-modal="true"
      aria-label={`简历分析: ${resumeFilename}`}
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
              简历分析
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

        {/* Tab 栏 */}
        <div className="flex border-b border-white/8 shrink-0">
          {TABS.map((t) => {
            const active = t.key === activeTab;
            return (
              <button
                key={t.key}
                onClick={() => handleTabSwitch(t.key)}
                className={`flex-1 px-4 py-3 text-sm font-medium
                  border-b-2 transition-colors cursor-pointer
                  active:scale-[0.98] motion-reduce:active:scale-100
                  ${
                    active
                      ? "text-slate-100 border-indigo-500"
                      : "text-slate-500 border-transparent hover:text-slate-300"
                  }`}
                aria-pressed={active}
              >
                {t.label}
              </button>
            );
          })}
        </div>

        {/* 内容区 */}
        <div className="flex-1 overflow-y-auto px-6 py-5">
          {status === "loading" && (
            <div className="space-y-3" aria-busy="true" aria-live="polite">
              <div className="h-4 rounded animate-skeleton" />
              <div className="h-4 rounded animate-skeleton w-11/12" />
              <div className="h-4 rounded animate-skeleton w-9/12" />
              <div className="h-4 rounded animate-skeleton w-10/12" />
              <div className="h-4 rounded animate-skeleton w-8/12" />
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

          {status === "success" && (
            <>
              {/* 评分 Tab：先显示分数条，再显示文字分析 */}
              {activeTab === "score" && scores && (
                <div className="mb-5 space-y-3">
                  <ScoreBar label="ATS 匹配率" value={scores.ats_match} />
                  <ScoreBar label="关键词覆盖率" value={scores.keyword_coverage} />
                  <ScoreBar label="技能密度" value={scores.skill_density} />
                  <ScoreBar label="综合评价" value={scores.overall} />
                </div>
              )}
              <div
                className="text-sm text-slate-300 leading-relaxed whitespace-pre-wrap"
                aria-live="polite"
              >
                {result}
              </div>
              {/* 导出按钮 */}
              <div className="mt-4 pt-4 border-t border-white/8 flex justify-end">
                <button
                  onClick={handleExport}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5
                    text-xs font-medium rounded-lg
                    bg-white/5 hover:bg-white/10
                    border border-white/10
                    text-slate-300
                    active:scale-[0.98] motion-reduce:active:scale-100
                    transition-all cursor-pointer"
                >
                  <Download size={14} weight="bold" aria-hidden="true" />
                  导出
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
