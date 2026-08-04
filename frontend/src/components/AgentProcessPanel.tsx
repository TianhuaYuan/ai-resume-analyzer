/**
 * AgentProcessPanel — 展示 Agent 推理过程的可折叠时间线组件。
 *
 * 流式期间：完整展开，实时显示每一步。
 * 流式完成后：自动折叠为紧凑头部（"思考过程 ∨" + 耗时），点击展开查看完整过程。
 * 思考片段（agent_thought）在渲染时自动合并为一条完整记录。
 */

import { memo, useState, useEffect, useRef, useMemo } from "react";
import {
  Wrench,
  CheckCircle,
  WarningCircle,
  Robot,
  Brain,
  CaretRight,
  CaretDown,
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

/** 格式化耗时 */
function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return s > 0 ? `${m}m ${s}s` : `${m}m`;
}

/**
 * 合并连续的 agent_thought 步骤为一条。
 * agent_thought 是文本流片段（如"你失业了"、"让我"、"再看一下..."），
 * 逐段显示没意义，应合并为一个完整的思考块。
 */
function mergeThoughtSteps(raw: AgentStep[]): AgentStep[] {
  const merged: AgentStep[] = [];
  for (const step of raw) {
    if (
      step.type === "agent_thought" &&
      merged.length > 0 &&
      merged[merged.length - 1].type === "agent_thought"
    ) {
      // 追加到上一条 thinking 的 detail 末尾
      const last = merged[merged.length - 1];
      merged[merged.length - 1] = {
        ...last,
        detail: (last.detail ?? "") + (step.detail ?? ""),
      };
    } else {
      merged.push({ ...step });
    }
  }
  return merged;
}

/** 单步渲染（memo：step 引用未变时跳过重渲染） */
const StepItem = memo(function StepItem({
  step,
  index,
  streaming,
}: {
  step: AgentStep;
  index: number;
  streaming: boolean;
}) {
  // 所有步骤默认展开：流式期间实时展示思考内容和工具调用，结束后也保持展开供用户阅读
  const [expanded, setExpanded] = useState(true);
  const hasDetail = step.detail && step.detail.length > 0;

  const config = {
    tool_call: {
      icon: Wrench,
      color: "text-brand",
      bg: "bg-brand/10",
      border: "border-brand/20",
      label: streaming
        ? `${getToolLabel(step.name)} 调用中...`
        : `调用 ${getToolLabel(step.name)}`,
    },
    tool_result: {
      icon: CheckCircle,
      color: "text-emerald-600",
      bg: "bg-emerald-500/10",
      border: "border-emerald-500/20",
      label: `${getToolLabel(step.name)} 完成`,
    },
    tool_error: {
      icon: WarningCircle,
      color: "text-red-500",
      bg: "bg-red-500/10",
      border: "border-red-500/20",
      label: `${getToolLabel(step.name)} 失败`,
    },
    agent_thought: {
      icon: Brain,
      color: "text-brand",
      bg: "bg-brand/10",
      border: "border-brand/20",
      label: "思考",
    },
    tool_stream: {
      icon: Wrench,
      color: "text-sky-600",
      bg: "bg-sky-500/10",
      border: "border-sky-500/20",
      label: `${getToolLabel(step.name)} 生成中`,
    },
  }[step.type];

  const Icon = config.icon;
  // 流式期间：思考内容始终展开不截断；工具调用/结果也展开
  // 流式结束后：思考保持展开（用户可折叠），工具步骤保持展开（用户可折叠）
  // 流式结束后点击标题行可整体折叠面板
  const showToggle = hasDetail && !streaming;

  return (
    <div className="flex gap-2.5">
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
          {showToggle && (
            <span className="ml-1 text-[var(--color-text-muted)]">
              {expanded ? "▲" : "▼"}
            </span>
          )}
        </button>
        {expanded && hasDetail && (
          <div
            className={`mt-1 p-2 rounded-lg bg-[var(--color-bg-secondary)] border border-[var(--color-border)] text-[11px] text-[var(--color-text-secondary)] leading-relaxed whitespace-pre-wrap break-words ${
              streaming
                ? "" // 流式期间不限高，内容完全展开实时可见
                : "max-h-40 overflow-y-auto" // 结束后限制高度，可内部滚动
            }`}
          >
            {step.detail}
          </div>
        )}
      </div>
    </div>
  );
});

