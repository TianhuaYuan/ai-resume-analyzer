/**
 * CheckIssueList — AI 检查问题列表（纯展示组件）。
 *
 * 自 InlineAIPanel check 模式抽出：loading / error / 空态「未发现问题」/ 问题列表。
 * 供静默纠错角标展开与未来其他入口复用。
 */

import { Check, Glasses } from "lucide-react";
import type { AICheckIssue } from "../../api/builder";

/** check 问题严重度样式映射（颜色编码左边框 + 标签） */
const SEVERITY_STYLE: Record<
  AICheckIssue["severity"],
  { border: string; badge: string; label: string }
> = {
  high: {
    border: "border-l-danger",
    badge: "bg-danger/15 text-danger border border-danger/20",
    label: "高优先级",
  },
  medium: {
    border: "border-l-warning",
    badge: "bg-warning/15 text-warning border border-warning/20",
    label: "中优先级",
  },
  low: {
    border: "border-l-success",
    badge: "bg-success/15 text-success border border-success/20",
    label: "低优先级",
  },
};

interface CheckIssueListProps {
  issues: AICheckIssue[];
  /** 检查进行中（显示 spinner） */
  loading?: boolean;
  /** 错误信息（非空显示错误块） */
  error?: string;
}

export function CheckIssueList({ issues, loading = false, error = "" }: CheckIssueListProps) {
  if (loading) {
    return (
      <div className="flex items-center gap-2 text-xs text-[var(--color-text-muted)]">
        <span
          className="inline-block w-3.5 h-3.5 rounded-full border-2 border-brand border-t-transparent animate-spin"
          aria-hidden="true"
        />
        正在检查...
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-2.5 rounded-action bg-danger/10 border border-danger/20 text-danger text-xs">
        {error}
      </div>
    );
  }

  if (issues.length === 0) {
    return (
      <div className="flex items-center gap-2 p-3 rounded-action bg-success/10 border border-success/20 text-success text-xs">
        <Check size={14} strokeWidth={2.25} aria-hidden="true" />
        未发现问题，内容质量良好
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <p className="flex items-center gap-1 text-[10px] font-medium text-[var(--color-text-muted)] uppercase tracking-wider">
        <Glasses size={11} strokeWidth={2.25} aria-hidden="true" />
        智能检查结果
      </p>
      <ul className="space-y-2">
        {issues.map((issue, idx) => {
          const s = SEVERITY_STYLE[issue.severity];
          return (
            <li
              key={idx}
              className={`pl-3 pr-2 py-2 rounded-r-md border-l-2 ${s.border} bg-[var(--color-bg-secondary)]`}
            >
              <div className="flex items-center gap-2 mb-1 flex-wrap">
                <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${s.badge}`}>
                  {issue.category}
                </span>
                {issue.field && (
                  <span className="px-1.5 py-0.5 rounded text-[10px] font-medium
                    bg-[var(--color-border)]/40 text-[var(--color-text-secondary)]">
                    {issue.field}
                  </span>
                )}
                <span className="text-[10px] text-[var(--color-text-muted)]">{s.label}</span>
              </div>
              <p className="text-xs text-[var(--color-text-secondary)] leading-relaxed">
                {issue.description}
              </p>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
