/**
 * EditorToolbar — 顶部工具栏组件。
 *
 * 功能：
 * - 文件名编辑
 * - 保存状态指示
 * - 撤销/重做按钮
 * - 布局切换按钮（聊天/预览/双栏）
 * - 样式面板切换
 * - 模板切换
 */

import {
  FloppyDisk,
  Check,
  PaintBrush,
  GridFour,
  Funnel,
  ArrowCounterClockwise,
  ArrowClockwise,
  Warning,
  ChatsCircle,
  Monitor,
} from "@phosphor-icons/react";
import type { LayoutMode } from "./EditorLayout";

interface EditorToolbarProps {
  filename: string;
  onFilenameChange: (name: string) => void;
  saveStatus: "idle" | "saving" | "saved" | "error";
  lastSaveMode: "draft" | "complete" | null;
  saving: boolean;
  canUndo: boolean;
  canRedo: boolean;
  onUndo: () => void;
  onRedo: () => void;
  onSaveDraft: () => void;
  onSaveComplete: () => void;
  layoutMode: LayoutMode;
  onLayoutModeChange: (mode: LayoutMode) => void;
  onToggleStyle: () => void;
  onToggleTemplate: () => void;
}

export function EditorToolbar({
  filename,
  onFilenameChange,
  saveStatus,
  lastSaveMode,
  saving,
  canUndo,
  canRedo,
  onUndo,
  onRedo,
  onSaveDraft,
  onSaveComplete,
  layoutMode,
  onLayoutModeChange,
  onToggleStyle,
  onToggleTemplate,
}: EditorToolbarProps) {
  // 迷你模式：editModule 或 fullChat/fullPreview 时收缩为图标栏
  const isMini = layoutMode === "editModule" || layoutMode === "fullChat" || layoutMode === "fullPreview";

  return (
    <div className={`shrink-0 flex items-center justify-between gap-3 border-b border-[var(--color-border)] bg-white/80 backdrop-blur-xl transition-all duration-300 ${
      isMini ? "px-3 py-1.5" : "px-4 py-2.5"
    }`}>
      {/* 左侧：文件名 + 保存状态 */}
      <div className="flex items-center gap-3 min-w-0">
        {!isMini && (
          <input
            type="text"
            value={filename}
            onChange={(e) => onFilenameChange(e.target.value)}
            placeholder="未命名简历"
            className="px-2 py-1 rounded-full text-sm font-medium text-[var(--color-text)]
              bg-[#F2F2F7] border border-transparent
              hover:border-[var(--color-border)]
              focus:outline-none focus:bg-white focus:border-brand/40
              focus:ring-4 focus:ring-brand/15
              transition-all duration-150 min-w-[120px] max-w-[240px]"
            aria-label="文件名"
          />
        )}

        {saveStatus === "saving" && (
          <span className="flex items-center gap-1 text-[11px] text-[var(--color-text-muted)]">
            <span className="inline-block w-3 h-3 rounded-full border-2 border-brand border-t-transparent animate-spin" />
            {!isMini && "保存中..."}
          </span>
        )}
        {saveStatus === "saved" && (
          <span className="flex items-center gap-1 text-[11px] text-emerald-400">
            <Check size={12} weight="bold" />
            {!isMini && (lastSaveMode === "complete" ? "已保存并完成" : "草稿已保存")}
          </span>
        )}
        {saveStatus === "error" && (
          <span className="flex items-center gap-1 text-[11px] text-red-400">
            <Warning size={12} weight="bold" />
            {!isMini && "保存失败"}
          </span>
        )}
      </div>

      {/* 中间：撤销/重做 + 布局切换 */}
      <div className="flex items-center gap-1">
        <button
          onClick={onUndo}
          disabled={!canUndo}
          className="p-1.5 rounded-lg text-[var(--color-text-muted)] hover:bg-[var(--color-bg-secondary)]
            disabled:opacity-30 disabled:cursor-not-allowed transition-colors cursor-pointer"
          title="撤销 (Ctrl+Z)"
        >
          <ArrowCounterClockwise size={16} weight="bold" />
        </button>
        <button
          onClick={onRedo}
          disabled={!canRedo}
          className="p-1.5 rounded-lg text-[var(--color-text-muted)] hover:bg-[var(--color-bg-secondary)]
            disabled:opacity-30 disabled:cursor-not-allowed transition-colors cursor-pointer"
          title="重做 (Ctrl+Shift+Z)"
        >
          <ArrowClockwise size={16} weight="bold" />
        </button>

        <div className="w-px h-5 bg-[var(--color-border)] mx-1" />

        {/* 布局切换 */}
        <button
          onClick={() => onLayoutModeChange(layoutMode === "fullChat" ? "default" : "fullChat")}
          className={`p-1.5 rounded-lg transition-colors cursor-pointer ${
            layoutMode === "fullChat"
              ? "text-brand bg-brand/10"
              : "text-[var(--color-text-muted)] hover:bg-[var(--color-bg-secondary)]"
          }`}
          title="全屏聊天"
        >
          <ChatsCircle size={16} weight="bold" />
        </button>
        <button
          onClick={() => onLayoutModeChange(layoutMode === "fullPreview" ? "default" : "fullPreview")}
          className={`p-1.5 rounded-lg transition-colors cursor-pointer ${
            layoutMode === "fullPreview"
              ? "text-brand bg-brand/10"
              : "text-[var(--color-text-muted)] hover:bg-[var(--color-bg-secondary)]"
          }`}
          title="全屏预览"
        >
          <Monitor size={16} weight="bold" />
        </button>
      </div>

      {/* 右侧：样式/模板/保存 */}
      <div className="flex items-center gap-2">
        <button
          onClick={onToggleStyle}
          className={`flex items-center gap-1.5 rounded-lg text-xs font-medium
            text-[var(--color-text-muted)] hover:bg-[var(--color-bg-secondary)] transition-colors cursor-pointer ${
            isMini ? "p-1.5" : "px-3 py-1.5"
          }`}
          title="样式"
        >
          <PaintBrush size={14} weight="bold" />
          {!isMini && "样式"}
        </button>
        <button
          onClick={onToggleTemplate}
          className={`flex items-center gap-1.5 rounded-lg text-xs font-medium
            text-[var(--color-text-muted)] hover:bg-[var(--color-bg-secondary)] transition-colors cursor-pointer ${
            isMini ? "p-1.5" : "px-3 py-1.5"
          }`}
          title="模板"
        >
          <GridFour size={14} weight="bold" />
          {!isMini && "模板"}
        </button>

        <div className="w-px h-5 bg-[var(--color-border)]" />

        {!isMini && (
          <>
            <button
              onClick={onSaveDraft}
              disabled={saving}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium
                text-[var(--color-text-muted)] hover:bg-[var(--color-bg-secondary)]
                disabled:opacity-50 transition-colors cursor-pointer"
            >
              <FloppyDisk size={14} weight="bold" />
              保存草稿
            </button>
            <button
              onClick={onSaveComplete}
              disabled={saving}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold
                bg-brand text-white hover:bg-brand/90
                disabled:opacity-50 transition-colors cursor-pointer"
            >
              <Check size={14} weight="bold" />
              保存并完成
            </button>
          </>
        )}
      </div>
    </div>
  );
}