export default function AgentProcessPanel({
  steps,
  streaming,
}: AgentProcessPanelProps) {
  const [expanded, setExpanded] = useState(true);
  const prevStreamingRef = useRef(streaming);
  const startTimeRef = useRef<number>(Date.now());
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const stepsContainerRef = useRef<HTMLDivElement>(null);

  // 合并连续的 agent_thought 步骤
  const displaySteps = useMemo(() => mergeThoughtSteps(steps), [steps]);

  // 计划进度（Magic-Resume ChatThread todos 卡对照：工具调用 = 清单项，结果/错误 = 已完成）
  const planProgress = useMemo(() => {
    const calls = steps.filter((s) => s.type === "tool_call").length;
    const done = steps.filter(
      (s) => s.type === "tool_result" || s.type === "tool_error"
    ).length;
    return {
      calls,
      done,
      pct: calls > 0 ? Math.min(100, Math.round((done / calls) * 100)) : 0,
    };
  }, [steps]);

  // 流式期间：步骤列表自动滚到底部，让用户始终看到最新步骤
  useEffect(() => {
    if (!streaming) return;
    const el = stepsContainerRef.current;
    if (!el) return;
    requestAnimationFrame(() => {
      el.scrollTop = el.scrollHeight;
    });
  }, [displaySteps, streaming]);

  // 流式开始时记录起始时间
  useEffect(() => {
    if (streaming && !prevStreamingRef.current) {
      startTimeRef.current = Date.now();
      setElapsedSeconds(0);
    }
    prevStreamingRef.current = streaming;
  }, [streaming]);

  // 流式期间实时更新耗时
  useEffect(() => {
    if (!streaming) return;
    const timer = setInterval(() => {
      setElapsedSeconds(Math.floor((Date.now() - startTimeRef.current) / 1000));
    }, 1000);
    return () => clearInterval(timer);
  }, [streaming]);

  // 流式完成时自动折叠，计算最终耗时
  useEffect(() => {
    if (!streaming && prevStreamingRef.current) {
      setElapsedSeconds(Math.floor((Date.now() - startTimeRef.current) / 1000));
      setExpanded(false);
    }
  }, [streaming]);

  // 挂载时若流式已结束（如 agent_done 触发 id 变更导致组件重新挂载），
  // 直接折叠——避免展开闪烁
  useEffect(() => {
    if (!streaming && steps.length > 0) {
      setExpanded(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (steps.length === 0 && !streaming) return null;

  // ── 流式完成后：紧凑折叠头部 ──
  if (!streaming && steps.length > 0 && !expanded) {
    return (
      <div className="mb-2">
        <button
          onClick={() => setExpanded(true)}
          className="flex items-center gap-2 text-xs text-[var(--color-text-muted)] hover:text-[var(--color-text-secondary)] transition-colors cursor-pointer"
        >
          <CaretRight size={12} weight="bold" className="shrink-0" />
          <span className="font-medium">思考过程</span>
          <span className="text-[10px] tabular-nums text-[var(--color-text-muted)]">
            {displaySteps.length} 步{elapsedSeconds > 0 ? ` · ${formatDuration(elapsedSeconds)}` : ""}
          </span>
        </button>
      </div>
    );
  }

  // ── 流式期间或展开后：完整面板 ──
  return (
    <div className="glass-card mb-3 p-3">
      {/* 标题行 */}
      <div className="flex items-center justify-between">
        <button
          onClick={() => !streaming && steps.length > 0 && setExpanded(false)}
          className={`flex items-center gap-2 ${!streaming && steps.length > 0 ? "cursor-pointer hover:opacity-80 transition-opacity" : ""}`}
        >
          {!streaming && steps.length > 0 && (
            <CaretDown size={12} weight="bold" className="text-[var(--color-text-muted)]" />
          )}
          {!streaming && steps.length > 0 ? (
            <span className="text-xs font-medium text-[var(--color-text-secondary)]">思考过程</span>
          ) : (
            <>
              <Robot size={14} weight="duotone" className="text-brand" aria-hidden="true" />
              <span className="text-xs font-semibold text-[var(--color-text-secondary)]">Agent 推理过程</span>
            </>
          )}
          {streaming && (
            <span className="inline-flex items-center gap-1 text-[10px] text-brand">
              <span className="inline-block w-1.5 h-1.5 rounded-full bg-brand animate-pulse" />
              进行中
            </span>
          )}
        </button>
        {!streaming && steps.length > 0 && elapsedSeconds > 0 && (
          <span className="text-[10px] text-[var(--color-text-muted)] tabular-nums">
            {formatDuration(elapsedSeconds)}
          </span>
        )}
      </div>

      {/* 计划进度（Magic-Resume todos 卡对照：工具清单 + 完成度进度条） */}
      {planProgress.calls > 0 && (
        <div className="mt-2.5">
          <div className="flex items-center justify-between mb-1">
            <span className="text-[10px] text-[var(--color-text-muted)]">
              工具执行计划
            </span>
            <span className="text-[10px] text-[var(--color-text-secondary)] tabular-nums">
              {planProgress.done}/{planProgress.calls} 完成
            </span>
          </div>
          <div className="h-1 rounded-full bg-[var(--color-bg-secondary)] overflow-hidden">
            <div
              className="h-full rounded-full bg-brand transition-all duration-500"
              style={{ width: `${planProgress.pct}%` }}
            />
          </div>
        </div>
      )}

      {/* 步骤列表（流式期间可滚动，自动滚到底部展示最新步骤） */}
      <div
        ref={stepsContainerRef}
        className={`mt-2 space-y-0 ${
          streaming ? "max-h-[60vh] overflow-y-auto" : ""
        }`}
      >
        {displaySteps.length > 0 ? (
          displaySteps.map((step, i) => (
            <StepItem key={`${step.id ?? i}-${i}`} step={step} index={i} streaming={streaming} />
          ))
        ) : (
          <div className="flex items-center gap-2 text-xs text-[var(--color-text-muted)]">
            <span className="inline-block w-3 h-3 rounded-full border-2 border-brand border-t-transparent animate-spin" />
            等待 Agent 启动...
          </div>
        )}
      </div>
    </div>
  );
}
