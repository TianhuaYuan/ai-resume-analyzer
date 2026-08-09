/**
 * T31 Phase 4: ModuleManager — StylePanel 的「板块管理」子组件。
 *
 * 职责：
 * - 列出当前简历的全部模块（按 sort_order 排序）
 * - 每行显示模块名 + 显隐开关（Eye / EyeOff）
 * - 显隐通过 onToggleHidden(type) 回调，由父组件写入 style.hidden_modules
 *
 * 排序已移除：模块顺序在左侧编辑器拖拽调整（ModuleCardEditor），
 * 样式面板这里只做显隐，避免两套排序入口冗余（M 修复）。
 *
 * 纯展示组件：不直接持有 style / onChange，避免与父组件状态耦合。
 */

import { memo, useMemo } from "react";
import { Eye, EyeOff } from "lucide-react";
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
}: ModuleManagerProps) {
  const sorted = useMemo(
    () => [...modules].sort((a, b) => a.sort_order - b.sort_order),
    [modules],
  );

  return (
    <div className="space-y-1.5">
      <p className="text-[10px] text-[var(--color-text-muted)] leading-relaxed">
        眼睛图标控制模块显示/隐藏（顺序在左侧编辑区拖拽调整）。
      </p>
      {sorted.length === 0 ? (
        <p className="text-[11px] text-[var(--color-text-muted)]">暂无模块</p>
      ) : (
        sorted.map((module) => {
          const type = module.module_type;
          const isHidden = hiddenModules.includes(type);
          const title = MODULE_TITLES[type] ?? type;

          return (
            <div
              key={type}
              className={`group flex items-center gap-1 px-2 py-1.5 rounded-action border
                transition-all duration-150
                ${isHidden ? "opacity-50" : "opacity-100"}
                border-[var(--color-border)]/60 bg-[var(--color-bg-secondary)]`}
            >
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
                  <EyeOff size={14} aria-hidden="true" />
                ) : (
                  <Eye size={14} aria-hidden="true" />
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
