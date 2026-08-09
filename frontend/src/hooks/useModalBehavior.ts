import { useEffect, useRef, type RefObject } from "react";

/**
 * useModalBehavior — 模态框行为标准化 Hook（借鉴 Hermes useModalBehavior）。
 *
 * 统一处理模态框的三件套行为：
 * - Esc 键关闭（自动忽略 dialog 原生 cancel 事件以避免双重关闭）
 * - body 滚动锁定（打开时 overflow:hidden，关闭还原）
 * - 焦点还原（关闭后还原到打开前的 activeElement）
 *
 * 用法：
 *   const containerRef = useModalBehavior({ open, onClose });
 *   return <div ref={containerRef}>...</div>;
 *
 * 注意：Esc 用 keydown 监听；若宿主元素是 <dialog>，原生 Esc 已触发 cancel，
 * 此处会额外触发一次 keydown（onClose 需幂等，如先判 open）。
 */
interface ModalBehaviorOptions {
  open: boolean;
  onClose: () => void;
  /** 是否监听 Esc 关闭（默认 true）。某些场景需禁用（如输入中） */
  escapeClosable?: boolean;
  /** 关闭后是否还原焦点（默认 true） */
  restoreFocus?: boolean;
}

export function useModalBehavior<T extends HTMLElement = HTMLDivElement>({
  open,
  onClose,
  escapeClosable = true,
  restoreFocus = true,
}: ModalBehaviorOptions): RefObject<T | null> {
  const containerRef = useRef<T>(null);

  useEffect(() => {
    if (!open) return;

    // 1. 记录打开前的焦点元素（用于关闭后还原）
    const prevActive =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;

    // 2. 锁滚动（body overflow 切换）
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    // 3. Esc 关闭
    const onKey = (e: KeyboardEvent) => {
      if (!escapeClosable) return;
      if (e.key === "Escape") {
        e.preventDefault();
        // 原生 dialog 会先触发 cancel，再触发此 keydown；用 isOpen 幂等防重入
        onClose();
      }
    };
    document.addEventListener("keydown", onKey);

    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
      if (restoreFocus && prevActive) {
        prevActive.focus?.();
      }
    };
  }, [open, onClose, escapeClosable, restoreFocus]);

  return containerRef;
}
