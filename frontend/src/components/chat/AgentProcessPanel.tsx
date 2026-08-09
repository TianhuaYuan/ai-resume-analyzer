/**
 * AgentProcessPanel — 展示 Agent 推理过程的可折叠时间线组件。
 *
 * 流式期间：完整展开，实时显示每一步。
 * 流式完成后：自动折叠为紧凑头部（"思考过程 ∨" + 耗时），点击展开查看完整过程。
 * 思考片段（agent_thought）在渲染时自动合并为一条完整记录。
 */

import { memo, useState, useEffect, useRef, useMemo } from "react";
import { Wrench, CircleCheck, CircleAlert, MessagesSquare, BrainCircuit, ChevronRight, ChevronDown, LoaderCircle } from "lucide-react";
import type { AgentStep } from "../../api/qa";

interface AgentProcessPanelProps {
  steps: AgentStep[];
  /** 是否正在流式（影响动画和提示文案） */
  streaming: boolean;
}

/** 工具名中文映射 — 对齐 19 个真实工具名 */
const TOOL_LABELS: Record<string, string> = {
  search_resume: "检索简历",
  jd_match: "JD 匹配",
  diagnose_resume: "简历诊断",
  compare_resumes: "对比分析",
  rewrite_star: "STAR 改写",
  translate: "翻译",
  interview_coach: "面试教练",
  cover_letter: "求职信",
  answer_from_index: "知识库问答",
  search_assets: "资产检索",
  get_resume_content: "读取简历",
  save_memory: "保存记忆",
  recall_memory: "召回记忆",
  search_jobs_live: "实时岗位搜索",
  generate_module: "生成模块",
  check_module: "检查模块",
  modify_module: "修改模块",
  rewrite_resume: "重写简历",
  ask_info: "追问信息",
  web_search: "联网搜索",
  search_corpus: "面经知识库",
  negotiation_brief: "谈薪简报",
};

export function getToolLabel(name: string): string {
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
      // 保留原引用（不 spread）：agent_thought 高频刷新时，未变化的
      // tool_call / tool_result 等步骤引用不变，StepItem 的 memo 才能跳过重渲染
      merged.push(step);
    }
  }
  return merged;
}

