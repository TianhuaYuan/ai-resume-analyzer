import { useEffect } from "react";
import { Warning, X } from "@phosphor-icons/react";

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
 * 关闭方式（取消）：Esc / 点 overlay / 点 X / 点取消按钮
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
  // Esc 取消
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !loading) onCancel();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, loading, onCancel]);

  if (!open) return null;

  const handleOverlayClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if (e.target === e.currentTarget && !loading) onCancel();
  };

  const confirmColor = danger
    ? "bg-red-500/20 hover:bg-red-500/30 text-red-300 border border-red-500/40"
    : "bg-indigo-500/20 hover:bg-indigo-500/30 text-indigo-300 border border-indigo-500/40";

  return (
    <div
      onClick={handleOverlayClick}
      className="fixed inset-0 z-[60] flex items-center justify-center
        bg-black/60 backdrop-blur-sm motion-reduce:backdrop-blur-none"
      role="dialog"
      aria-modal="true"
      aria-label={title}
    >
      <div
        className="bg-[#1e293b] border border-white/10 rounded-2xl
          max-w-md w-full mx-4 shadow-2xl
          animate-fade-in-up motion-reduce:animate-none"
      >
        <div className="flex items-start gap-3 px-6 py-5">
          <div
            className={`shrink-0 mt-0.5 p-2 rounded-lg
              ${danger ? "bg-red-500/15 text-red-400" : "bg-amber-500/15 text-amber-400"}`}
          >
            <Warning size={20} weight="bold" aria-hidden="true" />
          </div>
          <div className="flex-1 min-w-0">
            <h3 className="text-base font-semibold text-slate-100">{title}</h3>
            <p className="text-sm text-slate-400 mt-1.5 leading-relaxed">
              {description}
            </p>
          </div>
          <button
            onClick={() => !loading && onCancel()}
            aria-label="关闭"
            disabled={loading}
            className="p-1.5 rounded-lg text-slate-400
              hover:text-slate-100 hover:bg-white/8
              active:scale-[0.95] motion-reduce:active:scale-100
              transition-all cursor-pointer shrink-0
              disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <X size={16} weight="bold" aria-hidden="true" />
          </button>
        </div>

        <div className="flex items-center justify-end gap-2 px-6 py-4 border-t border-white/5">
          <button
            onClick={() => !loading && onCancel()}
            disabled={loading}
            className="px-3.5 py-1.5 text-sm font-medium rounded-lg
              text-slate-400 hover:text-slate-100 hover:bg-white/8
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
              <span
                className="inline-block w-3 h-3 rounded-full border-2 border-current border-t-transparent animate-spin"
                aria-hidden="true"
              />
            )}
            {confirmText}
          </button>
        </div>
      </div>
    </div>
  );
}
