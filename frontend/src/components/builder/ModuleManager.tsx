/**
 * T31 Phase 4: ModuleManager — StylePanel 的「板块管理」子组件。
 *
 * 职责：
 * - 列出当前简历的全部模块（按 sort_order 排序）
 * - 每行显示模块名 + 显隐开关（Eye / EyeSlash） + 拖拽/箭头排序
 * - 显隐通过 onToggleHidden(type) 回调，由父组件写入 style.hidden_modules
 * - 排序通过 onReorder(orderedTypes) 回调，由父组件（BuilderPage）更新 sort_order
 *
 * 纯展示组件：不直接持有 style / onChange，避免与父组件状态耦合。
 */

import { memo, useMemo, useState } from "react";
import { Eye, EyeSlash, DotsSixVertical, CaretUp, CaretDown } from "@phosphor-icons/react";
import { MODULE_TITLES } from "../templates/shared/sections";

/** StylePanel.modules 的条目形状（与 ResumeModule 结构兼容） */
export interface StylePanelModule {
  module_type: string;
  content: Record<string, unknown>;
  sort_order: number;
}

interface ModuleManagerProps {
  /** 当前模块列表（可无序，内部按 sort_order 排序） */
  modules: StylePanelModule[];
  /** 已隐藏的模块类型列表（对应 style.hidden_modules ?? []） */
  hiddenModules: string[];
  /** 切换模块显隐（由父组件写回 style.hidden_modules） */
  onToggleHidden: (moduleType: string) => void;
  /** 排序完成回调（新的模块类型顺序，由父组件更新 sort_order） */
  onReorder: (orderedTypes: string[]) => void;
}

const ICON_BTN_CLASS =
  "shrink-0 p-1 rounded-full text-[var(--color-text-muted)] " +
  "hover:text-brand hover:bg-brand/10 " +
  "disabled:opacity-30 disabled:cursor-not-allowed " +
  "transition-all cursor-pointer";

function ModuleManagerImpl({
  modules,
  hiddenModules,
  onToggleHidden,
  onReorder,
}: ModuleManagerProps) {
  // 拖拽排序状态（与 ModuleList 一致的原生 HTML5 拖拽）
  const [dragIndex, setDragIndex] = useState<number | null>(null);
  const [dropIndex, setDropIndex] = useState<number | null>(null);

  const sorted = useMemo(
    () => [...modules].sort((a, b) => a.sort_order - b.sort_order),
    [modules],
  );

  /** 将 index 处的模块移动到 to 位置，并把新顺序回传父组件 */
  const move = (from: number, to: number) => {
    if (from < 0 || to < 0 || from >= sorted.length || to >= sorted.length || from === to) return;
    const ordered = sorted.map((m) => m.module_type);
    const [moved] = ordered.splice(from, 1);
    ordered.splice(to, 0, moved);
    onReorder(ordered);
  };

  const handleDragStart = (index: number) => {
    setDragIndex(index);
    setDropIndex(index);
  };

  const handleDragOver = (e: React.DragEvent, index: number) => {
    e.preventDefault();
    if (dropIndex !== index) setDropIndex(index);
  };

  const handleDrop = (targetIndex: number) => {
    if (dragIndex !== null && dragIndex !== targetIndex) move(dragIndex, targetIndex);
    setDragIndex(null);
    setDropIndex(null);
  };

  const handleDragEnd = () => {
    setDragIndex(null);
    setDropIndex(null);
  };

  return (
    <div className="space-y-1.5">
      <p className="text-[10px] text-[var(--color-text-muted)] leading-relaxed">
        拖拽或使用箭头调整模块顺序；眼睛图标控制显示/隐藏。
      </p>
      {sorted.length === 0 ? (
        <p className="text-[11px] text-[var(--color-text-muted)]">暂无模块</p>
      ) : (
        sorted.map((module, index) => {
          const type = module.module_type;
          const isHidden = hiddenModules.includes(type);
          const title = MODULE_TITLES[type] ?? type;
          const isDragging = dragIndex === index;
          const isDropTarget =
            dropIndex === index && dragIndex !== null && dragIndex !== index;

          return (
            <div
              key={type}
              draggable
              onDragStart={() => handleDragStart(index)}
              onDragOver={(e) => handleDragOver(e, index)}
              onDrop={(e) => {
                e.preventDefault();
                handleDrop(index);
              }}
              onDragEnd={handleDragEnd}
              className={`group flex items-center gap-1 px-2 py-1.5 rounded-lg border
                transition-all duration-150
                ${isHidden ? "opacity-50" : "opacity-100"}
                ${isDragging ? "opacity-40" : ""}
                ${isDropTarget ? "border-t-2 border-brand/50" : ""}
                border-[var(--color-border)]/60 bg-[var(--color-bg-secondary)]`}
              aria-hidden="false"
            >
              {/* 拖拽手柄 */}
              <span
                className="shrink-0 cursor-grab active:cursor-grabbing text-[var(--color-text-muted)]"
                title="拖拽排序"
              >
                <DotsSixVertical size={13} weight="bold" aria-hidden="true" />
              </span>

              {/* 模块名称 */}
              <span
                className={`flex-1 text-xs truncate ${
                  isHidden
                    ? "line-through text-[var(--color-text-muted)]"
                    : "text-[var(--color-text-secondary)]"
                }`}
              >
                {title}
              </span>

              {/* 上移 / 下移（无障碍降级） */}
              <button
                onClick={() => move(index, index - 1)}
                disabled={index === 0}
                className={ICON_BTN_CLASS}
                aria-label={`上移${title}`}
                title="上移"
              >
                <CaretUp size={13} weight="bold" aria-hidden="true" />
              </button>
              <button
                onClick={() => move(index, index + 1)}
                disabled={index === sorted.length - 1}
                className={ICON_BTN_CLASS}
                aria-label={`下移${title}`}
                title="下移"
              >
                <CaretDown size={13} weight="bold" aria-hidden="true" />
              </button>

              {/* 显隐开关 */}
              <button
                onClick={() => onToggleHidden(type)}
                className={`${ICON_BTN_CLASS} ${
                  isHidden ? "text-[var(--color-text-muted)]" : "text-brand"
                }`}
                aria-label={isHidden ? `显示${title}` : `隐藏${title}`}
                aria-pressed={isHidden}
                title={isHidden ? "显示模块" : "隐藏模块"}
              >
                {isHidden ? (
                  <EyeSlash size={14} weight="regular" aria-hidden="true" />
                ) : (
                  <Eye size={14} weight="regular" aria-hidden="true" />
                )}
              </button>
            </div>
          );
        })
      )}
    </div>
  );
}

export const ModuleManager = memo(ModuleManagerImpl);
