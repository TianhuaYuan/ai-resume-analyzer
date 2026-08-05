/**
 * FieldAIMenu — 条目/字段级 AI 菜单（优化 / 改写）。
 *
 * 替代模块级 InlineAIPanel：作用于单条内容（如某条经历的 description），
 * 结果经 onApplyText 回填到该条字段。按需显示——仅在有 text 时渲染 Sparkle 入口。
 *
 * 布局约束：父容器（ModuleCard 身体）有 overflow-hidden 高度动画，absolute popover
 * 会被裁剪 → 菜单用 inline 展开（参与文档流），不用浮层。
 *
 * 交互：
 * - 点 Sparkle 展开菜单（优化 / 改写两个操作）
 * - 「优化」立即调用 aiOptimize，展示结果 + 使用/取消
 * - 「改写」展开指令输入 + 预设标签，调 aiRewrite
 */

import { useCallback, useState } from "react";
import { Sparkle, Check, X, PaperPlaneTilt, PencilSimple, MagicWand, Eyeglasses } from "@phosphor-icons/react";
import { useInlineAI } from "./useInlineAI";
import { REWRITE_PRESETS } from "./rewritePresets";
import { CheckIssueList } from "./CheckIssueList";
import type { AICheckIssue } from "../../api/builder";

interface FieldAIMenuProps {
  resumeId: number;
  /** 模块类型（透传给后端，用于 prompt 上下文） */
  moduleType: string;
  /** 待处理文本（如单条 description） */
  text: string;
  /** 禁用（如内容为空） */
  disabled?: boolean;
  /** 应用 AI 结果到目标字段 */
  onApplyText: (newText: string) => void;
}

