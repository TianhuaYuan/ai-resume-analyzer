import { useEffect, useRef } from "react";
import { TriangleAlert, LogIn } from "lucide-react";

interface SessionExpiredDialogProps {
  open: boolean;
  /** 点击「去登录」按钮 */
  onGoLogin: () => void;
}

/**
 * 全局会话过期弹窗。
 *
 * 当 refresh_token 也过期、无法静默续期时显示。
 * 用户必须点击「去登录」跳转登录页，不可通过 Esc/backdrop 关闭。
 *
 * 使用原生 <dialog> 元素，浏览器原生提供 focus trap 和模态语义。
 */
export default function SessionExpiredDialog({
  open,
  onGoLogin,
}: SessionExpiredDialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);

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
    } else {
      try {
        dialog.close();
      } catch {
        dialog.open = false;
      }
    }
  }, [open]);

  // 禁止 Esc 和 backdrop 关闭
  const handleCancel = (e: React.FormEvent<HTMLDialogElement>) => {
    e.preventDefault();
  };

  const handleClose = (e: React.MouseEvent<HTMLDialogElement>) => {
    e.preventDefault();
  };

  if (!open) return null;

  return (
    <dialog
      ref={dialogRef}
      onCancel={handleCancel}
      onClose={handleClose}
      className="fixed inset-0 z-[70] m-0 w-full h-full p-0
        bg-black/60 backdrop-blur-sm motion-reduce:backdrop-blur-none"
      role="dialog"
      aria-modal="true"
      aria-label="登录已过期"
    >
      <div
        className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2
          bg-[var(--color-surface)] border border-[var(--color-border)] rounded-input
          max-w-sm w-full mx-4 shadow-2xl
          animate-fade-in-up motion-reduce:animate-none"
      >
        <div className="flex flex-col items-center px-6 py-6 text-center">
          <div className="shrink-0 p-3 rounded-list mb-4 bg-danger/15 text-danger">
            <TriangleAlert size={28} strokeWidth={2.25} aria-hidden="true" />
          </div>

          <h3 className="text-base font-semibold text-[var(--color-text)]">
            登录已过期
          </h3>

          <p className="text-sm text-[var(--color-text-secondary)] mt-2 leading-relaxed">
            你的登录状态已失效，请重新登录后继续使用。
          </p>
        </div>

        <div className="flex items-center justify-center gap-2 px-6 py-4 border-t border-[var(--color-border)]">
          <button
            onClick={onGoLogin}
            className="px-4 py-2 text-sm font-medium rounded-full
              bg-brand hover:bg-brand-hover text-white
              active:scale-[0.98] motion-reduce:active:scale-100
              transition-all cursor-pointer
              flex items-center gap-1.5"
          >
            <LogIn size={14} aria-hidden="true" />
            去登录
          </button>
        </div>
      </div>
    </dialog>
  );
}
