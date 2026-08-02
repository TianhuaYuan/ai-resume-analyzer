/**
 * T31 / #5 / #12: ModuleList — Builder 左侧模块列表组件。
 *
 * 展示「已添加模块」列表，支持：
 * - HTML5 拖拽排序（onReorder 回传新顺序）
 * - 删除模块（onRemove）
 * - 底部「添加模块」按钮选择任意预设类型（onAdd）
 * 点击选中模块进入编辑，每个模块带 AI 快速生成入口。
 */

import { memo, useState, useMemo } from "react";
import {
  DotsSixVertical,
  Sparkle,
  Plus,
  TrashSimple,
  CaretDown,
} from "@phosphor-icons/react";
import type { ModuleType, ResumeModule, ModuleContent } from "../../api/builder";

/** 15 个模块类型的中文名映射 */
export const MODULE_LABELS: Record<ModuleType, string> = {
  basic_info: "基本信息",
  education: "教育经历",
  work_experience: "工作经历",
  project_experience: "项目经历",
  skills: "专业技能",
  language: "语言能力",
  honors: "荣誉奖项",
  certificates: "证书",
  interests: "兴趣爱好",
  club_activities: "社团活动",
  publications: "发表论文",
  recommendation: "推荐人",
  social_links: "社交链接",
  other: "其他",
  custom: "自定义",
};

/** 模块类型的显示顺序（与后端 ModuleType 枚举顺序一致） */
export const MODULE_ORDER: ModuleType[] = [
  "basic_info",
  "education",
  "work_experience",
  "project_experience",
  "skills",
  "language",
  "honors",
  "certificates",
  "interests",
  "club_activities",
  "publications",
  "recommendation",
  "social_links",
  "other",
  "custom",
];

/** 模块类型对应的图标名（用于无障碍标签） */
const MODULE_ICONS: Record<ModuleType, string> = {
  basic_info: "用户图标",
  education: "学历图标",
  work_experience: "工作图标",
  project_experience: "项目图标",
  skills: "技能图标",
  language: "语言图标",
  honors: "荣誉图标",
  certificates: "证书图标",
  interests: "兴趣图标",
  club_activities: "社团图标",
  publications: "论文图标",
  recommendation: "推荐图标",
  social_links: "链接图标",
  other: "其他图标",
  custom: "自定义图标",
};

/**
 * 判断模块内容是否为空（无实质数据）。
 */
export function isModuleEmpty(content: ModuleContent): boolean {
  if (!content || Object.keys(content).length === 0) return true;

  for (const value of Object.values(content)) {
    if (value == null || value === "") continue;

    if (Array.isArray(value)) {
      if (value.length === 0) continue;
      if (value.every((v) => typeof v === "string")) {
        if (value.some((v) => v.trim() !== "")) return false;
        continue;
      }
      return false;
    }

    if (typeof value === "object") {
      const hasValue = Object.values(value).some(
        (v) =>
          v != null &&
          v !== "" &&
          !(Array.isArray(v) && v.length === 0) &&
          !(typeof v === "object" && v !== null && Object.keys(v).length === 0),
      );
      if (hasValue) return false;
      continue;
    }

    return false;
  }

  return true;
}

interface ModuleListProps {
  /** 当前简历的全部模块 */
  modules: ResumeModule[];
  /** 当前选中的模块类型 */
  selectedType: ModuleType | null;
  /** 选中模块回调 */
  onSelect: (type: ModuleType) => void;
  /** AI 生成回调 */
  onAIGenerate: (type: ModuleType) => void;
  /** 拖拽排序完成回调（新顺序的模块类型数组） */
  onReorder: (ordered: ModuleType[]) => void;
  /** 添加模块回调 */
  onAdd: (type: ModuleType) => void;
  /** 删除模块回调 */
  onRemove: (type: ModuleType) => void;
}

