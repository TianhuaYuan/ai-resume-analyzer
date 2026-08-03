import { useEffect, useRef, useState } from "react";
import { Sparkle, X } from "@phosphor-icons/react";

interface AIGenerateDialogProps {
  open: boolean;
  /** 模块类型标识，如 "experience"、"education" */
  moduleType: string;
  /** 模块中文标签，如 "工作经历"、"教育背景" */
  moduleLabel: string;
  /** 条目描述，如 "公司 A · 前端工程师"，为空时仅显示模块标签 */
  entryDescription?: string;
  /** 确认回调，返回用户填写的目标岗位和特殊要求 */
  onConfirm: (targetPosition: string, specialRequirements: string) => void;
  /** 取消回调 */
  onCancel: () => void;
}

/**
 * AI 生成预对话弹窗。
 *
 * 在 AI 生成模块内容之前，向用户收集上下文信息（目标岗位、特殊要求），
 * 以便生成更精准的简历内容。
 *
 * 使用原生 <dialog> 元素，自动支持 focus trap。
 *
 * 关闭方式：Esc / 点 backdrop / 点 X / 点取消按钮
 */
export default function AIGenerateDialog({
  open,
  moduleType: _moduleType,
  moduleLabel,
  entryDescription,
  onConfirm,
  onCancel,
}: AIGenerateDialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const positionInputRef = useRef<HTMLInputElement>(null);
  const [targetPosition, setTargetPosition] = useState("");
  const [specialRequirements, setSpecialRequirements] = useState("");

  // 打开/关闭 dialog
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;

    if (open) {
      try {
        dialog.showModal();
      } catch {
        dialog.open = true;
      }
      // 聚焦第一个输入框
      requestAnimationFrame(() => {
        positionInputRef.current?.focus();
      });
    } else {
      try {
        dialog.close();
      } catch {
        dialog.open = false;
      }
    }
  }, [open]);

  // Esc 关闭
  const handleCancel = (e: React.FormEvent<HTMLDialogElement>) => {
    e.preventDefault();
    onCancel();
  };

  // backdrop 点击关闭
  const handleClose = (e: React.MouseEvent<HTMLDialogElement>) => {
    e.preventDefault();
    onCancel();
  };

  const handleConfirm = () => {
    onConfirm(targetPosition.trim(), specialRequirements.trim());
    setTargetPosition("");
    setSpecialRequirements("");
  };

  // 显示内容描述：有 entryDescription 时 "模块标签 · 条目描述"，否则仅模块标签
  const contentLabel = entryDescription
    ? `${moduleLabel} · ${entryDescription}`
    : moduleLabel;

  if (!open) return null;

  return (
    <dialog
      ref={dialogRef}
      onCancel={handleCancel}
      onClose={handleClose}
      className="fixed inset-0 z-[60] m-0 w-full h-full p-0
        bg-black/30 backdrop-blur-sm motion-reduce:backdrop-blur-none"
      role="dialog"
      aria-modal="true"
      aria-label="AI 生成助手"
    >
      <div
        className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2
          bg-[var(--color-surface)] border border-[var(--color-border)] rounded-2xl
          max-w-md w-full mx-4 shadow-2xl
          animate-fade-in-up motion-reduce:animate-none"
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 pt-5 pb-2">
          <h3 className="text-base font-semibold text-[var(--color-text)] flex items-center gap-2">
            <Sparkle size={18} weight="fill" className="text-amber-400" aria-hidden="true" />
            AI 生成助手
          </h3>
          <button
            onClick={onCancel}
            aria-label="关闭"
            className="p-1.5 rounded-lg text-[var(--color-text-secondary)]
              hover:text-[var(--color-text)] hover:bg-[var(--color-bg-secondary)]
              active:scale-[0.95] motion-reduce:active:scale-100
              transition-all cursor-pointer shrink-0"
          >
            <X size={16} weight="bold" aria-hidden="true" />
          </button>
        </div>

        {/* Body */}
        <div className="px-6 pt-2 pb-4 space-y-4">
          {/* 内容描述（只读） */}
          <div>
            <label className="block text-sm font-medium text-[var(--color-text-secondary)] mb-1.5">
              你想生成什么内容？
            </label>
            <div
              className="px-3 py-2 text-sm text-[var(--color-text)] rounded-lg
                bg-[var(--color-bg-secondary)] border border-[var(--color-border)]"
            >
              {contentLabel}
            </div>
          </div>

          {/* 目标岗位 */}
          <div>
            <label
              htmlFor="ai-gen-position"
              className="block text-sm font-medium text-[var(--color-text-secondary)] mb-1.5"
            >
              目标岗位（可选）
            </label>
            <input
              ref={positionInputRef}
              id="ai-gen-position"
              type="text"
              value={targetPosition}
              onChange={(e) => setTargetPosition(e.target.value)}
              placeholder="如：高级前端工程师、全栈开发"
              className="w-full px-3 py-2 text-sm rounded-lg
                bg-[var(--color-bg-secondary)] border border-[var(--color-border)]
                text-[var(--color-text)] placeholder:text-[var(--color-text-secondary)]/50
                focus:outline-none focus:ring-2 focus:ring-brand/40 focus:border-brand/60
                transition-all"
            />
          </div>

          {/* 特殊要求 */}
          <div>
            <label
              htmlFor="ai-gen-requirements"
              className="block text-sm font-medium text-[var(--color-text-secondary)] mb-1.5"
            >
              特殊要求（可选）
            </label>
            <textarea
              id="ai-gen-requirements"
              value={specialRequirements}
              onChange={(e) => setSpecialRequirements(e.target.value)}
              placeholder="如：突出 React 经验、量化成果"
              rows={3}
              className="w-full px-3 py-2 text-sm rounded-lg resize-none
                bg-[var(--color-bg-secondary)] border border-[var(--color-border)]
                text-[var(--color-text)] placeholder:text-[var(--color-text-secondary)]/50
                focus:outline-none focus:ring-2 focus:ring-brand/40 focus:border-brand/60
                transition-all"
            />
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 px-6 py-4 border-t border-[var(--color-border)]">
          <button
            onClick={onCancel}
            className="px-3.5 py-1.5 text-sm font-medium rounded-lg
              text-[var(--color-text-secondary)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-secondary)]
              active:scale-[0.98] motion-reduce:active:scale-100
              transition-all cursor-pointer"
          >
            取消
          </button>
          <button
            onClick={handleConfirm}
            className="px-3.5 py-1.5 text-sm font-medium rounded-lg
              bg-brand/10 hover:bg-brand/15 text-brand border border-brand/30
              active:scale-[0.98] motion-reduce:active:scale-100
              transition-all cursor-pointer
              flex items-center gap-1.5"
          >
            <Sparkle size={14} weight="fill" aria-hidden="true" />
            开始生成
          </button>
        </div>
      </div>
    </dialog>
  );
}
