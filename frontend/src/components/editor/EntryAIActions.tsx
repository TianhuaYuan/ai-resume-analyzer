/**
 * EntryAIActions — 条目级 AI 操作按钮组。
 *
 * 悬浮在条目卡片上时显示，点击展开下拉菜单，提供 5 种 AI 操作：
 * - optimize（优化本条）：润色措辞、增强专业感
 * - check（检查本条）：检查语法、格式等问题
 * - rewrite（改写本条）：按指令改写内容
 * - expand（生成更多成果）：扩展成就描述
 * - delete（删除本条）：需二次确认
 *
 * 使用方式：包裹在条目卡片容器中，hover 时自动显示触发按钮。
 *
 * 无障碍：
 * - 触发按钮：aria-haspopup="menu" + aria-expanded
 * - 菜单容器：role="menu"
 * - 菜单项：role="menuitem"
 * - 键盘：Esc 关闭、ArrowDown/Up 导航
 * - 删除操作有独立确认流程
 */

import { useState, useRef, useEffect, useCallback, memo } from "react";
import {
  Sparkle,
  CheckSquare,
  PencilSimple,
  Plus,
  Trash,
} from "@phosphor-icons/react";
import ConfirmDialog from "../ConfirmDialog";

// ── 类型定义 ──────────────────────────────────────────────

interface EntryAIActionsProps {
  /** 简历 ID */
  resumeId: number;
  /** 模块类型（如 experience、education、projects） */
  moduleType: string;
  /** 条目唯一 ID */
  entryId: string;
  /** 条目数据（用于上下文传递） */
  entryData: Record<string, unknown>;
  /**
   * AI 操作回调。
   * @param action - 操作类型（optimize / check / rewrite / expand）
   * @param instruction - 改写指令（仅 rewrite 时传入）
   */
  onAction: (action: string, instruction?: string) => void;
  /** 删除回调（可选，不传则不显示删除选项） */
  onDelete?: () => void;
}

// ── 菜单项配置 ────────────────────────────────────────────

interface MenuItemConfig {
  key: string;
  label: string;
  icon: React.ReactNode;
  action: string;
  danger?: boolean;
  /** 是否需要输入指令（rewrite 时使用） */
  needsInstruction?: boolean;
}

function buildMenuItems(hasDelete: boolean): MenuItemConfig[] {
  const items: MenuItemConfig[] = [
    {
      key: "optimize",
      label: "优化本条",
      icon: <Sparkle size={14} weight="fill" aria-hidden="true" />,
      action: "optimize",
    },
    {
      key: "check",
      label: "检查本条",
      icon: <CheckSquare size={14} weight="bold" aria-hidden="true" />,
      action: "check",
    },
    {
      key: "rewrite",
      label: "改写本条",
      icon: <PencilSimple size={14} weight="bold" aria-hidden="true" />,
      action: "rewrite",
      needsInstruction: true,
    },
    {
      key: "expand",
      label: "生成更多成果",
      icon: <Plus size={14} weight="bold" aria-hidden="true" />,
      action: "expand",
    },
  ];

  if (hasDelete) {
    items.push({
      key: "delete",
      label: "删除本条",
      icon: <Trash size={14} weight="bold" aria-hidden="true" />,
      action: "delete",
      danger: true,
    });
  }

  return items;
}

// ── 主组件 ──────────────────────────────────────────────

