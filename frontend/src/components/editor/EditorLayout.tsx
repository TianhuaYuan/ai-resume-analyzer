/**
 * EditorLayout — 三栏布局容器 + 状态机管理。
 *
 * 布局状态：
 * - default:     Sidebar(固定) | ChatPanel(40%) | PreviewPanel(60%)
 * - editModule:  Sidebar(折叠) | ChatPanel(40%) | PreviewPanel(60%) + InlineEditor 浮层
 * - previewFold: Sidebar(展开) | ChatPanel(70%) | PreviewPanel(折叠指示器)
 * - fullChat:    Sidebar(折叠) | ChatPanel(100%) | PreviewPanel(隐藏)
 * - fullPreview: Sidebar(折叠) | ChatPanel(隐藏) | PreviewPanel(100%)
 */

import { useState, useCallback, useEffect, type ReactNode } from "react";
import type { ModuleType } from "../../api/builder";

// ── 布局状态类型 ──────────────────────────────────────────

export type LayoutMode =
  | "default"      // 默认双栏
  | "editModule"   // 编辑模块（InlineEditor 弹出）
  | "previewFold"  // 预览折叠
  | "fullChat"     // 全屏聊天
  | "fullPreview"; // 全屏预览

interface EditorLayoutState {
  mode: LayoutMode;
  /** 当前编辑的模块类型（editModule 模式下有效） */
  editingModule: ModuleType | null;
  /** 当前编辑的条目 ID（条目级编辑） */
  editingEntryId: string | null;
}

// ── Props ──────────────────────────────────────────────────

interface EditorLayoutProps {
  /** Sidebar 组件 */
  sidebar: ReactNode;
  /** ChatPanel 组件 */
  chatPanel: ReactNode;
  /** PreviewPanel 组件 */
  previewPanel: ReactNode;
  /** InlineEditor 组件（可选，editModule 模式下显示） */
  inlineEditor?: ReactNode;
  /** Toolbar 组件 */
  toolbar: ReactNode;
  /** 布局模式变更回调 */
  onModeChange?: (mode: LayoutMode) => void;
}

// ── 主组件 ──────────────────────────────────────────────────

export function EditorLayout({
  sidebar,
  chatPanel,
  previewPanel,
  inlineEditor,
  toolbar,
  onModeChange,
}: EditorLayoutProps) {
  const [layoutState, setLayoutState] = useState<EditorLayoutState>({
    mode: "default",
    editingModule: null,
    editingEntryId: null,
  });

  // ── 模式切换 ──────────────────────────────────────────────

  const setMode = useCallback(
    (mode: LayoutMode, extra?: { module?: ModuleType; entryId?: string }) => {
      setLayoutState((prev) => ({
        ...prev,
        mode,
        editingModule: extra?.module ?? (mode === "editModule" ? prev.editingModule : null),
        editingEntryId: extra?.entryId ?? (mode === "editModule" ? prev.editingEntryId : null),
      }));
      onModeChange?.(mode);
    },
    [onModeChange],
  );

  const openModuleEditor = useCallback(
    (moduleType: ModuleType, entryId?: string) => {
      setMode("editModule", { module: moduleType, entryId });
    },
    [setMode],
  );

  const closeModuleEditor = useCallback(() => {
    setMode("default");
  }, [setMode]);

  const togglePreviewFold = useCallback(() => {
    setLayoutState((prev) => ({
      ...prev,
      mode: prev.mode === "previewFold" ? "default" : "previewFold",
    }));
  }, []);

  const toggleFullChat = useCallback(() => {
    setMode((prev) => (prev.mode === "fullChat" ? "default" : "fullChat"));
  }, []);

  const toggleFullPreview = useCallback(() => {
    setMode((prev) => (prev.mode === "fullPreview" ? "default" : "fullPreview"));
  }, []);

  // ── 键盘快捷键：Esc 关闭 InlineEditor ──
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && layoutState.mode === "editModule") {
        closeModuleEditor();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [layoutState.mode, closeModuleEditor]);

  // ── 计算各栏宽度 ──────────────────────────────────────────

  const { mode } = layoutState;
  const sidebarCollapsed = mode === "editModule" || mode === "fullChat" || mode === "fullPreview";

  // chatPanel 宽度比例
  const chatWidth = mode === "fullChat" ? "100%" : mode === "previewFold" ? "70%" : mode === "fullPreview" ? "0%" : "40%";
  // previewPanel 宽度比例
  const previewWidth = mode === "fullPreview" ? "100%" : mode === "fullChat" ? "0%" : mode === "previewFold" ? "30%" : "60%";

  return (
    <div className="flex h-full overflow-hidden">
      {/* 左侧导航栏 */}
      <div className={`${sidebarCollapsed ? "w-0 overflow-hidden" : "w-60"} transition-all duration-300 flex-shrink-0`}>
        {sidebar}
      </div>

      {/* 主编辑区 */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* 顶部工具栏 */}
        <div className="flex-shrink-0">
          {toolbar}
        </div>

        {/* 三栏内容区 */}
        <div className="flex-1 flex overflow-hidden">
          {/* ChatPanel */}
          {mode !== "fullPreview" && (
            <div
              className="overflow-hidden transition-all duration-300 border-r border-[var(--color-border)]"
              style={{ width: chatWidth }}
            >
              {chatPanel}
            </div>
          )}

          {/* PreviewPanel + InlineEditor */}
          {mode !== "fullChat" && (
            <div
              className="relative overflow-hidden transition-all duration-300"
              style={{ width: previewWidth }}
            >
              {previewPanel}

              {/* InlineEditor 浮层（editModule 模式） */}
              {mode === "editModule" && inlineEditor && (
                <div className="absolute inset-0 z-10 bg-[var(--color-bg)] overflow-auto">
                  {inlineEditor}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── 导出状态管理 hooks ──────────────────────────────────────

export type { EditorLayoutState };
