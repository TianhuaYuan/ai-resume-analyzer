import { memo, useEffect, useMemo, useRef, useState } from "react";
import {
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CircleAlert,
  LoaderCircle,
  ListChecks,
  Sparkles,
} from "lucide-react";
import type { AgentStep } from "../../api/qa";

interface AgentProcessPanelProps {
  steps: AgentStep[];
  streaming: boolean;
}

const TOOL_LABELS: Record<string, string> = {
  search_resume: "检索简历内容",
  jd_match: "分析岗位匹配度",
  diagnose_resume: "检查简历问题",
  compare_resumes: "对比简历版本",
  rewrite_star: "优化经历表述",
  translate: "翻译内容",
  interview_coach: "准备面试建议",
  cover_letter: "撰写求职信",
  answer_from_index: "查找相关依据",
  search_assets: "检索求职资料",
  get_resume_content: "读取简历内容",
  save_memory: "保存关键信息",
  recall_memory: "读取历史信息",
  search_jobs_live: "查找相关岗位",
  generate_module: "生成简历内容",
  check_module: "检查简历条目",
  modify_module: "修改简历条目",
  rewrite_resume: "重写简历",
  ask_info: "整理待补充信息",
  web_search: "检索公开资料",
  search_corpus: "检索面试资料",
  negotiation_brief: "整理谈薪建议",
};

/** 面向用户的名称。未知内部工具不直接暴露实现标识。 */
export function getToolLabel(name: string): string {
  return TOOL_LABELS[name] ?? "处理当前任务";
}

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const remaining = seconds % 60;
  return remaining > 0 ? `${minutes}m ${remaining}s` : `${minutes}m`;
}

function formatDurationMs(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  const seconds = ms / 1000;
  return seconds < 10 ? `${seconds.toFixed(1)}s` : `${Math.round(seconds)}s`;
}

/**
 * 原始 reasoning 可能包含模型内部推理、敏感上下文或不稳定片段。
 * UI 只保留“正在分析”这一可解释状态，不展示或缓存推理正文。
 */
function buildDisplaySteps(steps: AgentStep[]): AgentStep[] {
  const result: AgentStep[] = [];
  let thoughtAdded = false;

  for (const step of steps) {
    if (step.type === "agent_thought") {
      if (!thoughtAdded) {
        result.push({
          type: "agent_thought",
          name: "planning",
          id: "planning",
          status: step.status,
        });
        thoughtAdded = true;
      }
      continue;
    }
    result.push(step);
  }

  return result;
}

const StepItem = memo(function StepItem({
  step,
  index,
  streaming,
}: {
  step: AgentStep;
  index: number;
  streaming: boolean;
}) {
  const isRunning = streaming && step.status === "running";
  const hasDuration = step.durationMs != null && step.durationMs > 0;

  const config = {
    tool_call: {
      icon: LoaderCircle,
      iconClass: "text-brand",
      label: isRunning ? `${getToolLabel(step.name)}中` : getToolLabel(step.name),
    },
    tool_result: {
      icon: CheckCircle2,
      iconClass: "text-success",
      label: `${getToolLabel(step.name)}完成`,
    },
    tool_error: {
      icon: CircleAlert,
      iconClass: "text-danger",
      label: `${getToolLabel(step.name)}未完成`,
    },
    agent_thought: {
      icon: Sparkles,
      iconClass: "text-brand",
      label: streaming ? "正在分析需求" : "需求分析完成",
    },
    tool_stream: {
      icon: LoaderCircle,
      iconClass: "text-brand",
      label: `${getToolLabel(step.name)}中`,
    },
  }[step.type];

  const Icon = config.icon;
  const animate = isRunning || (streaming && step.type === "tool_stream");

  return (
    <div className="flex gap-2.5">
      <div className="flex flex-col items-center shrink-0">
        <div className="flex h-5 w-5 items-center justify-center rounded-full border border-[var(--color-border)] bg-[var(--color-bg-secondary)]">
          <Icon
            size={11}
            strokeWidth={2.25}
            className={`${config.iconClass} ${animate ? "animate-spin" : ""}`}
            aria-hidden="true"
          />
        </div>
        {index > 0 && <div className="mt-0.5 w-px flex-1 bg-[var(--color-border)]" />}
      </div>
      <div className="min-w-0 flex-1 pb-2">
        <span className="text-xs font-medium text-[var(--color-text-secondary)]">
          {config.label}
        </span>
        {hasDuration && (
          <span className="ml-1.5 rounded border border-[var(--color-border)] bg-[var(--color-bg-secondary)] px-1.5 text-[10px] tabular-nums text-[var(--color-text-muted)]">
            {formatDurationMs(step.durationMs!)}
          </span>
        )}
        {step.type === "tool_error" && (
          <p className="mt-1 text-[11px] text-[var(--color-text-muted)]">
            本步骤暂未完成，系统会继续尝试其他可用方案。
          </p>
        )}
      </div>
    </div>
  );
});