function EntryAIActionsImpl({
  resumeId: _resumeId,
  moduleType: _moduleType,
  entryId: _entryId,
  entryData: _entryData,
  onAction,
  onDelete,
}: EntryAIActionsProps) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [showRewriteInput, setShowRewriteInput] = useState(false);
  const [rewriteInstruction, setRewriteInstruction] = useState("");
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);

  const containerRef = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const rewriteInputRef = useRef<HTMLInputElement>(null);

  const menuItems = buildMenuItems(!!onDelete);

  // ── 点击外部关闭菜单 ──────────────────────────────────

  useEffect(() => {
    if (!menuOpen) return;

    const handlePointerDown = (e: MouseEvent) => {
      if (containerRef.current?.contains(e.target as Node)) return;
      setMenuOpen(false);
      setShowRewriteInput(false);
      setRewriteInstruction("");
    };

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        setMenuOpen(false);
        setShowRewriteInput(false);
        setRewriteInstruction("");
        triggerRef.current?.focus();
      }
    };

    document.addEventListener("mousedown", handlePointerDown);
    document.addEventListener("touchstart", handlePointerDown as EventListener);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
      document.removeEventListener("touchstart", handlePointerDown as EventListener);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [menuOpen]);

  // ── rewrite 输入框自动聚焦 ─────────────────────────────

  useEffect(() => {
    if (showRewriteInput) {
      rewriteInputRef.current?.focus();
    }
  }, [showRewriteInput]);

  // ── 关闭菜单并重置状态 ─────────────────────────────────

  const closeMenu = useCallback(() => {
    setMenuOpen(false);
    setShowRewriteInput(false);
    setRewriteInstruction("");
  }, []);

  // ── 触发按钮点击 ───────────────────────────────────────

  const handleTriggerClick = useCallback(() => {
    setMenuOpen((prev) => !prev);
    setShowRewriteInput(false);
    setRewriteInstruction("");
  }, []);

  // ── 菜单项点击 ─────────────────────────────────────────

  const handleItemClick = useCallback(
    (item: MenuItemConfig) => {
      if (item.key === "delete") {
        // 删除需要二次确认
        setShowDeleteConfirm(true);
        return;
      }

      if (item.needsInstruction) {
        // rewrite：展开内联指令输入
        setShowRewriteInput(true);
        return;
      }

      // 直接执行 AI 操作
      onAction(item.action);
      closeMenu();
    },
    [onAction, closeMenu],
  );

  // ── rewrite 指令提交 ────────────────────────────────────

  const handleRewriteSubmit = useCallback(() => {
    const inst = rewriteInstruction.trim();
    if (!inst) return;
    onAction("rewrite", inst);
    closeMenu();
  }, [rewriteInstruction, onAction, closeMenu]);

  // ── rewrite 指令取消 ────────────────────────────────────

  const handleRewriteCancel = useCallback(() => {
    setShowRewriteInput(false);
    setRewriteInstruction("");
  }, []);

  // ── 删除确认 ────────────────────────────────────────────

  const handleDeleteConfirm = useCallback(() => {
    setShowDeleteConfirm(false);
    closeMenu();
    onDelete?.();
  }, [onDelete, closeMenu]);

  const handleDeleteCancel = useCallback(() => {
    setShowDeleteConfirm(false);
  }, []);

  // ── 键盘导航（菜单内） ─────────────────────────────────

  const handleMenuKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLDivElement>) => {
      if (e.key === "Escape") {
        e.preventDefault();
        closeMenu();
        triggerRef.current?.focus();
        return;
      }

      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        const focusableItems = menuRef.current?.querySelectorAll<HTMLElement>(
          '[role="menuitem"]:not([aria-disabled="true"])',
        );
        if (!focusableItems || focusableItems.length === 0) return;

        const list = Array.from(focusableItems);
        const currentIndex = list.findIndex((el) => el === document.activeElement);

        let nextIndex: number;
        if (e.key === "ArrowDown") {
          nextIndex =
            currentIndex < 0 || currentIndex === list.length - 1 ? 0 : currentIndex + 1;
        } else {
          nextIndex = currentIndex <= 0 ? list.length - 1 : currentIndex - 1;
        }

        list[nextIndex]?.focus();
      }
    },
    [closeMenu],
  );

  // ── rewrite 指令键盘 ────────────────────────────────────

  const handleRewriteKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key === "Enter") {
        e.preventDefault();
        handleRewriteSubmit();
      } else if (e.key === "Escape") {
        e.preventDefault();
        handleRewriteCancel();
      }
    },
    [handleRewriteSubmit, handleRewriteCancel],
  );

  // ── 渲染 ──────────────────────────────────────────────

  return (
    <>
      <div ref={containerRef} className="relative">
        {/* 触发按钮：悬浮在条目卡片右上角 */}
        <button
          ref={triggerRef}
          type="button"
          aria-haspopup="menu"
          aria-expanded={menuOpen}
          aria-label="AI 操作"
          onClick={handleTriggerClick}
          className="p-1.5 rounded-lg text-[var(--color-text-muted)]
            hover:text-brand hover:bg-brand/10
            opacity-0 group-hover:opacity-100 focus:opacity-100
            active:scale-90 motion-reduce:active:scale-100
            transition-all duration-150 cursor-pointer"
        >
          <Sparkle size={14} weight="fill" aria-hidden="true" />
        </button>

        {/* 下拉菜单 */}
        {menuOpen && (
          <div
            ref={menuRef}
            role="menu"
            aria-label="AI 操作菜单"
            onKeyDown={handleMenuKeyDown}
            className="absolute right-0 top-full mt-1 min-w-[160px] z-50
              bg-[var(--color-surface)] border border-[var(--color-border)] rounded-xl
              shadow-2xl py-1.5
              animate-fade-in-up motion-reduce:animate-none"
          >
            {/* rewrite 内联指令输入 */}
            {showRewriteInput && (
              <div className="px-2.5 py-2 border-b border-[var(--color-border)]">
                <div className="flex items-center gap-1.5">
                  <input
                    ref={rewriteInputRef}
                    type="text"
                    value={rewriteInstruction}
                    onChange={(e) => setRewriteInstruction(e.target.value)}
                    onKeyDown={handleRewriteKeyDown}
                    placeholder="输入改写指令..."
                    className="flex-1 px-2.5 py-1.5 rounded-lg text-xs
                      bg-[var(--color-bg-secondary)] border border-[var(--color-border)]
                      placeholder:text-[var(--color-text-muted)]
                      focus:outline-none focus:border-brand/40 focus:ring-2 focus:ring-brand/15
                      transition-all duration-150"
                    aria-label="改写指令"
                  />
                  <button
                    onClick={handleRewriteSubmit}
                    disabled={!rewriteInstruction.trim()}
                    className="shrink-0 px-2 py-1.5 rounded-lg text-[10px] font-medium
                      bg-brand text-white hover:bg-brand/90
                      disabled:opacity-40 disabled:cursor-not-allowed
                      transition-all cursor-pointer"
                  >
                    Go
                  </button>
                </div>
                <button
                  onClick={handleRewriteCancel}
                  className="mt-1 text-[10px] text-[var(--color-text-muted)]
                    hover:text-[var(--color-text-secondary)] transition-colors cursor-pointer"
                >
                  取消
                </button>
              </div>
            )}

            {/* 菜单项 */}
            {menuItems.map((item) => (
              <button
                key={item.key}
                type="button"
                role="menuitem"
                onClick={() => handleItemClick(item)}
                className={`w-full text-left px-3 py-2 text-xs flex items-center gap-2
                  transition-colors cursor-pointer
                  ${
                    item.danger
                      ? "text-red-400 hover:bg-red-500/10"
                      : "text-[var(--color-text-secondary)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-secondary)]"
                  }`}
              >
                {item.icon}
                {item.label}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* 删除确认弹窗 */}
      <ConfirmDialog
        open={showDeleteConfirm}
        title="确认删除"
        description="确定要删除这条内容吗？此操作不可撤销。"
        confirmText="删除"
        cancelText="取消"
        danger
        onConfirm={handleDeleteConfirm}
        onCancel={handleDeleteCancel}
      />
    </>
  );
}

export const EntryAIActions = memo(EntryAIActionsImpl);
