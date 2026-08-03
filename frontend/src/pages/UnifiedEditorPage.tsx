/**
 * UnifiedEditorPage — 统一 Agent 编辑器主页面。
 *
 * 合并 QAPage + BuilderPage 为单一页面：
 * - 左侧：Agent ChatPanel（持久化对话，共享 conversation 机制）
 * - 右侧：A4PreviewPanel（可折叠，点击模块弹出内联编辑）
 * - 顶部：EditorToolbar（文件名、保存、撤销/重做、布局切换）
 *
 * 路由：/resumes/:id/edit（替代原 BuilderPage）
 */

import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { useParams } from "react-router-dom";
import {
  getBuilderResume,
  saveDraft,
  saveComplete,
  acquireEditLock,
  renewEditLock,
  releaseEditLock,
} from "../api/builder";
import type {
  BuilderResume,
  ResumeModule,
  ResumeStyle,
  ModuleType,
  ModuleContent,
  ResumeModuleInput,
} from "../api/builder";
import { useHistory } from "../hooks/useHistory";
import { EditorLayout } from "../components/editor/EditorLayout";
import type { LayoutMode } from "../components/editor/EditorLayout";
import { EditorToolbar } from "../components/editor/EditorToolbar";
import { ChatPanel } from "../components/editor/ChatPanel";
import { InlineEditor } from "../components/editor/InlineEditor";
import { A4PreviewPanel } from "../components/builder/A4PreviewPanel";
import { StylePanel } from "../components/builder/StylePanel";
import { TemplateSheet } from "../components/builder/TemplateSheet";
import { trackEvent } from "../api/analytics";

// ── 常量 ──────────────────────────────────────────────────────

const DEFAULT_STYLE: ResumeStyle = {
  template_id: "default",
  font_family: "Noto Sans CJK SC",
  font_size: "14px",
  line_height: 1.6,
  spacing: "8px",
  accent_color: "#2563eb",
  margin: "16mm",
  page_size: "A4",
  section_spacing: "16px",
  custom_css: "",
};

function modulesToInputs(modules: ResumeModule[]): ResumeModuleInput[] {
  return [...modules]
    .sort((a, b) => a.sort_order - b.sort_order)
    .map((m) => ({
      module_type: m.module_type,
      content: m.content,
      sort_order: m.sort_order,
    }));
}

function notifyListRefresh() {
  window.dispatchEvent(new Event("resume:list-refresh"));
}

// ── 主组件 ────────────────────────────────────────────────────

