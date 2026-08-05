/**
 * JDMatchReport — 简历×JD 匹配报告（复制自 Magic-Resume FitReportView 形态）。
 *
 * - 总分 hero + band 档位徽章（scoreBandKey 与 ScoreCard 同源）
 * - matched / missing 关键词 chips 分色（Magic-Resume KeywordChips 对照）
 * - gaps 低成本改进项列表（Magic-Resume fit-report.gaps 对照）
 * - 导出差距清单（一键复制 + CareerCoach 学习路径引导）
 */
import { useState } from "react";
import { CheckCircle, WarningCircle, TrendUp, Export } from "@phosphor-icons/react";
import type { MatchJDResult } from "../api/resumes";
import { formatGapList, type GapExportContext } from "../lib/gapExport";
import { BAND_META, scoreBandKey } from "./ScoreCard";

interface JDMatchReportProps {
  result: MatchJDResult;
  /** 简历名称，用于导出清单的头部信息 */
  resumeName?: string;
  /** JD 文本片段，用于导出清单的头部信息 */
  jdSnippet?: string;
}

export default function JDMatchReport({ result, resumeName, jdSnippet }: JDMatchReportProps) {
  const scores = result.scores;
  const matched = result.matched_keywords ?? [];
  const missing = result.missing_keywords ?? [];
  const gaps = result.gaps ?? [];

  const [copied, setCopied] = useState(false);

  const handleCopyGapList = async () => {
    const ctx: GapExportContext = { resumeName, jdSnippet };
    const text = formatGapList(result, ctx);
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      // 降级 execCommand
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.left = "-9999px";
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="space-y-4">
      {/* 总分 + 档位徽章（FitReportView 对照） */}
      <div className="flex items-center gap-4">
        {scores ? (
          <div className="flex items-center gap-3">
            <span className="text-4xl font-bold tabular-nums text-[var(--color-text)]">
              {scores.overall}
            </span>
            <span className="text-xs text-[var(--color-text-muted)]">/ 100</span>
            <span
              className={`px-2 py-0.5 rounded-full text-[11px] font-medium ${
                BAND_META[scoreBandKey(scores.overall)].className
              } bg-[var(--color-bg-secondary)]`}
            >
              {BAND_META[scoreBandKey(scores.overall)].label}
            </span>
          </div>
        ) : (
          <div className="flex items-center gap-2 text-xs text-[var(--color-text-muted)]">
            <TrendUp size={14} />
            未生成结构化评分
          </div>
        )}
      </div>

      {result.analysis && (
        <p className="text-xs text-[var(--color-text-secondary)] leading-relaxed">
          {result.analysis}
        </p>
      )}

      {/* 匹配/缺失关键词 chips（Magic-Resume KeywordChips 对照） */}
      {matched.length > 0 && (
        <div>
          <div className="flex items-center gap-1.5 mb-1.5">
            <CheckCircle size={13} className="text-emerald-400" weight="fill" />
            <span className="text-xs font-medium text-[var(--color-text-secondary)]">
              已匹配 ({matched.length})
            </span>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {matched.map((k) => (
              <span
                key={k}
                className="px-2 py-0.5 rounded-md text-[11px] bg-emerald-500/10 text-emerald-600 border border-emerald-500/20"
              >
                {k}
              </span>
            ))}
          </div>
        </div>
      )}

      {missing.length > 0 && (
        <div>
          <div className="flex items-center gap-1.5 mb-1.5">
            <WarningCircle size={13} className="text-rose-400" weight="fill" />
            <span className="text-xs font-medium text-[var(--color-text-secondary)]">
              缺失 ({missing.length})
            </span>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {missing.map((k) => (
              <span
                key={k}
                className="px-2 py-0.5 rounded-md text-[11px] bg-rose-500/10 text-rose-500 border border-rose-500/20"
              >
                {k}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* 低成本改进项（fit-report.gaps 对照） */}
      {gaps.length > 0 && (
        <div>
          <div className="flex items-center gap-1.5 mb-1.5">
            <TrendUp size={13} className="text-amber-400" />
            <span className="text-xs font-medium text-[var(--color-text-secondary)]">
              改进建议
            </span>
          </div>
          <ul className="space-y-1.5">
            {gaps.map((g) => (
              <li key={g} className="flex gap-2 text-xs text-[var(--color-text-secondary)] leading-relaxed">
                <span className="text-amber-400 shrink-0">›</span>
                <span>{g}</span>
              </li>
            ))}
          </ul>

          {/* 导出差距清单 + CareerCoach 引导 */}
          <div className="mt-3 pt-3 border-t border-[var(--color-border)]">
            <button
              onClick={() => void handleCopyGapList()}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium
                text-[var(--color-text-secondary)] bg-[var(--color-bg-secondary)]
                hover:bg-[#E5E5EA] active:scale-[0.98] transition-all cursor-pointer"
            >
              <Export size={12} weight="bold" aria-hidden="true" />
              {copied ? "已复制" : "导出差距清单"}
            </button>
            <p className="mt-2 text-[11px] text-[var(--color-text-muted)] leading-relaxed">
              下载{" "}
              <a
                href="https://github.com/AI-Engineer-Coder/career-coach-agent"
                target="_blank"
                rel="noopener noreferrer"
                className="underline underline-offset-2 hover:text-[var(--color-text-secondary)] transition-colors"
              >
                CareerCoach 桌面版
              </a>{" "}
              自动生成学习路径
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
