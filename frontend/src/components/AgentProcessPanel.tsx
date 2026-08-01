/**
 * T18: AgentProcessPanel — 展示 Agent 推理过程的可折叠时间线组件。
 *
 * 在 MessageBubble 流式期间渲染，实时展示 Agent 的工具调用链：
 * agent_start → tool_call → tool_result/tool_error → agent_done
 *
 * 每个 step 可折叠展开查看参数/结果详情。
 */

import { useState } from "react";
import {
  Wrench,
  CheckCircle,
  WarningCircle,
  Robot,
  Brain,
} from "@phosphor-icons/react";
import type { AgentStep } from "../api/qa";

interface AgentProcessPanelProps {
  steps: AgentStep[];
  /** 是否正在流式（影响动画和提示文案） */
  streaming: boolean;
}

/** 工具名中文映射 */
const TOOL_LABELS: Record<string, string> = {
  search_resume: "检索简历",
  jd_match: "JD 匹配",
  diagnose_resume: "简历诊断",
  compare_resume: "简历对比",
  rewrite_section: "改写段落",
  translate_resume: "翻译简历",
  interview_q: "面试题生成",
  greeting_letter: "求职信",
  reply_question: "回复问题",
};

function getToolLabel(name: string): string {
  return TOOL_LABELS[name] ?? name;
}

/** 单步渲染 */
function StepItem({ step, index }: { step: AgentStep; index: number }) {
  const [expanded, setExpanded] = useState(false);
  const hasDetail = step.detail && step.detail.length > 0;

  const config = {
    tool_call: {
      icon: Wrench,
      color: "text-indigo-400",
      bg: "bg-indigo-500/8",
      border: "border-indigo-500/20",
      label: `调用 ${getToolLabel(step.name)}`,
    },
    tool_result: {
      icon: CheckCircle,
      color: "text-emerald-400",
      bg: "bg-emerald-500/8",
      border: "border-emerald-500/20",
      label: `${getToolLabel(step.name)} 完成`,
    },
    tool_error: {
      icon: WarningCircle,
      color: "text-red-400",
      bg: "bg-red-500/8",
      border: "border-red-500/20",
      label: `${getToolLabel(step.name)} 失败`,
    },
    agent_thought: {
      icon: Brain,
      color: "text-purple-400",
      bg: "bg-purple-500/8",
      border: "border-purple-500/20",
      label: "Agent 思考",
    },
  }[step.type];

  const Icon = config.icon;

  return (
    <div className="flex gap-2.5 animate-fade-in-up">
      {/* 时间线竖线 */}
      <div className="flex flex-col items-center shrink-0">
        <div
          className={`w-5 h-5 rounded-full ${config.bg} ${config.border} border flex items-center justify-center`}
        >
          <Icon size={11} weight="fill" className={config.color} aria-hidden="true" />
        </div>
        {index > 0 && (
          <div className="w-px flex-1 bg-[var(--color-border)] mt-0.5" />
        )}
      </div>

      {/* 内容 */}
      <div className="flex-1 min-w-0 pb-2">
        <button
          onClick={() => hasDetail && setExpanded((v) => !v)}
          disabled={!hasDetail}
          className={`text-xs font-medium ${config.color} ${
            hasDetail
              ? "cursor-pointer hover:opacity-80 transition-opacity"
              : "cursor-default"
          }`}
        >
          {config.label}
          {hasDetail && (
            <span className="ml-1 text-[var(--color-text-muted)]">
              {expanded ? "▲" : "▼"}
            </span>
          )}
        </button>
        {expanded && hasDetail && (
          <div className="mt-1 p-2 rounded-lg bg-black/20 border border-[var(--color-border)] text-[11px] text-[var(--color-text-secondary)] leading-relaxed whitespace-pre-wrap break-words max-h-40 overflow-y-auto">
            {step.detail}
          </div>
        )}
      </div>
    </div>
  );
}

export default function AgentProcessPanel({
  steps,
  streaming,
}: AgentProcessPanelProps) {
  if (steps.length === 0 && !streaming) return null;

  return (
    <div className="mb-3 p-3 rounded-xl bg-white/3 border border-[var(--color-border)]">
      {/* 标题行 */}
      <div className="flex items-center gap-2 mb-2.5">
        <Robot
          size={14}
          weight="duotone"
          className="text-indigo-400"
          aria-hidden="true"
        />
        <span className="text-xs font-semibold text-[var(--color-text-secondary)]">
          Agent 推理过程
        </span>
        {streaming && (
          <span className="inline-flex items-center gap-1 text-[10px] text-indigo-400">
            <span className="inline-block w-1.5 h-1.5 rounded-full bg-indigo-400 animate-pulse" />
            进行中
          </span>
        )}
        {!streaming && steps.length > 0 && (
          <span className="text-[10px] text-[var(--color-text-muted)]">
            {steps.length} 步
          </span>
        )}
      </div>

      {/* 步骤列表 */}
      {steps.length > 0 ? (
        <div className="space-y-0">
          {steps.map((step, i) => (
            <StepItem key={`${step.id ?? i}-${i}`} step={step} index={i} />
          ))}
        </div>
      ) : (
        <div className="flex items-center gap-2 text-xs text-[var(--color-text-muted)]">
          <span className="inline-block w-3 h-3 rounded-full border-2 border-indigo-400 border-t-transparent animate-spin" />
          等待 Agent 启动...
        </div>
      )}
    </div>
  );
}