export default function UnifiedEditorPage() {
  const { id } = useParams<{ id: string }>();
  const resumeId = Number(id);

  // ── 数据状态 ──
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [resume, setResume] = useState<BuilderResume | null>(null);
  const {
    state: modules,
    setState: setModules,
    undo,
    redo,
    canUndo,
    canRedo,
    reset: resetHistory,
  } = useHistory<ResumeModule[]>([], { maxHistory: 50, debounceMs: 500 });
  const [filename, setFilename] = useState("");
  const [version, setVersion] = useState(0);
  const [style, setStyle] = useState<ResumeStyle>(DEFAULT_STYLE);

  // ── UI 状态 ──
  const [layoutMode, setLayoutMode] = useState<LayoutMode>("default");
  const [editingModule, setEditingModule] = useState<ModuleType | null>(null);
  const [editingEntryId, setEditingEntryId] = useState<string | null>(null);
  const [showStylePanel, setShowStylePanel] = useState(false);
  const [showTemplateSheet, setShowTemplateSheet] = useState(false);
  const [previewKey, setPreviewKey] = useState(0);
  const [saving, setSaving] = useState(false);
  const [saveStatus, setSaveStatus] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [lastSaveMode, setLastSaveMode] = useState<"draft" | "complete" | null>(null);
  const [indexInfo, setIndexInfo] = useState<{ is_indexed: boolean; is_stale: boolean } | null>(null);
  const [materialized, setMaterialized] = useState(true);

  // ── Refs ──
  const lockTokenRef = useRef<string | null>(null);
  const modulesRef = useRef(modules);
  const filenameRef = useRef(filename);
  const styleRef = useRef(style);
  const autoSaveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const firstEditRef = useRef(true);
  const builderTrackedRef = useRef(false);

  useEffect(() => { modulesRef.current = modules; }, [modules]);
  useEffect(() => { filenameRef.current = filename; }, [filename]);
  useEffect(() => { styleRef.current = style; }, [style]);

  // ── 撤销/重做快捷键 ──
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      const isCtrlOrCmd = e.ctrlKey || e.metaKey;
      if (!isCtrlOrCmd) return;
      if (e.key === "z" || e.key === "Z") {
        e.preventDefault();
        if (e.shiftKey) { redo(); } else { undo(); }
      } else if (e.key === "y" || e.key === "Y") {
        e.preventDefault();
        redo();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [undo, redo]);

  // ── 加载简历 ──
  const loadResume = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await getBuilderResume(resumeId);
      setResume(data);
      resetHistory(data.modules ?? []);
      setFilename(data.filename);
      setVersion(data.version);
      setStyle(data.style ?? DEFAULT_STYLE);
      setIndexInfo({ is_indexed: data.is_indexed ?? false, is_stale: data.is_stale ?? false });
      setMaterialized(data.modules_materialized ?? true);
      setSaveStatus("idle");
      firstEditRef.current = true;
      if (!builderTrackedRef.current) {
        builderTrackedRef.current = true;
        void trackEvent("resume.builder_create");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载简历失败");
    } finally {
      setLoading(false);
    }
  }, [resumeId, resetHistory]);

  const refreshModules = useCallback(async () => {
    try {
      const data = await getBuilderResume(resumeId);
      setResume(data);
      resetHistory(data.modules ?? []);
      setVersion(data.version);
      setMaterialized(data.modules_materialized ?? true);
      setIndexInfo({ is_indexed: data.is_indexed ?? false, is_stale: data.is_stale ?? false });
    } catch { /* 刷新失败不打断编辑 */ }
  }, [resumeId, resetHistory]);

  useEffect(() => {
    const sync = () => { void refreshModules(); };
    window.addEventListener("resume:modules-refresh", sync);
    return () => window.removeEventListener("resume:modules-refresh", sync);
  }, [refreshModules]);

  useEffect(() => { loadResume(); }, [loadResume]);

  // ── 编辑锁 ──
  useEffect(() => {
    acquireEditLock(resumeId)
      .then((res) => { if (res.locked && res.lock_token) lockTokenRef.current = res.lock_token; })
      .catch(() => {});
    const heartbeat = setInterval(() => {
      if (lockTokenRef.current) renewEditLock(resumeId, lockTokenRef.current).catch(() => {});
    }, 60000);
    return () => {
      clearInterval(heartbeat);
      if (lockTokenRef.current) releaseEditLock(resumeId, lockTokenRef.current).catch(() => {});
    };
  }, [resumeId]);

  // ── 自动保存草稿（5s 防抖） ──
  useEffect(() => {
    if (autoSaveTimerRef.current) clearTimeout(autoSaveTimerRef.current);
    if (!firstEditRef.current && resume) {
      autoSaveTimerRef.current = setTimeout(async () => {
        setSaving(true);
        try {
          const result = await saveDraft(resumeId, {
            filename: filenameRef.current,
            modules: modulesToInputs(modulesRef.current),
            style: styleRef.current,
          });
          setVersion(result.version);
          setSaveStatus("saved");
          setLastSaveMode("draft");
          notifyListRefresh();
        } catch {
          setSaveStatus("error");
        } finally {
          setSaving(false);
        }
      }, 5000);
    }
    firstEditRef.current = false;
    return () => { if (autoSaveTimerRef.current) clearTimeout(autoSaveTimerRef.current); };
  }, [modules, filename, style, resumeId, resume]);

  // ── 模块变更 ──
  const handleModuleChange = useCallback((type: ModuleType, content: ModuleContent) => {
    setModules((prev) =>
      prev.map((m) => (m.module_type === type ? { ...m, content } : m)),
    );
  }, [setModules]);

  const handleReorder = useCallback((ordered: ModuleType[]) => {
    setModules((prev) =>
      prev.map((m) => ({
        ...m,
        sort_order: ordered.indexOf(m.module_type),
      })),
    );
  }, [setModules]);

  const handleAddModule = useCallback((type: ModuleType) => {
    setModules((prev) => {
      const maxOrder = prev.reduce((max, m) => Math.max(max, m.sort_order), -1);
      return [...prev, {
        id: -Date.now(),
        resume_id: resumeId,
        module_type: type,
        content: {},
        sort_order: maxOrder + 1,
        created_at: new Date().toISOString(),
      }];
    });
  }, [resumeId, setModules]);

  const handleRemoveModule = useCallback((type: ModuleType) => {
    setModules((prev) => prev.filter((m) => m.module_type !== type));
  }, [setModules]);

  // ── 保存 ──
  const handleSaveDraft = useCallback(async () => {
    if (!resume) return;
    setSaving(true);
    try {
      const result = await saveDraft(resumeId, {
        filename: filenameRef.current,
        modules: modulesToInputs(modulesRef.current),
        style: styleRef.current,
      });
      setVersion(result.version);
      setSaveStatus("saved");
      setLastSaveMode("draft");
      notifyListRefresh();
    } catch {
      setSaveStatus("error");
    } finally {
      setSaving(false);
    }
  }, [resume, resumeId]);

  const handleSaveComplete = useCallback(async () => {
    if (!resume) return;
    setSaving(true);
    setError("");
    try {
      const result = await saveComplete(resumeId, version, {
        filename: filenameRef.current,
        modules: modulesToInputs(modulesRef.current),
        style: styleRef.current,
      });
      setVersion(result.version);
      setResume(result);
      setSaveStatus("saved");
      setLastSaveMode("complete");
      notifyListRefresh();
      setIndexInfo({ is_indexed: true, is_stale: false });
    } catch (e) {
      setError(e instanceof Error ? e.message : "保存失败");
      setSaveStatus("error");
    } finally {
      setSaving(false);
    }
  }, [resume, resumeId, version]);

  // ── 样式变更回调 ──
  const handleStyleChange = useCallback((newStyle: ResumeStyle) => {
    setStyle(newStyle);
    setPreviewKey((k) => k + 1);
  }, []);

  // ── 模板切换回调 ──
  const handleTemplateChange = useCallback((templateId: string) => {
    setStyle((prev) => ({ ...prev, template_id: templateId }));
    setPreviewKey((k) => k + 1);
  }, []);

  // ── 加载中/错误 ──
  if (loading) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center bg-[var(--color-bg)]">
        <span className="inline-block w-8 h-8 rounded-full border-2 border-brand border-t-transparent animate-spin" />
        <p className="text-sm text-[var(--color-text-muted)] mt-3">加载编辑器...</p>
      </div>
    );
  }

  if (error && !resume) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center bg-[var(--color-bg)] px-6">
        <p className="text-base text-[var(--color-text-secondary)] mb-1.5">加载失败</p>
        <p className="text-sm text-[var(--color-text-muted)] mb-5 text-center max-w-sm">{error}</p>
        <button onClick={loadResume} className="px-4 py-2 rounded-xl text-sm font-medium bg-brand/15 text-brand border border-brand/30 hover:bg-brand/25 cursor-pointer">
          重试
        </button>
      </div>
    );
  }

  if (!resume) return null;

  // ── 主布局 ──
  return (
    <div className="flex-1 flex flex-col overflow-hidden bg-[var(--color-bg)]">
      <EditorLayout
        sidebar={null}
        toolbar={
          <EditorToolbar
            filename={filename}
            onFilenameChange={setFilename}
            saveStatus={saveStatus}
            lastSaveMode={lastSaveMode}
            saving={saving}
            canUndo={canUndo}
            canRedo={canRedo}
            onUndo={undo}
            onRedo={redo}
            onSaveDraft={handleSaveDraft}
            onSaveComplete={handleSaveComplete}
            layoutMode={layoutMode}
            onLayoutModeChange={setLayoutMode}
            onToggleStyle={() => setShowStylePanel((v) => !v)}
            onToggleTemplate={() => setShowTemplateSheet((v) => !v)}
          />
        }
        chatPanel={
          <ChatPanel
            resumeId={resumeId}
            modules={modules}
            onModulesRefresh={refreshModules}
          />
        }
        previewPanel={
          <A4PreviewPanel
            resumeId={resumeId}
            previewKey={previewKey}
            collapsed={layoutMode === "previewFold"}
            onToggleCollapse={() => setLayoutMode((m) => m === "previewFold" ? "default" : "previewFold")}
            modulesData={{
              modules: modules.map((m) => ({
                module_type: m.module_type,
                content: m.content,
                sort_order: m.sort_order,
              })),
              style,
            }}
            onSelectSection={(moduleType) => {
              // 点击预览区 section → 打开 InlineEditor
              setEditingModule(moduleType);
              setEditingEntryId(null);
              setLayoutMode("editModule");
            }}
          />
        }
        inlineEditor={
          editingModule ? (
            <InlineEditor
              moduleType={editingModule}
              entryId={editingEntryId}
              modules={modules}
              resumeId={resumeId}
              onClose={() => {
                setEditingModule(null);
                setEditingEntryId(null);
                setLayoutMode("default");
              }}
              onChange={handleModuleChange}
              onAIGenerate={(type, action, prompt) => {
                // TODO: 接入 AIGenerateDialog
                console.log("AI generate:", type, action, prompt);
              }}
            />
          ) : undefined
        }
        onModeChange={setLayoutMode}
      />

      {/* 样式面板 */}
      {showStylePanel && (
        <StylePanel
          style={style}
          onChange={handleStyleChange}
          onClose={() => setShowStylePanel(false)}
        />
      )}

      {/* 模板选择 */}
      {showTemplateSheet && (
        <TemplateSheet
          currentTemplate={style.template_id}
          onChange={handleTemplateChange}
          onClose={() => setShowTemplateSheet(false)}
        />
      )}
    </div>
  );
}
