import { AnimatePresence, motion } from "framer-motion";
import { useEffect, type ReactNode } from "react";
import { X } from "@phosphor-icons/react";
import { twMerge } from "tailwind-merge";
import { overlayVariants, panelVariants } from "../useModalMotion";

export type ModalSize = "sm" | "md" | "lg" | "xl";

interface ModalProps {
  open: boolean;
  onClose: () => void;
  /** 面板标题（带标题栏 + 关闭按钮） */
  title?: ReactNode;
  children: ReactNode;
  /** 底部操作区（flex justify-end 自动右对齐） */
  footer?: ReactNode;
  size?: ModalSize;
  /** 点遮罩是否关闭（默认 true） */
  closeOnOverlay?: boolean;
  /** 隐藏关闭按钮（用于必须走操作的场景，如登录） */
  hideClose?: boolean;
  className?: string;
}

const SIZE_CLASSES: Record<ModalSize, string> = {
  sm: "max-w-sm",
  md: "max-w-md",
  lg: "max-w-2xl",
  xl: "max-w-4xl",
};

/**
 * Modal — 统一弹窗容器（framer-motion 驱动，全站动效一致）。
 *
 * 与 useModalMotion 配套：入场弹簧微升 + 遮罩 fade，退场快速淡出。
 * 内置：Esc 关闭、遮罩点击关闭、body 滚动锁定、标题栏 + 关闭按钮、footer 插槽。
 * 行为与既有 Dialog（ConfirmDialog 等原生 <dialog>）互补，供新面板统一接入。
 */
export default function Modal({
  open,
  onClose,
  title,
  children,
  footer,
  size = "md",
  closeOnOverlay = true,
  hideClose = false,
  className,
}: ModalProps) {
  // Esc 关闭
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, onClose]);

  // body 滚动锁定
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [open]);

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          role="dialog"
          aria-modal="true"
          aria-label={typeof title === "string" ? title : undefined}
          className="fixed inset-0 z-[60] flex items-center justify-center p-4 sm:p-6"
        >
          {/* 遮罩 */}
          <motion.div
            variants={overlayVariants}
            initial="hidden"
            animate="visible"
            exit="exit"
            onClick={closeOnOverlay ? onClose : undefined}
            className="absolute inset-0 bg-black/30 backdrop-blur-sm motion-reduce:backdrop-blur-none"
          />
          {/* 面板 */}
          <motion.div
            variants={panelVariants}
            initial="hidden"
            animate="visible"
            exit="exit"
            style={{ transformOrigin: "center" }}
            className={twMerge(
              "relative w-full rounded-modal bg-[var(--color-surface)] border border-[var(--color-border)] shadow-2xl shadow-black/20",
              "max-h-[85vh] flex flex-col overflow-hidden",
              SIZE_CLASSES[size],
              className,
            )}
          >
            {/* 标题栏 */}
            {(title || !hideClose) && (
              <div className="flex items-center justify-between gap-3 px-6 pt-5 pb-3 shrink-0">
                <div className="min-w-0 text-base font-semibold text-[var(--color-text)] display-tight">
                  {title}
                </div>
                {!hideClose && (
                  <button
                    onClick={onClose}
                    aria-label="关闭"
                    className="shrink-0 p-1.5 rounded-action text-[var(--color-text-secondary)]
                      hover:text-[var(--color-text)] hover:bg-[var(--color-bg-secondary)]
                      active:scale-[0.95] motion-reduce:active:scale-100
                      transition-all cursor-pointer"
                  >
                    <X size={16} weight="bold" aria-hidden="true" />
                  </button>
                )}
              </div>
            )}
            {/* 内容区（可滚动） */}
            <div className={twMerge("px-6 pb-5 overflow-y-auto", title || !hideClose ? "pt-1" : "pt-6")}>
              {children}
            </div>
            {/* 底部操作区 */}
            {footer && (
              <div className="flex items-center justify-end gap-2 px-6 py-4 border-t border-[var(--color-border)] shrink-0">
                {footer}
              </div>
            )}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
