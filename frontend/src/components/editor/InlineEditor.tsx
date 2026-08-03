/**
 * InlineEditor — 模块内联编辑浮层。
 *
 * 在 editModule 模式下覆盖在 PreviewPanel 上，
 * 加载对应模块的表单进行编辑。
 */

import { useMemo, useCallback } from "react";
import { X } from "@phosphor-icons/react";
import type { ModuleType, ResumeModule, ModuleContent } from "../../api/builder";
import { getModuleTitle, MODULE_LABELS } from "../../api/builder";
import { ModuleCard } from "../builder/ModuleCard";
import type { AIAction } from "../builder/ModuleCard";

interface InlineEditorProps {
  /** 当前编辑的模块类型 */
  moduleType: ModuleType;
  /** 条目 ID（可选，条目级编辑） */
  entryId?: string | null;
  /** 所有模块列表 */
  modules: ResumeModule[];
  /** 简历 ID */
  resumeId: number;
  /** 关闭编辑器 */
  onClose: () => void;
  /** 模块内容变更回调 */
  onChange: (type: ModuleType, content: ModuleContent) => void;
  /** AI 生成回调 */
  onAIGenerate?: (type: ModuleType, action?: AIAction, customPrompt?: string) => void;
}

export function InlineEditor({
  moduleType,
  entryId,
  modules,
  resumeId,
  onClose,
  onChange,
  onAIGenerate,
}: InlineEditorProps) {
  // 找到当前编辑的模块
  const module = useMemo(
    () => modules.find((m) => m.module_type === moduleType),
    [modules, moduleType],
  );

  const label = module ? getModuleTitle(module.content, moduleType) : MODULE_LABELS[moduleType] ?? moduleType;

  const handleChange = useCallback(
    (content: ModuleContent) => {
      onChange(moduleType, content);
    },
    [moduleType, onChange],
  );

  const handleAIGenerate = useCallback(
    (action?: AIAction, customPrompt?: string) => {
      onAIGenerate?.(moduleType, action, customPrompt);
    },
    [moduleType, onAIGenerate],
  );

  if (!module) {
    return (
      <div className="flex flex-col h-full bg-[var(--color-bg)]">
        <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--color-border)]">
          <h3 className="text-sm font-semibold text-[var(--color-text)]">{label}</h3>
          <button onClick={onClose} className="p-1 rounded-lg hover:bg-[var(--color-bg-secondary)] cursor-pointer">
            <X size={16} />
          </button>
        </div>
        <div className="flex-1 flex items-center justify-center text-sm text-[var(--color-text-muted)]">
          模块不存在
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full bg-[var(--color-bg)]">
      {/* 头部：模块名 + 关闭按钮 */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--color-border)] shrink-0">
        <h3 className="text-sm font-semibold text-[var(--color-text)]">{label}</h3>
        <button
          onClick={onClose}
          className="p-1.5 rounded-lg hover:bg-[var(--color-bg-secondary)] transition-colors cursor-pointer"
          title="关闭 (Esc)"
        >
          <X size={16} weight="bold" />
        </button>
      </div>

      {/* 编辑区：复用 ModuleCard 的表单 */}
      <div className="flex-1 overflow-y-auto px-4 py-3">
        <ModuleCard
          resumeId={resumeId}
          moduleType={moduleType}
          content={module.content}
          expanded={true}
          onChange={handleChange}
          onAIGenerate={handleAIGenerate}
          onRemove={() => {}}
          isDragging={false}
          isDropTarget={false}
          index={0}
          onDragStart={() => {}}
          onDragOver={() => {}}
          onDrop={() => {}}
          onDragEnd={() => {}}
          onToggleExpand={() => {}}
          onTouchDragStart={() => {}}
        />
      </div>
    </div>
  );
}
