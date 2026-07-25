import { useEffect, useRef, useState } from "react";
import { Warning, Clock, SignIn, ArrowClockwise } from "@phosphor-icons/react";

type SessionDialogMode = "expired" | "warning";

interface SessionExpiredDialogProps {
  open: boolean;
  mode: SessionDialogMode;
  /** warning 模式下的剩余秒数，用于倒计时显示 */
  remainingSeconds?: number;
  /** 点击主按钮（去登录 / 延长登录） */
  onPrimary: () => void;
  /** warning 模式下点「忽略」 */
  onIgnore?: () => void;
  /** 主按钮 loading 状态（延长登录时刷新 token 请求中） */
  loading?: boolean;
}

/**
 * 全局会话状态弹窗。
 *
 * P3-6：使用原生 <dialog> 元素，浏览器原生提供 focus trap（Tab 键循环）
 * 和模态语义（aria-modal、esc 关闭等）。
 *
 * 两种模式：
 * - expired：token 已过期，刷新失败。只能点「去登录」，不能关闭（Esc/overlay/X 均禁用）。
 * - warning：token 即将过期（默认提前 5 分钟）。可以「延长登录」或「忽略」。
 */
export default function SessionExpiredDialog({
  open,
  mode,
  remainingSeconds = 0,
  onPrimary,
  onIgnore,
  loading = false,
}: SessionExpiredDialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [countdown, setCountdown] = useState(remainingSeconds);

  // warning 模式下倒计时，每秒更新
  useEffect(() => {
    if (!open || mode !== "warning") return;
    setCountdown(remainingSeconds);
    const timer = setInterval(() => {
      setCountdown((prev) => (prev > 0 ? prev - 1 : 0));
    }, 1000);
    return () => clearInterval(timer);
  }, [open, mode, remainingSeconds]);

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

  // expired 模式：禁止 Esc 和 backdrop 关闭
  const canClose = mode === "warning" && !loading;

  const handleCancel = (e: React.FormEvent<HTMLDialogElement>) => {
    e.preventDefault();
    if (canClose) {
      onIgnore?.();
    }
  };

  const handleClose = (e: React.DialogEvent<HTMLDialogElement>) => {
    e.preventDefault();
    if (canClose) {
      onIgnore?.();
    }
  };

  if (!open) return null;

  const isExpired = mode === "expired";
  const mins = Math.floor(countdown / 60);
  const secs = countdown % 60;

  const iconColor = isExpired
    ? "bg-red-500/15 text-red-400"
    : "bg-amber-500/15 text-amber-400";

  const primaryColor =
    "bg-indigo-500/20 hover:bg-indigo-500/30 text-indigo-300 border border-indigo-500/40";

  return (
    <dialog
      ref={dialogRef}
      onCancel={handleCancel}
      onClose={handleClose}
      className="fixed inset-0 z-[70] m-0 w-full h-full p-0
        bg-black/60 backdrop-blur-sm motion-reduce:backdrop-blur-none"
      role="dialog"
      aria-modal="true"
      aria-label={isExpired ? "登录已过期" : "登录即将过期"}
    >
      <div
        className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2
          bg-[var(--color-surface)] border border-[var(--color-border)] rounded-2xl
          max-w-sm w-full mx-4 shadow-2xl
          animate-fade-in-up motion-reduce:animate-none"
      >
        <div className="flex flex-col items-center px-6 py-6 text-center">
          <div className={`shrink-0 p-3 rounded-xl mb-4 ${iconColor}`}>
            {isExpired ? (
              <Warning size={28} weight="bold" aria-hidden="true" />
            ) : (
              <Clock size={28} weight="bold" aria-hidden="true" />
            )}
          </div>

          <h3 className="text-base font-semibold text-[var(--color-text)]">
            {isExpired ? "登录已过期" : "登录即将过期"}
          </h3>

          <p className="text-sm text-[var(--color-text-secondary)] mt-2 leading-relaxed">
            {isExpired
              ? "你的登录状态已失效，请重新登录后继续使用。"
              : `你的登录还有 ${mins}分${secs.toString().padStart(2, "0")}秒 过期，是否延长？`}
          </p>
        </div>

        <div className="flex items-center justify-center gap-2 px-6 py-4 border-t border-[var(--color-border)]">
          {!isExpired && (
            <button
              onClick={() => canClose && onIgnore?.()}
              disabled={loading}
              className="px-4 py-2 text-sm font-medium rounded-lg
                text-[var(--color-text-secondary)] hover:text-[var(--color-text)] hover:bg-white/8
                active:scale-[0.98] motion-reduce:active:scale-100
                transition-all cursor-pointer
                disabled:opacity-50 disabled:cursor-not-allowed"
            >
              忽略
            </button>
          )}
          <button
            onClick={() => !loading && onPrimary()}
            disabled={loading}
            className={`px-4 py-2 text-sm font-medium rounded-lg
              ${primaryColor}
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
            {isExpired ? (
              <>
                <SignIn size={14} weight="regular" aria-hidden="true" />
                去登录
              </>
            ) : (
              <>
                <ArrowClockwise size={14} weight="regular" aria-hidden="true" />
                延长登录
              </>
            )}
          </button>
        </div>
      </div>
    </dialog>
  );
}
