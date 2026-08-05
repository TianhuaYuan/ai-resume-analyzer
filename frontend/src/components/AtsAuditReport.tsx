import { useState } from "react";
import type { AtsAuditResult, AtsAuditIssue } from "../api/resumes";

interface AtsAuditReportProps {
  result: AtsAuditResult;
  onClose?: () => void;
}

/** 根据分数返回颜色 class */
function scoreColor(score: number): string {
  if (score >= 80) return "text-emerald-400";
  if (score >= 60) return "text-amber-400";
  return "text-red-400";
}

/** 根据分数返回描述 */
function scoreLabel(score: number): string {
  if (score >= 80) return "优秀";
  if (score >= 60) return "良好";
  if (score >= 40) return "需改进";
  return "问题较多";
}

/** 严重度 → 颜色/标签 */
function severityStyle(severity: string) {
  switch (severity) {
    case "high":
      return { badge: "bg-red-500/20 text-red-300", icon: "⚠", label: "严重" };
    case "medium":
      return { badge: "bg-amber-500/20 text-amber-300", icon: "●", label: "中等" };
    case "low":
      return { badge: "bg-emerald-500/20 text-emerald-300", icon: "ℹ", label: "轻微" };
    default:
      return { badge: "bg-gray-500/20 text-gray-300", icon: "•", label: severity };
  }
}

/** 问题类型中文名 */
function issueTypeName(type: string): string {
  const map: Record<string, string> = {
    garbled: "乱码文本",
    blank: "空白段",
    special_symbol: "特殊符号",
    image_text: "图片文字",
    table: "表格",
  };
  return map[type] || type;
}

function IssueCard({ issue }: { issue: AtsAuditIssue }) {
  const [expanded, setExpanded] = useState(false);
  const style = severityStyle(issue.severity);

  return (
    <div className="border border-[var(--color-border)] rounded-lg p-3 hover:bg-[var(--color-bg-secondary)] transition-colors">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full text-left flex items-start gap-2"
      >
        <span className={`inline-flex items-center justify-center w-5 h-5 rounded text-xs ${style.badge}`}>
          {style.icon}
        </span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-medium text-[var(--color-text)]">
              {issue.message}
            </span>
            <span className={`text-[10px] px-1.5 py-0.5 rounded ${style.badge}`}>
              {style.label}
            </span>
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-[var(--color-bg-tertiary)] text-[var(--color-text-secondary)]">
              {issueTypeName(issue.issue_type)}
            </span>
          </div>
          <div className="text-xs text-[var(--color-text-secondary)] mt-1">
            {issue.section}
          </div>
        </div>
        <span className="text-[var(--color-text-secondary)] text-xs shrink-0">
          {expanded ? "▲" : "▼"}
        </span>
      </button>

      {expanded && (
        <div className="mt-3 ml-7 space-y-2">
          <div className="text-sm text-[var(--color-text)]">
            <span className="font-medium">建议：</span>
            {issue.suggestion}
          </div>
          {issue.context && (
            <div className="text-xs text-[var(--color-text-secondary)] bg-[var(--color-bg-tertiary)] p-2 rounded font-mono">
              上下文：{issue.context}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function AtsAuditReport({ result, onClose }: AtsAuditReportProps) {
  const [activeSeverity, setActiveSeverity] = useState<string | null>(null);

  // 按 severity 分组
  const grouped = {
    high: result.issues.filter((i) => i.severity === "high"),
    medium: result.issues.filter((i) => i.severity === "medium"),
    low: result.issues.filter((i) => i.severity === "low"),
  };

  const filtered =
    activeSeverity === null
      ? result.issues
      : result.issues.filter((i) => i.severity === activeSeverity);

  return (
    <div className="w-full max-w-lg mx-auto">
      {/* Hero 分数区 */}
      <div className="text-center mb-6">
        <div className={`text-5xl font-bold ${scoreColor(result.ats_score)}`}>
          {result.ats_score}
        </div>
        <div className="text-sm text-[var(--color-text-secondary)] mt-1">
          ATS 可读性得分 / {scoreLabel(result.ats_score)}
        </div>

        {/* Method 徽章 */}
        <div className="flex items-center justify-center gap-2 mt-3">
          <span className="text-[10px] px-2 py-0.5 rounded-full bg-[var(--color-bg-tertiary)] text-[var(--color-text-secondary)]">
            检测方式：{result.method.toUpperCase()}
          </span>
          {!result.pdf_available && (
            <span className="text-[10px] px-2 py-0.5 rounded-full bg-amber-500/10 text-amber-400">
              WeasyPrint 不可用
            </span>
          )}
        </div>

        {/* 问题统计 */}
        <div className="flex items-center justify-center gap-4 mt-3 text-xs">
          {grouped.high.length > 0 && (
            <span className="text-red-400">
              {grouped.high.length} 严重
            </span>
          )}
          {grouped.medium.length > 0 && (
            <span className="text-amber-400">
              {grouped.medium.length} 中等
            </span>
          )}
          {grouped.low.length > 0 && (
            <span className="text-emerald-400">
              {grouped.low.length} 轻微
            </span>
          )}
        </div>
      </div>

      {/* Warnings */}
      {result.warnings.length > 0 && (
        <div className="mb-4 p-3 rounded-lg bg-amber-500/10 border border-amber-500/20">
          {result.warnings.map((w, idx) => (
            <div key={idx} className="text-xs text-amber-400">
              {w}
            </div>
          ))}
        </div>
      )}

      {/* 筛选标签 */}
      {result.issues.length > 0 && (
        <div className="flex items-center gap-2 mb-4">
          <button
            onClick={() => setActiveSeverity(null)}
            className={`text-xs px-3 py-1 rounded-full transition-colors ${
              activeSeverity === null
                ? "bg-[var(--color-accent)] text-white"
                : "bg-[var(--color-bg-tertiary)] text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-secondary)]"
            }`}
          >
            全部 ({result.issues.length})
          </button>
          {(["high", "medium", "low"] as const).map((sev) => {
            const count = grouped[sev].length;
            if (count === 0) return null;
            const s = severityStyle(sev);
            return (
              <button
                key={sev}
                onClick={() => setActiveSeverity(activeSeverity === sev ? null : sev)}
                className={`text-xs px-3 py-1 rounded-full transition-colors ${
                  activeSeverity === sev
                    ? s.badge
                    : "bg-[var(--color-bg-tertiary)] text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-secondary)]"
                }`}
              >
                {s.label} ({count})
              </button>
            );
          })}
        </div>
      )}

      {/* 问题列表 */}
      <div className="space-y-2">
        {filtered.length === 0 ? (
          <div className="text-center py-8 text-[var(--color-text-secondary)]">
            {result.issues.length === 0 ? (
              <>
                <div className="text-2xl mb-2">{"✔"}</div>
                <div className="text-sm">太棒了！没有检测到 ATS 兼容性问题</div>
              </>
            ) : (
              <div className="text-sm">当前筛选条件下无问题</div>
            )}
          </div>
        ) : (
          filtered.map((issue, idx) => <IssueCard key={idx} issue={issue} />)
        )}
      </div>

      {/* 关闭按钮 */}
      {onClose && (
        <div className="mt-6 text-center">
          <button
            onClick={onClose}
            className="px-6 py-2 rounded-lg bg-[var(--color-accent)] text-white text-sm hover:opacity-90 transition-opacity"
          >
            关闭
          </button>
        </div>
      )}
    </div>
  );
}
