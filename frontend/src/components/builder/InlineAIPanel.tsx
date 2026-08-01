/**
 * InlineAIPanel — UP 简历对齐的内联 AI 面板。
 *
 * 替代原有 BuilderAIChat 聊天面板，提供三种内联 AI 交互模式：
 * - optimize：一键优化（调用 aiOptimize，展示优化结果，可「使用」回填）
 * - check：智能检查（调用 aiCheck，展示问题列表，可「一键修复」→ 切到 optimize）
 * - rewrite：智能改写（输入指令或选预设标签，调用 aiRewrite，展示改写结果）
 *
 * 通过 mode props 控制显隐与当前模式（null = 不显示），结果经 onApply 回填到模块。
 * 组件用 memo 包裹导出，所有按钮带 aria-label，加载态禁用操作按钮。
 */

import { memo, useState, useEffect, useCallback, useRef } from "react";
import {
  Sparkle,
  Check,
  X,
  ArrowClockwise,
  PencilSimple,
  Eyeglasses,
  PaperPlaneTilt,
} from "@phosphor-icons/react";
import { aiOptimize, aiCheck, aiRewrite } from "../../api/builder";
import type { AICheckIssue } from "../../api/builder";

// ── Props ──────────────────────────────────────────────────────

interface InlineAIPanelProps {
  /** 简历 ID */
  resumeId: number;
  /** 当前模块类型（透传给后端） */
  moduleType: string;
  /** 当前模块的文本内容 */
  text: string;
  /** 当前激活的模式，null = 不显示 */
  mode: "optimize" | "check" | "rewrite" | null;
  /** 切换模式回调（null = 关闭面板） */
  onModeChange: (mode: "optimize" | "check" | "rewrite" | null) => void;
  /** 应用 AI 结果到模块 */
  onApply: (newText: string) => void;
}

// ── 常量 ────────────────────────────────────────────────────────

/** rewrite 预设指令标签（UP 简历对齐） */
const REWRITE_PRESETS = [
  "更简洁专业",
  "突出技术能力",
  "增加量化数据",
  "优化语言表达",
  "突出工作成果",
  "针对XX职位优化",
];

/** check 问题严重度样式映射（颜色编码左边框 + 标签） */
const SEVERITY_STYLE: Record<
  AICheckIssue["severity"],
  { border: string; badge: string; label: string }
> = {
  high: {
    border: "border-l-red-400",
    badge: "bg-red-500/15 text-red-400 border border-red-500/20",
    label: "高优先级",
  },
  medium: {
    border: "border-l-amber-400",
    badge: "bg-amber-500/15 text-amber-400 border border-amber-500/20",
    label: "中优先级",
  },
  low: {
    border: "border-l-emerald-400",
    badge: "bg-emerald-500/15 text-emerald-400 border border-emerald-500/20",
    label: "低优先级",
  },
};

/** 模式 → 标题文案 */
const TITLE: Record<Exclude<InlineAIPanelProps["mode"], null>, string> = {
  optimize: "一键优化",
  check: "智能检查",
  rewrite: "智能改写",
};

// ── 主组件 ──────────────────────────────────────────────────────