export function FieldAIMenu({
  resumeId,
  moduleType,
  text,
  disabled = false,
  onApplyText,
}: FieldAIMenuProps) {
  const { loading, error, optimize, check, rewrite } = useInlineAI(resumeId, moduleType);
  const [open, setOpen] = useState(false);
  const [rewriteOpen, setRewriteOpen] = useState(false);
  const [instruction, setInstruction] = useState("");
  const [result, setResult] = useState("");
  const [issues, setIssues] = useState<AICheckIssue[]>([]);
  /** 是否执行过检查（区分「未检查」与「检查后无问题」两个空态） */
  const [checked, setChecked] = useState(false);

  const toggleOpen = useCallback(() => {
    if (open) {
      // 关闭时重置子状态
      setRewriteOpen(false);
      setInstruction("");
      setResult("");
      setIssues([]);
      setChecked(false);
    }
    setOpen(!open);
  }, [open]);

  /** 优化：立即请求 */
  const handleOptimize = useCallback(async () => {
    setIssues([]);
    setChecked(false);
    const res = await optimize(text);
    if (res) setResult(res.optimized_text);
  }, [optimize, text]);

  /** 检查：立即请求，结果展示问题列表 */
  const handleCheck = useCallback(async () => {
    setResult("");
    const res = await check(text);
    if (res) {
      setIssues(res.issues);
      setChecked(true);
    }
  }, [check, text]);

  /** 改写：带指令请求 */
  const handleRewrite = useCallback(
    async (inst?: string) => {
      const finalInst = (inst ?? instruction).trim();
      if (!finalInst) return;
      setIssues([]);
      setChecked(false);
      const res = await rewrite(text, finalInst);
      if (res) {
        setResult(res.rewritten_text);
        setRewriteOpen(false);
      }
    },
    [rewrite, text, instruction],
  );

  const handleApply = useCallback(() => {
    if (result) onApplyText(result);
    toggleOpen();
  }, [result, onApplyText, toggleOpen]);

  return (
    <div>
      {/* Sparkle 入口按钮 */}
      <button
        onClick={(e) => {
          e.stopPropagation();
          toggleOpen();
        }}
        disabled={disabled}
        className={`shrink-0 p-1 rounded transition-all cursor-pointer
          ${open
            ? "text-brand bg-brand/10"
            : "text-[var(--color-text-muted)] hover:text-brand hover:bg-brand/10"}
          disabled:opacity-30 disabled:cursor-not-allowed`}
        aria-label="AI 优化/改写此条内容"
        title="AI 优化/改写"
      >
        <Sparkle size={13} weight="fill" aria-hidden="true" />
      </button>

      {/* 展开菜单（inline，参与文档流） */}
      {open && (
        <div className="mt-2 p-2.5 rounded-xl bg-[var(--color-bg-secondary)] border border-[var(--color-border)] space-y-2">
          {/* 操作按钮：优化 / 检查 / 改写 */}
          <div className="flex items-center gap-1.5 flex-wrap">
            <button
              onClick={handleOptimize}
              disabled={loading}
              className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[10px] font-medium
                bg-brand/10 text-brand border border-brand/30 hover:brightness-125
                disabled:opacity-40 disabled:cursor-not-allowed transition-all cursor-pointer"
              aria-label="优化此条内容"
            >
              <MagicWand size={10} weight="bold" aria-hidden="true" />
              优化
            </button>
            <button
              onClick={handleCheck}
              disabled={loading}
              className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[10px] font-medium
                bg-emerald-500/10 text-emerald-600 border border-emerald-500/30 hover:brightness-110
                disabled:opacity-40 disabled:cursor-not-allowed transition-all cursor-pointer"
              aria-label="检查此条内容"
            >
              <Eyeglasses size={10} weight="bold" aria-hidden="true" />
              检查
            </button>
            <button
              onClick={() => setRewriteOpen((v) => !v)}
              disabled={loading}
              className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[10px] font-medium
                transition-all cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed
                ${rewriteOpen
                  ? "bg-brand/10 text-brand border border-brand/30"
                  : "text-[var(--color-text-muted)] hover:text-brand hover:bg-brand/10 border border-transparent"}`}
              aria-label="按指令改写此条内容"
            >
              <PencilSimple size={10} weight="bold" aria-hidden="true" />
              改写
            </button>
          </div>

          {/* 检查结果（问题列表；checked 区分「未检查」与「检查后无问题」） */}
          {!loading && checked && (
            <div className="pt-0.5">
              <CheckIssueList issues={issues} />
            </div>
          )}

          {/* 改写输入区 */}
          {rewriteOpen && (
            <div className="space-y-2">
              <div className="flex gap-1.5 items-start">
                <textarea
                  value={instruction}
                  onChange={(e) => setInstruction(e.target.value)}
                  placeholder="输入改写指令，或点下方标签..."
                  rows={2}
                  disabled={loading}
                  className="flex-1 px-2.5 py-1.5 rounded-lg text-xs text-[var(--color-text)]
                    bg-white border border-[var(--color-border)]
                    placeholder:text-[var(--color-text-muted)]
                    focus:outline-none focus:border-brand/40 focus:ring-2 focus:ring-brand/15
                    resize-none disabled:opacity-50 transition-all duration-150"
                  aria-label="改写指令"
                />
                <button
                  onClick={() => handleRewrite()}
                  disabled={loading || !instruction.trim()}
                  className="shrink-0 h-[30px] px-2.5 rounded-lg text-white text-[10px] font-medium
                    inline-flex items-center gap-1 bg-brand hover:bg-[#0077ed]
                    disabled:opacity-40 disabled:cursor-not-allowed transition-all cursor-pointer"
                  aria-label="执行改写"
                >
                  <PaperPlaneTilt size={10} weight="fill" aria-hidden="true" />
                  Go
                </button>
              </div>
              <div className="flex flex-wrap gap-1">
                {REWRITE_PRESETS.map((preset) => (
                  <button
                    key={preset}
                    onClick={() => handleRewrite(preset)}
                    disabled={loading}
                    className="px-2 py-0.5 rounded-full text-[10px] font-medium
                      text-brand bg-brand/10 border border-brand/20 hover:brightness-125
                      disabled:opacity-40 disabled:cursor-not-allowed transition-all cursor-pointer"
                    aria-label={`使用指令：${preset}`}
                  >
                    {preset}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* 加载 / 错误 */}
          {loading && (
            <div className="flex items-center gap-2 text-xs text-[var(--color-text-muted)]">
              <span
                className="inline-block w-3.5 h-3.5 rounded-full border-2 border-brand border-t-transparent animate-spin"
                aria-hidden="true"
              />
              处理中...
            </div>
          )}
          {!loading && error && (
            <div className="p-2 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-xs">
              {error}
            </div>
          )}

          {/* 结果 + 使用/取消 */}
          {!loading && result && (
            <div className="space-y-2">
              <div className="p-2.5 rounded-lg bg-white border border-[var(--color-border)]
                text-xs text-[var(--color-text)] leading-relaxed whitespace-pre-wrap break-words max-h-40 overflow-y-auto">
                {result}
              </div>
              <div className="flex items-center justify-end gap-1.5">
                <button
                  onClick={toggleOpen}
                  className="px-2.5 py-1 rounded-lg text-[10px] font-medium border border-[var(--color-border)]
                    text-[var(--color-text-secondary)] hover:text-[var(--color-text)] hover:bg-white
                    transition-all cursor-pointer"
                  aria-label="取消"
                >
                  <X size={10} weight="bold" className="inline mr-0.5" aria-hidden="true" />
                  取消
                </button>
                <button
                  onClick={handleApply}
                  className="px-2.5 py-1 rounded-lg text-[10px] font-medium text-white bg-brand hover:bg-[#0077ed]
                    inline-flex items-center gap-1 transition-all cursor-pointer"
                  aria-label="使用 AI 结果"
                >
                  <Check size={10} weight="bold" aria-hidden="true" />
                  使用
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
