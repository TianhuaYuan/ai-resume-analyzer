/**
 * FieldAIMenu — 条目/字段级 AI 菜单（优化 / 检查 / 改写）。
 *
 * 三操作按钮直接平铺（不折叠），作用于单条内容（如某条经历的 description），
 * 结果经 onApplyText 回填到该条字段。
 *
 * 交互：
 * - 「优化」立即调用 aiOptimize，展示结果 + 使用/取消
 * - 「检查」调用 aiCheck，展示问题列表
 * - 「改写」展开指令输入 + 预设标签，调 aiRewrite
 */

import { useCallback, useState } from "react";
import { Check, X, Send, Pencil, TrendingUp, Glasses } from "lucide-react";
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
  const [rewriteOpen, setRewriteOpen] = useState(false);
  const [instruction, setInstruction] = useState("");
  const [result, setResult] = useState("");
  const [issues, setIssues] = useState<AICheckIssue[]>([]);
  /** 是否执行过检查（区分「未检查」与「检查后无问题」两个空态） */
  const [checked, setChecked] = useState(false);

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
    if (result) {
      onApplyText(result);
      setResult("");
      setIssues([]);
      setChecked(false);
    }
  }, [result, onApplyText]);

  return (
    <div className="space-y-2">
      {/* 操作按钮：优化 / 检查 / 改写（直接平铺，不折叠） */}
      <div className="flex items-center gap-1.5 flex-wrap">
        <button
          onClick={handleOptimize}
          disabled={disabled || loading}
          className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[10px] font-medium
            bg-brand/10 text-brand border border-brand/30 hover:brightness-125
            disabled:opacity-40 disabled:cursor-not-allowed transition-all cursor-pointer"
          aria-label="优化此条内容"
        >
          <TrendingUp size={10} strokeWidth={2.25} aria-hidden="true" />
          优化
        </button>
        <button
          onClick={handleCheck}
          disabled={disabled || loading}
          className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[10px] font-medium
            bg-success/10 text-success border border-success/30 hover:brightness-110
            disabled:opacity-40 disabled:cursor-not-allowed transition-all cursor-pointer"
          aria-label="检查此条内容"
        >
          <Glasses size={10} strokeWidth={2.25} aria-hidden="true" />
          检查
        </button>
        <button
          onClick={() => setRewriteOpen((v) => !v)}
          disabled={disabled || loading}
          className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[10px] font-medium
            transition-all cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed
            ${rewriteOpen
              ? "bg-brand/10 text-brand border border-brand/30"
              : "bg-sky-500/10 text-sky-600 border border-sky-500/30 hover:brightness-110"}`}
          aria-label="按指令改写此条内容"
        >
          <Pencil size={10} strokeWidth={2.25} aria-hidden="true" />
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
              className="flex-1 px-2.5 py-1.5 rounded-action text-xs text-[var(--color-text)]
                bg-white border border-[var(--color-border)]
                placeholder:text-[var(--color-text-muted)]
                focus:outline-none focus:border-brand/40 focus:ring-2 focus:ring-brand/15
                resize-none disabled:opacity-50 transition-all duration-150"
              aria-label="改写指令"
            />
            <button
              onClick={() => handleRewrite()}
              disabled={loading || !instruction.trim()}
              className="shrink-0 h-[30px] px-2.5 rounded-action text-white text-[10px] font-medium
                inline-flex items-center gap-1 bg-brand hover:bg-brand-hover
                disabled:opacity-40 disabled:cursor-not-allowed transition-all cursor-pointer"
              aria-label="执行改写"
            >
              <Send size={10} fill="currentColor" aria-hidden="true" />
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
        <div className="p-2 rounded-action bg-danger/10 border border-danger/20 text-danger text-xs">
          {error}
        </div>
      )}

      {/* 结果 + 使用/取消（固定高度，避免内容长度变化导致布局跳动） */}
      {!loading && result && (
        <div className="space-y-2">
          <div className="p-2.5 rounded-action bg-white border border-[var(--color-border)]
            text-xs text-[var(--color-text)] leading-relaxed whitespace-pre-wrap break-words h-44 overflow-y-auto">
            {result}
          </div>
          <div className="flex items-center justify-end gap-1.5">
            <button
              onClick={() => {
                setResult("");
                setRewriteOpen(false);
                setIssues([]);
                setChecked(false);
              }}
              className="px-2.5 py-1 rounded-action text-[10px] font-medium border border-[var(--color-border)]
                text-[var(--color-text-secondary)] hover:text-[var(--color-text)] hover:bg-white
                transition-all cursor-pointer"
              aria-label="取消"
            >
              <X size={10} strokeWidth={2.25} className="inline mr-0.5" aria-hidden="true" />
              取消
            </button>
            <button
              onClick={handleApply}
              className="px-2.5 py-1 rounded-action text-[10px] font-medium text-white bg-brand hover:bg-brand-hover
                inline-flex items-center gap-1 transition-all cursor-pointer"
              aria-label="使用 AI 结果"
            >
              <Check size={10} strokeWidth={2.25} aria-hidden="true" />
              使用
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