function ModuleListImpl({
  modules,
  selectedType,
  onSelect,
  onAIGenerate,
  onReorder,
  onAdd,
  onRemove,
}: ModuleListProps) {
  const [showAddMenu, setShowAddMenu] = useState(false);
  // 拖拽源索引
  const [dragIndex, setDragIndex] = useState<number | null>(null);
  // 拖拽悬停目标索引（高亮用）
  const [dropIndex, setDropIndex] = useState<number | null>(null);

  // 已添加模块按 sort_order 排序
  const sortedModules = useMemo(
    () => [...modules].sort((a, b) => a.sort_order - b.sort_order),
    [modules],
  );

  const existingTypes = useMemo(
    () => new Set(modules.map((m) => m.module_type)),
    [modules],
  );
  const availableTypes = MODULE_ORDER.filter((t) => !existingTypes.has(t));

  const handleDragStart = (index: number) => {
    setDragIndex(index);
    setDropIndex(index);
  };

  const handleDragOver = (e: React.DragEvent, index: number) => {
    e.preventDefault();
    if (dropIndex !== index) setDropIndex(index);
  };

  const handleDrop = (targetIndex: number) => {
    if (dragIndex === null || dragIndex === targetIndex) {
      setDragIndex(null);
      setDropIndex(null);
      return;
    }
    const ordered = sortedModules.map((m) => m.module_type);
    const [moved] = ordered.splice(dragIndex, 1);
    ordered.splice(targetIndex, 0, moved);
    onReorder(ordered);
    setDragIndex(null);
    setDropIndex(null);
  };

  const handleDragEnd = () => {
    setDragIndex(null);
    setDropIndex(null);
  };

  return (
    <div className="flex flex-col h-full bg-[var(--color-bg)]">
      {/* 标题栏 */}
      <div className="shrink-0 px-4 py-3 border-b border-[var(--color-border)] flex items-center justify-between">
        <h3 className="text-xs font-semibold text-[var(--color-text-secondary)] uppercase tracking-wider">
          模块列表
        </h3>
        <span className="text-[10px] text-[var(--color-text-muted)]">
          {sortedModules.length}/{MODULE_ORDER.length}
        </span>
      </div>

      {/* 已添加模块列表 */}
      <div className="flex-1 overflow-y-auto py-1">
        {sortedModules.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-8 px-4 text-center">
            <p className="text-xs text-[var(--color-text-muted)] mb-1">暂无模块</p>
            <p className="text-[10px] text-[var(--color-text-muted)]">
              点击下方「添加模块」开始构建
            </p>
          </div>
        ) : (
          sortedModules.map((module, index) => {
            const type = module.module_type;
            const isEmpty = isModuleEmpty(module.content);
            const isSelected = selectedType === type;
            const isDragging = dragIndex === index;
            const isDropTarget = dropIndex === index && dragIndex !== null && dragIndex !== index;

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
                onClick={() => onSelect(type)}
                className={`group flex items-center gap-1 px-2 py-2 mx-1 rounded-lg cursor-pointer
                  transition-all duration-150 border
                  ${isSelected
                    ? "bg-brand/10 border-brand/30"
                    : "border-transparent hover:bg-[var(--color-bg-secondary)]"
                  }
                  ${isEmpty ? "opacity-50" : "opacity-100"}
                  ${isDragging ? "opacity-40" : ""}
                  ${isDropTarget ? "border-t-2 border-brand/50" : ""}`}
                role="button"
                tabIndex={0}
                aria-label={`${MODULE_LABELS[type]}${isEmpty ? "（空）" : ""}`}
                aria-pressed={isSelected}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    onSelect(type);
                  }
                }}
              >
                {/* 拖拽手柄 */}
                <span
                  className="shrink-0 cursor-grab active:cursor-grabbing"
                  title="拖拽排序"
                >
                  <DotsSixVertical
                    size={14}
                    weight="bold"
                    className="text-[var(--color-text-muted)] opacity-0 group-hover:opacity-100 transition-opacity"
                    aria-label={MODULE_ICONS[type]}
                  />
                </span>

                {/* 模块名称 */}
                <span
                  className={`flex-1 text-xs truncate ${
                    isSelected
                      ? "text-brand font-medium"
                      : "text-[var(--color-text-secondary)]"
                  }`}
                >
                  {MODULE_LABELS[type]}
                </span>

                {/* 内容状态指示器 */}
                {!isEmpty && (
                  <span
                    className="w-1.5 h-1.5 rounded-full bg-emerald-400 shrink-0"
                    aria-label="已填写"
                  />
                )}

                {/* AI 生成按钮 */}
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    onAIGenerate(type);
                  }}
                  className="shrink-0 p-1 rounded text-[var(--color-text-muted)]
                    hover:text-brand hover:bg-brand/10
                    opacity-0 group-hover:opacity-100
                    active:scale-90 motion-reduce:active:scale-100
                    transition-all cursor-pointer"
                  aria-label={`AI 生成${MODULE_LABELS[type]}`}
                  title="AI 生成"
                >
                  <Sparkle size={12} weight="fill" aria-hidden="true" />
                </button>

                {/* 删除按钮 */}
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    onRemove(type);
                  }}
                  className="shrink-0 p-1 rounded text-[var(--color-text-muted)]
                    hover:text-red-400 hover:bg-red-500/10
                    opacity-0 group-hover:opacity-100
                    active:scale-90 motion-reduce:active:scale-100
                    transition-all cursor-pointer"
                  aria-label={`删除${MODULE_LABELS[type]}`}
                  title="删除模块"
                >
                  <TrashSimple size={12} weight="regular" aria-hidden="true" />
                </button>
              </div>
            );
          })
        )}
      </div>

      {/* 添加模块 */}
      <div className="shrink-0 p-2 border-t border-[var(--color-border)]">
        {showAddMenu ? (
          <div className="max-h-40 overflow-y-auto border border-[var(--color-border)] rounded-lg p-1">
            {availableTypes.length === 0 ? (
              <p className="px-2 py-1.5 text-[10px] text-[var(--color-text-muted)]">
                全部模块已添加
              </p>
            ) : (
              availableTypes.map((type) => (
                <button
                  key={type}
                  onClick={() => {
                    onAdd(type);
                    setShowAddMenu(false);
                  }}
                  className="w-full flex items-center gap-2 px-2 py-1.5 rounded-md text-xs
                    text-[var(--color-text-secondary)] hover:text-brand hover:bg-brand/10
                    transition-colors cursor-pointer text-left"
                  aria-label={`添加${MODULE_LABELS[type]}`}
                >
                  <Plus size={12} weight="bold" aria-hidden="true" />
                  {MODULE_LABELS[type]}
                </button>
              ))
            )}
          </div>
        ) : (
          <button
            onClick={() => setShowAddMenu(true)}
            disabled={availableTypes.length === 0}
            className="w-full inline-flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg
              text-xs font-medium text-[var(--color-text-secondary)]
              border border-dashed border-[var(--color-border)]
              hover:text-brand hover:border-brand/40 hover:bg-[var(--color-bg-secondary)]
              disabled:opacity-40 disabled:cursor-not-allowed
              transition-all cursor-pointer"
            aria-label="添加模块"
          >
            <Plus size={13} weight="bold" aria-hidden="true" />
            添加模块
            <CaretDown size={11} weight="fill" className="opacity-60" aria-hidden="true" />
          </button>
        )}
      </div>
    </div>
  );
}

export const ModuleList = memo(ModuleListImpl);