function InlineAIPanelImpl({
  resumeId,
  moduleType,
  text,
  mode,
  onModeChange,
  onApply,
}: InlineAIPanelProps) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [optimizedText, setOptimizedText] = useState("");
  const [issues, setIssues] = useState<AICheckIssue[]>([]);
  const [rewrittenText, setRewrittenText] = useState("");
  const [instruction, setInstruction] = useState("");

  /**
   * 竞态防护：每次发起新请求递增 reqId，回调据此判断结果是否已过期。
   * mode 切换 / 组件卸载 / rewrite 重新提交都会使在途请求失效。
   */
  const reqIdRef = useRef(0);

  /**
   * 最新请求参数快照。
   * 用 ref 而非直接依赖，避免编辑过程中 text 频繁变化重新触发 mode effect。
   */
  const paramsRef = useRef({ resumeId, text, moduleType });
  paramsRef.current = { resumeId, text, moduleType };

  // ── mode 变化：重置状态并按需自动发起请求 ───────────────────
  useEffect(() => {
    if (mode === null) return;

    // cancelled 为闭包变量：模式切换 / 卸载时 cleanup 置 true，使在途请求失效。
    // 不在 cleanup 里访问 ref.current（避免 react-hooks/exhaustive-deps 误报）。
    let cancelled = false;
    const myReqId = ++reqIdRef.current;
    const isActive = () => !cancelled && reqIdRef.current === myReqId;

    // 重置所有结果态
    setError("");
    setOptimizedText("");
    setIssues([]);
    setRewrittenText("");
    setInstruction("");

    // optimize / check 进入即自动请求；rewrite 等待用户输入
    if (mode === "optimize" || mode === "check") {
      setLoading(true);
      const { resumeId, text, moduleType } = paramsRef.current;
      const promise =
        mode === "optimize"
          ? aiOptimize(resumeId, text, moduleType)
          : aiCheck(resumeId, text, moduleType);

      promise
        .then((res) => {
          if (!isActive()) return;
          if ("optimized_text" in res) {
            setOptimizedText(res.optimized_text);
          } else {
            setIssues(res.issues);
          }
          setLoading(false);
        })
        .catch((err: unknown) => {
          if (!isActive()) return;
          setError(err instanceof Error ? err.message : "请求失败");
          setLoading(false);
        });
    } else {
      setLoading(false);
    }

    // 切换模式 / 卸载时使在途请求失效（防止 setState 落到已卸载/新模式）
    return () => {
      cancelled = true;
    };
    // 仅依赖 mode：text 等通过 paramsRef 读取，编辑不应重新触发请求
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode]);

  // ── rewrite 提交 ────────────────────────────────────────────
  const handleRewriteSubmit = useCallback(
    (inst?: string) => {
      const finalInst = (inst ?? instruction).trim();
      if (!finalInst) return;

      const myReqId = ++reqIdRef.current;
      const isActive = () => reqIdRef.current === myReqId;

      setLoading(true);
      setError("");
      setRewrittenText("");
      setInstruction(finalInst);

      const { resumeId, text, moduleType } = paramsRef.current;
      aiRewrite(resumeId, text, finalInst, moduleType)
        .then((res) => {
          if (!isActive()) return;
          setRewrittenText(res.rewritten_text);
          setLoading(false);
        })
        .catch((err: unknown) => {
          if (!isActive()) return;
          setError(err instanceof Error ? err.message : "改写失败");
          setLoading(false);
        });
    },
    [instruction],
  );

  // ── 操作回调 ────────────────────────────────────────────────
  const handleClose = useCallback(() => onModeChange(null), [onModeChange]);

  const handleApplyOptimize = useCallback(() => {
    if (optimizedText) onApply(optimizedText);
    onModeChange(null);
  }, [optimizedText, onApply, onModeChange]);

  const handleApplyRewrite = useCallback(() => {
    if (rewrittenText) onApply(rewrittenText);
    onModeChange(null);
  }, [rewrittenText, onApply, onModeChange]);

  // check「一键修复」→ 切到 optimize 模式（optimize effect 会自动用当前 text 发起优化）
  const handleFix = useCallback(() => onModeChange("optimize"), [onModeChange]);

  if (mode === null) return null;

  // ── 主题色：optimize = indigo，check/rewrite = purple ──────
  const isOptimize = mode === "optimize";
  const accentText = isOptimize ? "text-indigo-400" : "text-purple-400";
  const accentBorder = isOptimize ? "border-indigo-400" : "border-purple-400";
  const accentBg = isOptimize ? "bg-indigo-500/10" : "bg-purple-500/10";
  const accentRing = isOptimize
    ? "focus:ring-indigo-500/40 focus:border-indigo-500/50"
    : "focus:ring-purple-500/40 focus:border-purple-500/50";
  const accentBtn = isOptimize
    ? "bg-indigo-500 hover:bg-indigo-600"
    : "bg-purple-500 hover:bg-purple-600";

  // 标题图标：optimize=Sparkle / check=Eyeglasses / rewrite=PencilSimple
  const HeaderIcon = isOptimize
    ? Sparkle
    : mode === "check"
      ? Eyeglasses
      : PencilSimple;

  const loadingLabel =
    mode === "optimize" ? "正在优化..." : mode === "check" ? "正在检查..." : "正在改写...";

  // 底部操作栏是否显示（避免 rewrite 无结果时出现空栏 + 多余分割线）
  const showFooter =
    !loading &&
    !error &&
    ((mode === "optimize" && !!optimizedText) ||
      mode === "check" ||
      (mode === "rewrite" && !!rewrittenText));

  return (
    <div
      className="rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-secondary)]
        shadow-lg overflow-hidden animate-fade-in-up motion-reduce:animate-none"
      role="region"
      aria-label={TITLE[mode]}
    >
      {/* ── 标题栏 ── */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-[var(--color-border)]">
        <div className="flex items-center gap-2">
          <HeaderIcon size={14} weight="duotone" className={accentText} aria-hidden="true" />
          <h3 className="text-xs font-semibold text-[var(--color-text-secondary)] uppercase tracking-wider">
            {TITLE[mode]}
          </h3>
        </div>
        <button
          onClick={handleClose}
          className="p-1 rounded-md text-[var(--color-text-muted)]
            hover:text-[var(--color-text)] hover:bg-white/8 transition-all cursor-pointer"
          aria-label="关闭 AI 面板"
        >
          <X size={14} weight="bold" aria-hidden="true" />
        </button>
      </div>

      {/* ── 内容区（可滚动，防止长结果溢出模块卡片） ── */}
      <div className="px-4 py-3 space-y-3 max-h-[400px] overflow-y-auto">
        {/* optimize */}
        {mode === "optimize" && (
          <>
            {loading && (
              <div className="flex items-center gap-2 text-xs text-[var(--color-text-muted)]">
                <span
                  className={`inline-block w-3.5 h-3.5 rounded-full border-2 ${accentBorder} border-t-transparent animate-spin`}
                  aria-hidden="true"
                />
                {loadingLabel}
              </div>
            )}
            {!loading && error && (
              <div className="p-2.5 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-xs">
                {error}
              </div>
            )}
            {!loading && !error && optimizedText && (
              <div className="space-y-2">
                <p className="text-[10px] font-medium text-[var(--color-text-muted)] uppercase tracking-wider">
                  优化结果
                </p>
                <div className="p-3 rounded-lg bg-white/5 border border-[var(--color-border)]
                  text-sm text-[var(--color-text)] leading-relaxed whitespace-pre-wrap break-words">
                  {optimizedText}
                </div>
              </div>
            )}
          </>
        )}

        {/* check */}
        {mode === "check" && (
          <>
            {loading && (
              <div className="flex items-center gap-2 text-xs text-[var(--color-text-muted)]">
                <span
                  className={`inline-block w-3.5 h-3.5 rounded-full border-2 ${accentBorder} border-t-transparent animate-spin`}
                  aria-hidden="true"
                />
                {loadingLabel}
              </div>
            )}
            {!loading && error && (
              <div className="p-2.5 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-xs">
                {error}
              </div>
            )}
            {!loading && !error && (
              <div className="space-y-2">
                <p className="text-[10px] font-medium text-[var(--color-text-muted)] uppercase tracking-wider">
                  智能检查结果
                </p>
                {issues.length === 0 ? (
                  <div className="flex items-center gap-2 p-3 rounded-lg bg-emerald-500/10
                    border border-emerald-500/20 text-emerald-400 text-xs">
                    <Check size={14} weight="bold" aria-hidden="true" />
                    未发现问题，内容质量良好
                  </div>
                ) : (
                  <ul className="space-y-2">
                    {issues.map((issue, idx) => {
                      const s = SEVERITY_STYLE[issue.severity];
                      return (
                        <li
                          key={idx}
                          className={`pl-3 pr-2 py-2 rounded-r-md border-l-2 ${s.border} bg-white/5`}
                        >
                          <div className="flex items-center gap-2 mb-1">
                            <span
                              className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${s.badge}`}
                            >
                              {issue.category}
                            </span>
                            <span className="text-[10px] text-[var(--color-text-muted)]">
                              {s.label}
                            </span>
                          </div>
                          <p className="text-xs text-[var(--color-text-secondary)] leading-relaxed">
                            {issue.description}
                          </p>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </div>
            )}
          </>
        )}

        {/* rewrite */}
        {mode === "rewrite" && (
          <>
            {/* 输入框 + Go */}
            <div className="flex gap-2 items-start">
              <textarea
                value={instruction}
                onChange={(e) => setInstruction(e.target.value)}
                placeholder="输入改写指令，或点击下方标签..."
                rows={2}
                disabled={loading}
                className={`flex-1 px-3 py-2 rounded-lg text-xs text-[var(--color-text)]
                  bg-white/5 border border-[var(--color-border)]
                  placeholder:text-[var(--color-text-muted)]
                  focus:outline-none focus:ring-2 ${accentRing}
                  resize-none disabled:opacity-50 transition-all duration-150`}
                aria-label="改写指令"
              />
              <button
                onClick={() => handleRewriteSubmit()}
                disabled={loading || !instruction.trim()}
                className={`shrink-0 h-[34px] px-3 rounded-lg text-white text-xs font-medium
                  inline-flex items-center gap-1 ${accentBtn}
                  disabled:opacity-40 disabled:cursor-not-allowed transition-all cursor-pointer`}
                aria-label="执行改写"
              >
                <PaperPlaneTilt size={12} weight="fill" aria-hidden="true" />
                Go
              </button>
            </div>

            {/* 预设标签 */}
            <div className="flex flex-wrap gap-1.5">
              {REWRITE_PRESETS.map((preset) => (
                <button
                  key={preset}
                  onClick={() => handleRewriteSubmit(preset)}
                  disabled={loading}
                  className={`px-2.5 py-1 rounded-full text-[11px] font-medium border border-[var(--color-border)]
                    ${accentBg} ${accentText} hover:brightness-125
                    disabled:opacity-40 disabled:cursor-not-allowed transition-all cursor-pointer`}
                  aria-label={`使用指令：${preset}`}
                >
                  {preset}
                </button>
              ))}
            </div>

            {/* 改写加载 / 错误 / 结果 */}
            {loading && (
              <div className="flex items-center gap-2 text-xs text-[var(--color-text-muted)]">
                <span
                  className={`inline-block w-3.5 h-3.5 rounded-full border-2 ${accentBorder} border-t-transparent animate-spin`}
                  aria-hidden="true"
                />
                {loadingLabel}
              </div>
            )}
            {!loading && error && (
              <div className="p-2.5 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-xs">
                {error}
              </div>
            )}
            {!loading && !error && rewrittenText && (
              <div className="space-y-2 pt-1">
                <p className="text-[10px] font-medium text-[var(--color-text-muted)] uppercase tracking-wider">
                  改写结果
                </p>
                <div className="p-3 rounded-lg bg-white/5 border border-[var(--color-border)]
                  text-sm text-[var(--color-text)] leading-relaxed whitespace-pre-wrap break-words">
                  {rewrittenText}
                </div>
              </div>
            )}
          </>
        )}
      </div>

      {/* ── 底部操作栏 ── */}
      {showFooter && (
        <div className="flex items-center justify-end gap-2 px-4 py-3 border-t border-[var(--color-border)]">
          {/* optimize / rewrite：取消 + 使用 */}
          {((mode === "optimize" && optimizedText) ||
            (mode === "rewrite" && rewrittenText)) && (
            <>
              <button
                onClick={handleClose}
                className="px-3 py-1.5 rounded-lg text-xs font-medium border border-[var(--color-border)]
                  text-[var(--color-text-secondary)] hover:text-[var(--color-text)] hover:bg-white/8
                  transition-all cursor-pointer"
                aria-label="取消"
              >
                取消
              </button>
              <button
                onClick={mode === "optimize" ? handleApplyOptimize : handleApplyRewrite}
                className={`px-3 py-1.5 rounded-lg text-xs font-medium text-white inline-flex items-center gap-1.5
                  ${accentBtn} transition-all cursor-pointer`}
                aria-label="使用 AI 结果"
              >
                <Check size={12} weight="bold" aria-hidden="true" />
                使用
              </button>
            </>
          )}

          {/* check：忽略 + 一键修复 */}
          {mode === "check" && (
            <>
              <button
                onClick={handleClose}
                className="px-3 py-1.5 rounded-lg text-xs font-medium border border-[var(--color-border)]
                  text-[var(--color-text-secondary)] hover:text-[var(--color-text)] hover:bg-white/8
                  transition-all cursor-pointer"
                aria-label="忽略检查结果"
              >
                忽略
              </button>
              <button
                onClick={handleFix}
                className={`px-3 py-1.5 rounded-lg text-xs font-medium text-white inline-flex items-center gap-1.5
                  ${accentBtn} transition-all cursor-pointer`}
                aria-label="一键修复"
              >
                <ArrowClockwise size={12} weight="bold" aria-hidden="true" />
                一键修复
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}

export const InlineAIPanel = memo(InlineAIPanelImpl);