/** 格式化耗时（毫秒 → 可读） */
function formatDurationMs(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  const s = ms / 1000;
  return s < 10 ? `${s.toFixed(1)}s` : `${Math.round(s)}s`;
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
  const [expanded, setExpanded] = useState(true);
  const [showArgs, setShowArgs] = useState(false);
  const [showResult, setShowResult] = useState(false);
  // G2: 思考内容（agent_thought）默认展开 —— 用户要求思考过程自动展开 + 实时滚动查看最新
  const [showThought, setShowThought] = useState(true);

  const hasDetail = step.detail && step.detail.length > 0;
  const isThought = step.type === "agent_thought";
  const hasArgs = step.args != null || (step.argsText != null && step.argsText.length > 0);
  const hasResult = step.result != null && step.result.length > 0;
  const hasDuration = step.durationMs != null && step.durationMs > 0;

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
      icon: CircleCheck,
      color: "text-success",
      bg: "bg-success/10",
      border: "border-success/20",
      label: `${getToolLabel(step.name)} 完成`,
    },
    tool_error: {
      icon: CircleAlert,
      color: "text-danger",
      bg: "bg-danger/10",
      border: "border-danger/20",
      label: `${getToolLabel(step.name)} 失败`,
    },
    agent_thought: {
      icon: BrainCircuit,
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
  const isRunning = streaming && step.status === "running";
  const showToggle = (hasDetail || hasArgs || hasResult) && !streaming;

  // 状态图标：running 时旋转，done 时勾，error 时叉
  const StatusIcon = isRunning ? LoaderCircle : step.status === "error" ? CircleAlert : null;

  return (
    <div className="flex gap-2.5">
      {/* 时间线竖线 */}
      <div className="flex flex-col items-center shrink-0">
        <div
          className={`w-5 h-5 rounded-full ${config.bg} ${config.border} border flex items-center justify-center`}
        >
          {isRunning ? (
            <LoaderCircle size={11} strokeWidth={2.25} className={`${config.color} animate-spin`} aria-hidden="true" />
          ) : (
            <Icon size={11} fill="currentColor" className={config.color} aria-hidden="true" />
          )}
        </div>
        {index > 0 && (
          <div className="w-px flex-1 bg-[var(--color-border)] mt-0.5" />
        )}
      </div>

      {/* 内容 */}
      <div className="flex-1 min-w-0 pb-2">
        <button
          onClick={() => {
            // G2: 思考步骤点击切换思考折叠；其余步骤切换整体展开
            if (isThought) {
              if (hasDetail) setShowThought((v) => !v);
            } else if (hasDetail || hasArgs || hasResult) {
              setExpanded((v) => !v);
            }
          }}
          disabled={!hasDetail && !hasArgs && !hasResult}
          className={`text-xs font-medium ${config.color} ${
            hasDetail || hasArgs || hasResult
              ? "cursor-pointer hover:opacity-80 transition-opacity"
              : "cursor-default"
          }`}
        >
          {config.label}
          {hasDuration && (
            <span className="ml-1.5 px-1.5 py-0 rounded text-[10px] font-normal tabular-nums bg-[var(--color-bg-secondary)] text-[var(--color-text-muted)] border border-[var(--color-border)]">
              {formatDurationMs(step.durationMs!)}
            </span>
          )}
          {StatusIcon && (
            <StatusIcon
              size={10}
              fill="currentColor"
              className={`ml-1 inline-block ${isRunning ? "animate-spin text-brand" : "text-danger"}`}
              aria-hidden="true"
            />
          )}
          {showToggle && (
            <span className="ml-1 text-[var(--color-text-muted)]">
              {isThought ? (showThought ? "▲" : "▼") : expanded ? "▲" : "▼"}
            </span>
          )}
        </button>

        {expanded && (
          <div className="mt-1 space-y-1">
            {/* 参数展示（tool_call 时） */}
            {hasArgs && showArgs && (
              <div className="p-2 rounded-action bg-[var(--color-bg-secondary)] border border-[var(--color-border)] text-[11px] text-[var(--color-text-secondary)]">
                <div className="flex items-center justify-between mb-1">
                  <span className="font-medium text-[var(--color-text-muted)]">参数</span>
                  <button
                    onClick={(e) => { e.stopPropagation(); setShowArgs(false); }}
                    className="text-[10px] text-[var(--color-text-muted)] hover:text-[var(--color-text-secondary)] cursor-pointer"
                  >
                    收起
                  </button>
                </div>
                <pre className="whitespace-pre-wrap break-words overflow-x-auto max-h-32 overflow-y-auto">
                  {step.argsText ?? JSON.stringify(step.args, null, 2)}
                </pre>
              </div>
            )}
            {/* 结果展示（tool_result 时） */}
            {hasResult && showResult && (
              <div className="p-2 rounded-action bg-[var(--color-bg-secondary)] border border-[var(--color-border)] text-[11px] text-[var(--color-text-secondary)]">
                <div className="flex items-center justify-between mb-1">
                  <span className="font-medium text-[var(--color-text-muted)]">结果</span>
                  <button
                    onClick={(e) => { e.stopPropagation(); setShowResult(false); }}
                    className="text-[10px] text-[var(--color-text-muted)] hover:text-[var(--color-text-secondary)] cursor-pointer"
                  >
                    收起
                  </button>
                </div>
                <pre className="whitespace-pre-wrap break-words overflow-x-auto max-h-32 overflow-y-auto">
                  {step.result}
                </pre>
              </div>
            )}
            {/* G2: 思考内容（agent_thought）→ 默认折叠的 Accordion，点击展开查看模型推理过程，
                流式期间亦默认折叠，避免推理过程抢占主屏 */}
            {isThought ? (
              hasDetail && (
                <div className="mt-1">
                  <button
                    onClick={(e) => { e.stopPropagation(); setShowThought((v) => !v); }}
                    className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded
                      bg-[var(--color-bg-secondary)] border border-[var(--color-border)]
                      text-[var(--color-text-muted)] hover:text-[var(--color-text-secondary)]
                      cursor-pointer transition-colors"
                    aria-expanded={showThought}
                  >
                    {showThought ? "收起思考" : "展开思考"}
                    <ChevronDown
                      size={10}
                      strokeWidth={2.25}
                      className={`transition-transform ${showThought ? "" : "-rotate-90"}`}
                      aria-hidden="true"
                    />
                  </button>
                  {showThought && (
                    // 流式期间不设 max-h：思考内容完整展开，由外层 stepsContainerRef（60vh 封顶）
                    // 负责内部滚动，保证"最新思考"随实时滚动可见；完成后恢复 40 行截断便于复盘
                    <div
                      className={`mt-1 p-2 rounded-action bg-[var(--color-bg-secondary)] border border-[var(--color-border)] text-[11px] text-[var(--color-text-secondary)] leading-relaxed whitespace-pre-wrap break-words ${
                        streaming ? "" : "max-h-40 overflow-y-auto"
                      }`}
                    >
                      {step.detail}
                    </div>
                  )}
                </div>
              )
            ) : hasDetail ? (
              /* detail 展示（原有逻辑，非思考步骤） */
              <div
                className={`p-2 rounded-action bg-[var(--color-bg-secondary)] border border-[var(--color-border)] text-[11px] text-[var(--color-text-secondary)] leading-relaxed whitespace-pre-wrap break-words ${
                  streaming
                    ? ""
                    : "max-h-40 overflow-y-auto"
                }`}
              >
                {step.detail}
              </div>
            ) : null}
            {/* 操作按钮：有 args/result 时显示展开/折叠按钮 */}
            {!streaming && (hasArgs || hasResult) && (
              <div className="flex gap-1.5">
                {hasArgs && !showArgs && (
                  <button
                    onClick={(e) => { e.stopPropagation(); setShowArgs(true); setExpanded(true); }}
                    className="text-[10px] px-1.5 py-0.5 rounded bg-[var(--color-bg-secondary)] border border-[var(--color-border)] text-[var(--color-text-muted)] hover:text-[var(--color-text-secondary)] cursor-pointer"
                  >
                    查看参数
                  </button>
                )}
                {hasResult && !showResult && (
                  <button
                    onClick={(e) => { e.stopPropagation(); setShowResult(true); setExpanded(true); }}
                    className="text-[10px] px-1.5 py-0.5 rounded bg-[var(--color-bg-secondary)] border border-[var(--color-border)] text-[var(--color-text-muted)] hover:text-[var(--color-text-secondary)] cursor-pointer"
                  >
                    查看结果
                  </button>
                )}
              </div>
            )}
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
          <ChevronRight size={12} strokeWidth={2.25} className="shrink-0" />
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
            <ChevronDown size={12} strokeWidth={2.25} className="text-[var(--color-text-muted)]" />
          )}
          {!streaming && steps.length > 0 ? (
            <span className="text-xs font-medium text-[var(--color-text-secondary)]">思考过程</span>
          ) : (
            <>
              <MessagesSquare size={14} fill="currentColor" className="text-brand" aria-hidden="true" />
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
