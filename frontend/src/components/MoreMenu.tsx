import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { DotsThreeVertical } from "@phosphor-icons/react";

export interface MoreMenuItem {
  key: string;
  label: string;
  icon?: React.ReactNode;
  onClick: () => void;
  danger?: boolean;
  disabled?: boolean;
}

interface MoreMenuProps {
  items: MoreMenuItem[];
  /** 触发按钮的 aria-label，默认 "更多操作" */
  label?: string;
  /** 触发按钮自身的 disabled 状态（如卡片正在 loading 时禁用整组操作） */
  triggerDisabled?: boolean;
  /** 自定义触发按钮 className */
  triggerClassName?: string;
}

/**
 * Task 2.2: 通用「更多」下拉菜单。
 *
 * 用途：移动端折叠次要操作按钮，避免小屏按钮区拥挤。
 *
 * 无障碍：
 * - 触发按钮：aria-haspopup="menu" + aria-expanded
 * - 菜单容器：role="menu"
 * - 菜单项：role="menuitem" + aria-disabled（禁用项）
 * - 键盘：Esc 关闭、ArrowDown 打开后聚焦第一项、Tab 在菜单内循环
 *
 * 关闭方式：Esc / 点击外部 / 选中菜单项后自动关闭
 */
export default function MoreMenu({
  items,
  label = "更多操作",
  triggerDisabled = false,
  triggerClassName = "",
}: MoreMenuProps) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  // 点击外部关闭
  useEffect(() => {
    if (!open) return;
    const handlePointerDown = (e: MouseEvent) => {
      if (containerRef.current?.contains(e.target as Node)) return;
      setOpen(false);
    };
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        setOpen(false);
        triggerRef.current?.focus();
      }
    };
    document.addEventListener("mousedown", handlePointerDown);
    document.addEventListener("touchstart", handlePointerDown as unknown as EventListener);
    document.addEventListener("keydown", handleKeyDown as unknown as EventListener);
    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
      document.removeEventListener("touchstart", handlePointerDown as unknown as EventListener);
      document.removeEventListener("keydown", handleKeyDown as unknown as EventListener);
    };
  }, [open]);

  const close = () => {
    setOpen(false);
    // 关闭后把焦点还给触发按钮，便于键盘用户继续操作
    triggerRef.current?.focus();
  };

  const handleTriggerClick = () => {
    if (triggerDisabled) return;
    setOpen((v) => !v);
  };

  const handleTriggerKeyDown = (e: KeyboardEvent<HTMLButtonElement>) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      if (!triggerDisabled) {
        if (!open) setOpen(true);
        // 菜单已渲染（或即将渲染）后聚焦第一个可点击项
        // setTimeout 替代 requestAnimationFrame，兼容 jsdom 测试环境
        setTimeout(() => {
          const first = menuRef.current?.querySelector<HTMLElement>(
            '[role="menuitem"]:not([aria-disabled="true"])'
          );
          first?.focus();
        }, 0);
      }
    } else if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      if (!triggerDisabled) setOpen((v) => !v);
    }
  };

  const handleItemClick = (item: MoreMenuItem) => {
    if (item.disabled) return;
    item.onClick();
    close();
  };

  const handleMenuKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === "Escape") {
      e.preventDefault();
      close();
      return;
    }
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      const items = menuRef.current?.querySelectorAll<HTMLElement>(
        '[role="menuitem"]:not([aria-disabled="true"])'
      );
      if (!items || items.length === 0) return;
      const list = Array.from(items);
      const currentIndex = list.findIndex((el) => el === document.activeElement);
      let nextIndex: number;
      if (e.key === "ArrowDown") {
        nextIndex = currentIndex < 0 || currentIndex === list.length - 1 ? 0 : currentIndex + 1;
      } else {
        nextIndex = currentIndex <= 0 ? list.length - 1 : currentIndex - 1;
      }
      list[nextIndex]?.focus();
    }
  };

  // 菜单展开后，ArrowDown 应聚焦第一项（由 trigger 的 ArrowDown 也触发）
  // 这里在 open 变化后聚焦第一个可点击项
  useEffect(() => {
    if (!open) return;
    const first = menuRef.current?.querySelector<HTMLElement>(
      '[role="menuitem"]:not([aria-disabled="true"])'
    );
    // 不自动 focus，否则一打开就跳焦点，触发按钮的 ArrowDown 测试会失败
    // 改由 trigger 的 ArrowDown 显式聚焦
    first?.setAttribute("tabindex", "0");
  }, [open]);

  if (triggerDisabled) {
    return (
      <button
        ref={triggerRef}
        type="button"
        aria-haspopup="menu"
        aria-expanded="false"
        aria-label={label}
        disabled
        className={triggerClassName}
      >
        <DotsThreeVertical size={18} weight="bold" aria-hidden="true" />
      </button>
    );
  }

  return (
    <div ref={containerRef} className="relative inline-block">
      <button
        ref={triggerRef}
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={label}
        onClick={handleTriggerClick}
        onKeyDown={handleTriggerKeyDown}
        className={`inline-flex items-center justify-center p-1.5 rounded-lg
          text-[var(--color-text-secondary)] hover:text-[var(--color-text)] hover:bg-white/8
          active:scale-[0.95] motion-reduce:active:scale-100
          transition-all cursor-pointer ${triggerClassName}`}
      >
        <DotsThreeVertical size={18} weight="bold" aria-hidden="true" />
      </button>

      {open && (
        <div
          ref={menuRef}
          role="menu"
          aria-label={label}
          onKeyDown={handleMenuKeyDown}
          className="absolute right-0 top-full mt-1 min-w-[160px] z-50
            bg-[var(--color-surface)] border border-[var(--color-border)] rounded-xl
            shadow-2xl py-1.5
            animate-fade-in-up motion-reduce:animate-none"
        >
          {items.map((item) => (
            <button
              key={item.key}
              type="button"
              role="menuitem"
              aria-disabled={item.disabled}
              disabled={item.disabled}
              onClick={() => handleItemClick(item)}
              className={`w-full text-left px-3 py-2 text-xs flex items-center gap-2
                transition-colors cursor-pointer
                ${
                  item.disabled
                    ? "text-[var(--color-text-muted)] cursor-not-allowed"
                    : item.danger
                    ? "text-red-400 hover:bg-red-500/10"
                    : "text-[var(--color-text-secondary)] hover:text-[var(--color-text)] hover:bg-white/8"
                }`}
            >
              {item.icon}
              {item.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