export default function AgentProcessPanel({ steps, streaming }: AgentProcessPanelProps) {
  const [expanded, setExpanded] = useState(true);
  const prevStreamingRef = useRef(streaming);
  const startTimeRef = useRef(Date.now());
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const stepsContainerRef = useRef<HTMLDivElement>(null);
  const displaySteps = useMemo(() => buildDisplaySteps(steps), [steps]);

  const progress = useMemo(() => {
    const calls = steps.filter((step) => step.type === "tool_call").length;
    const done = steps.filter(
      (step) => step.type === "tool_result" || step.type === "tool_error",
    ).length;
    return {
      calls,
      done,
      percent: calls > 0 ? Math.min(100, Math.round((done / calls) * 100)) : 0,
    };
  }, [steps]);

  useEffect(() => {
    if (!streaming) return;
    const element = stepsContainerRef.current;
    if (!element) return;
    requestAnimationFrame(() => {
      element.scrollTop = element.scrollHeight;
    });
  }, [displaySteps, streaming]);

  useEffect(() => {
    if (streaming && !prevStreamingRef.current) {
      startTimeRef.current = Date.now();
      setElapsedSeconds(0);
    }
    if (!streaming && prevStreamingRef.current) {
      setElapsedSeconds(Math.floor((Date.now() - startTimeRef.current) / 1000));
      setExpanded(false);
    }
    prevStreamingRef.current = streaming;
  }, [streaming]);

  useEffect(() => {
    if (!streaming) return;
    const timer = window.setInterval(() => {
      setElapsedSeconds(Math.floor((Date.now() - startTimeRef.current) / 1000));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [streaming]);

  useEffect(() => {
    if (!streaming && steps.length > 0) setExpanded(false);
    // Mount-time normalization for restored conversations.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (steps.length === 0 && !streaming) return null;

  if (!streaming && steps.length > 0 && !expanded) {
    return (
      <div className="mb-2">
        <button
          type="button"
          onClick={() => setExpanded(true)}
          className="flex items-center gap-2 text-xs text-[var(--color-text-muted)] transition-colors hover:text-[var(--color-text-secondary)]"
        >
          <ChevronRight size={12} strokeWidth={2.25} aria-hidden="true" />
          <span className="font-medium">执行记录</span>
          <span className="text-[10px] tabular-nums">
            {displaySteps.length} 步{elapsedSeconds > 0 ? ` · ${formatDuration(elapsedSeconds)}` : ""}
          </span>
        </button>
      </div>
    );
  }

  return (
    <section className="mb-3 rounded-input border border-[var(--color-border)] bg-[var(--color-surface)] p-3">
      <div className="flex items-center justify-between gap-3">
        <button
          type="button"
          onClick={() => !streaming && steps.length > 0 && setExpanded(false)}
          className="flex min-w-0 items-center gap-2 text-left"
        >
          {!streaming && steps.length > 0 ? (
            <ChevronDown size={12} strokeWidth={2.25} className="text-[var(--color-text-muted)]" />
          ) : (
            <ListChecks size={14} strokeWidth={2.25} className="text-brand" aria-hidden="true" />
          )}
          <span className="text-xs font-semibold text-[var(--color-text-secondary)]">
            执行进度
          </span>
          {streaming && (
            <span className="inline-flex items-center gap-1 text-[10px] text-brand">
              <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-brand" />
              进行中
            </span>
          )}
        </button>
        {!streaming && elapsedSeconds > 0 && (
          <span className="text-[10px] tabular-nums text-[var(--color-text-muted)]">
            {formatDuration(elapsedSeconds)}
          </span>
        )}
      </div>

      {progress.calls > 0 && (
        <div className="mt-2.5">
          <div className="mb-1 flex items-center justify-between text-[10px] text-[var(--color-text-muted)]">
            <span>任务进度</span>
            <span className="tabular-nums">{progress.done}/{progress.calls}</span>
          </div>
          <div className="h-1 overflow-hidden rounded-full bg-[var(--color-bg-secondary)]">
            <div
              className="h-full rounded-full bg-brand transition-all duration-500"
              style={{ width: `${progress.percent}%` }}
            />
          </div>
        </div>
      )}

      <div
        ref={stepsContainerRef}
        className={`mt-2 space-y-0 ${streaming ? "max-h-[45vh] overflow-y-auto" : ""}`}
      >
        {displaySteps.length > 0 ? (
          displaySteps.map((step, index) => (
            <StepItem
              key={`${step.id ?? step.type}-${index}`}
              step={step}
              index={index}
              streaming={streaming}
            />
          ))
        ) : (
          <div className="flex items-center gap-2 text-xs text-[var(--color-text-muted)]">
            <LoaderCircle size={12} className="animate-spin text-brand" aria-hidden="true" />
            正在准备任务…
          </div>
        )}
      </div>
    </section>
  );
}
