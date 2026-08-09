import { useEffect, useRef } from "react";
import { Warning, X } from "@phosphor-icons/react";
import Spinner from "./ui/Spinner";

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  description: string;
  confirmText?: string;
  cancelText?: string;
  danger?: boolean;
  loading?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

/**
 * 通用确认弹窗。
 *
 * 用途：删除/清空等不可逆操作前的二次确认。
 *
 * P3-6：使用原生 &lt;dialog&gt; 元素，自动支持 focus trap（Tab 键循环）。
 *
 * 关闭方式（取消）：Esc / 点 backdrop / 点 X / 点取消按钮
 * 关闭方式（确认）：点确认按钮（loading 时禁用）
 */
export default function ConfirmDialog({
  open,
  title,
  description,
  confirmText = "确认",
  cancelText = "取消",
  danger = false,
  loading = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;

    if (open) {
      try {
        dialog.showModal();
      } catch {
        dialog.open = true;
      }
    } else {
      try {
        dialog.close();
      } catch {
        dialog.open = false;
      }
    }
  }, [open]);

  const handleClose = (e: React.MouseEvent<HTMLDialogElement>) => {
    e.preventDefault();
    if (!loading) onCancel();
  };

  const handleCancel = (e: React.FormEvent<HTMLDialogElement>) => {
    e.preventDefault();
    if (!loading) onCancel();
  };

  const confirmColor = danger
    ? "bg-danger-soft hover:bg-danger/25 text-danger border border-danger/40"
    : "bg-brand/10 hover:bg-brand/15 text-brand border border-brand/30";

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
      aria-label={title}
    >
      <div
        className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2
          bg-[var(--color-surface)] border border-[var(--color-border)] rounded-2xl
          max-w-md w-full mx-4 shadow-2xl
          animate-fade-in-up motion-reduce:animate-none"
      >
        <div className="flex items-start gap-3 px-6 py-5">
          <div
            className={`shrink-0 mt-0.5 p-2 rounded-lg
              ${danger ? "bg-danger-soft text-danger" : "bg-warning-soft text-warning"}`}
          >
            <Warning size={20} weight="bold" aria-hidden="true" />
          </div>
          <div className="flex-1 min-w-0">
            <h3 className="text-base font-semibold text-[var(--color-text)]">{title}</h3>
            <p className="text-sm text-[var(--color-text-secondary)] mt-1.5 leading-relaxed whitespace-pre-line">
              {description}
            </p>
          </div>
          <button
            onClick={() => !loading && onCancel()}
            aria-label="关闭"
            disabled={loading}
            className="p-1.5 rounded-lg text-[var(--color-text-secondary)]
              hover:text-[var(--color-text)] hover:bg-[var(--color-bg-secondary)]
              active:scale-[0.95] motion-reduce:active:scale-100
              transition-all cursor-pointer shrink-0
              disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <X size={16} weight="bold" aria-hidden="true" />
          </button>
        </div>

        <div className="flex items-center justify-end gap-2 px-6 py-4 border-t border-[var(--color-border)]">
          <button
            onClick={() => !loading && onCancel()}
            disabled={loading}
            className="px-3.5 py-1.5 text-sm font-medium rounded-lg
              text-[var(--color-text-secondary)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-secondary)]
              active:scale-[0.98] motion-reduce:active:scale-100
              transition-all cursor-pointer
              disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {cancelText}
          </button>
          <button
            onClick={() => !loading && onConfirm()}
            disabled={loading}
            className={`px-3.5 py-1.5 text-sm font-medium rounded-lg
              ${confirmColor}
              active:scale-[0.98] motion-reduce:active:scale-100
              transition-all cursor-pointer
              disabled:opacity-60 disabled:cursor-not-allowed
              flex items-center gap-1.5`}
          >
            {loading && (
              <span aria-hidden="true">
                <Spinner size={12} className="text-current" />
              </span>
            )}
            {confirmText}
          </button>
        </div>
      </div>
    </dialog>
  );
}
