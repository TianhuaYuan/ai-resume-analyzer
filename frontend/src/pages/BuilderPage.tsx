/**
 * BuilderPage — 简历编辑器主编排页面。
 *
 * 两栏布局：ModuleCardEditor（左）| A4PreviewPanel（右）
 * 顶部工具栏：文件名编辑、保存草稿、保存完成、样式切换、AI 切换
 *
 * 核心机制：
 * - 挂载时加载 builder 简历 + 获取编辑锁
 * - 编辑锁心跳续期 60s，卸载时释放
 * - 自动保存草稿：编辑后 5s 防抖
 * - 预览防抖：内容变更后 300ms 刷新 iframe
 * - 样式状态本地管理，随草稿保存
 * - StylePanel 和 BuilderAIChat 为浮动覆盖层
 */

import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import {
  FloppyDisk,
  Check,
  PaintBrush,
  ChatCircleDots,
  Warning,
  ArrowsClockwise,
  ArrowCounterClockwise,
  ArrowClockwise,
} from "@phosphor-icons/react";
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
import { MODULE_LABELS } from "../components/builder/ModuleList";
import { ModuleCardEditor } from "../components/builder/ModuleCardEditor";
import type { AIAction } from "../components/builder/ModuleCard";
import { A4PreviewPanel } from "../components/builder/A4PreviewPanel";
import { StylePanel } from "../components/builder/StylePanel";
import { BuilderAIChat } from "../components/builder/BuilderAIChat";
import { trackEvent } from "../api/analytics";
import { useHistory } from "../hooks/useHistory";

// ── 常量 ──────────────────────────────────────────────────────

/** 默认样式配置 */
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

/** 将 ResumeModule[] 转为保存用的 ResumeModuleInput[] */
function modulesToInputs(modules: ResumeModule[]): ResumeModuleInput[] {
  return [...modules]
    .sort((a, b) => a.sort_order - b.sort_order)
    .map((m) => ({
      module_type: m.module_type,
      content: m.content,
      sort_order: m.sort_order,
    }));
}

/** 保存成功后通知 Sidebar 等组件刷新简历列表（文件名/状态变化需同步到列表） */
function notifyListRefresh() {
  window.dispatchEvent(new Event("resume:list-refresh"));
}

// ── 组件 Props ────────────────────────────────────────────────

interface BuilderPageProps {
  /** 简历 ID（从 AppLayout 路由参数传入） */
  resumeId: number;
}

// ── 主组件 ────────────────────────────────────────────────────

export function BuilderPage({ resumeId }: BuilderPageProps) {
  // 加载与错误状态
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // 简历数据
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

  // UI 状态
  const [expandedType, setExpandedType] = useState<ModuleType | null>(null);
  const [showStylePanel, setShowStylePanel] = useState(false);
  const [showAIChat, setShowAIChat] = useState(false);
  const [previewCollapsed, setPreviewCollapsed] = useState(false);
  const [previewKey, setPreviewKey] = useState(0);

  // 保存状态
  const [saving, setSaving] = useState(false);
  const [saveStatus, setSaveStatus] = useState<"idle" | "saving" | "saved" | "error">("idle");

  // AI 触发
  const [aiQuestion, setAiQuestion] = useState("");
  const [aiTrigger, setAiTrigger] = useState(0);

  // Refs（避免闭包陷阱）
  const lockTokenRef = useRef<string | null>(null);
  const modulesRef = useRef(modules);
  const filenameRef = useRef(filename);
  const styleRef = useRef(style);
  const autoSaveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const firstEditRef = useRef(true);
  // T37: builder 埋点只触发一次（避免重试/重复加载重复上报）
  const builderTrackedRef = useRef(false);

  // 同步 refs
  useEffect(() => { modulesRef.current = modules; }, [modules]);
  useEffect(() => { filenameRef.current = filename; }, [filename]);
  useEffect(() => { styleRef.current = style; }, [style]);

  // ── 撤销/重做快捷键 ──────────────────────────────────────────
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      const isCtrlOrCmd = e.ctrlKey || e.metaKey;
      if (!isCtrlOrCmd) return;
      if (e.key === "z" || e.key === "Z") {
        e.preventDefault();
        if (e.shiftKey) {
          redo();
        } else {
          undo();
        }
      } else if (e.key === "y" || e.key === "Y") {
        e.preventDefault();
        redo();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [undo, redo]);

  // ── 加载简历 ────────────────────────────────────────────────

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
      setExpandedType("basic_info");
      setSaveStatus("idle");
      firstEditRef.current = true; // 重置首次编辑标记
      // T37: 进入 builder 埋点（best-effort，只上报一次）
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

  // agent 完成后刷新模块数据（回填表单），保留当前展开模块，不触发 loading
  // 添加 500ms 延迟：agent_done 事件可能在后端数据库提交完成前触发，
  // 直接拉取会拿到旧数据导致表单不更新
  const refreshModules = useCallback(async () => {
    await new Promise((resolve) => setTimeout(resolve, 500));
    try {
      const data = await getBuilderResume(resumeId);
      setResume(data);
      resetHistory(data.modules ?? []);
      setVersion(data.version);
    } catch {
      // 刷新失败不打断编辑，用户可稍后手动保存/重试
    }
  }, [resumeId, resetHistory]);

  // 跨 Tab 同步：QA 页面（聊天 Tab）改写类工具写库后，通过 resume:modules-refresh 通知此处重同步
  useEffect(() => {
    const sync = () => {
      void refreshModules();
    };
    window.addEventListener("resume:modules-refresh", sync);
    return () => window.removeEventListener("resume:modules-refresh", sync);
  }, [refreshModules]);

  useEffect(() => {
    loadResume();
  }, [loadResume]);

  // ── 编辑锁生命周期 ──────────────────────────────────────────

  useEffect(() => {
    // 获取编辑锁
    acquireEditLock(resumeId)
      .then((res) => {
        if (res.locked && res.lock_token) {
          lockTokenRef.current = res.lock_token;
        }
      })
      .catch(() => {
        // 锁获取失败 — 允许编辑但保存可能冲突
      });

    // 心跳续期（60s）
    const heartbeat = setInterval(() => {
      if (lockTokenRef.current) {
        renewEditLock(resumeId, lockTokenRef.current).catch(() => {});
      }
    }, 60000);

    // 释放锁
    return () => {
      clearInterval(heartbeat);
      if (lockTokenRef.current) {
        releaseEditLock(resumeId, lockTokenRef.current).catch(() => {});
      }
    };
  }, [resumeId]);

  // ── 预览刷新 key（内容/样式变更时递增，跳过首次，600ms 防抖） ──

  const previewDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (firstEditRef.current) {
      // 首次渲染（加载完成）不触发预览刷新，iframe 自行加载
      return;
    }
    // 防抖：连续编辑时只在停顿后触发一次预览刷新（400ms，无双重防抖）
    if (previewDebounceRef.current) clearTimeout(previewDebounceRef.current);
    previewDebounceRef.current = setTimeout(() => {
      setPreviewKey((k) => k + 1);
    }, 400);
    return () => {
      if (previewDebounceRef.current) clearTimeout(previewDebounceRef.current);
    };
  }, [modules, style]);

  // 当前编辑数据（传给 A4PreviewPanel 用 POST 实时渲染，不读数据库）
  const previewData = useMemo(
    () => ({ modules: modulesToInputs(modules), style }),
    [modules, style],
  );

  // ── 自动保存（5s 防抖） ─────────────────────────────────────

  const doSaveDraft = useCallback(async () => {
    if (!resume) return;
    setSaveStatus("saving");
    try {
      const result = await saveDraft(resumeId, {
        filename: filenameRef.current,
        modules: modulesToInputs(modulesRef.current),
        style: styleRef.current,
      });
      setVersion(result.version);
      setSaveStatus("saved");
      notifyListRefresh();
    } catch {
      setSaveStatus("error");
    }
  }, [resume, resumeId]);

  useEffect(() => {
    if (firstEditRef.current) {
      firstEditRef.current = false;
      return;
    }
    if (!resume) return;

    if (autoSaveTimerRef.current) clearTimeout(autoSaveTimerRef.current);
    autoSaveTimerRef.current = setTimeout(() => {
      doSaveDraft();
    }, 5000);

    return () => {
      if (autoSaveTimerRef.current) clearTimeout(autoSaveTimerRef.current);
    };
  }, [modules, filename, style, resume, doSaveDraft]);

  // ── 模块内容编辑（接收 type + content） ─────────────────────

  const handleModuleChange = useCallback(
    (type: ModuleType, content: ModuleContent) => {
      setModules((prev) => {
        const existing = prev.find((m) => m.module_type === type);
        if (existing) {
          return prev.map((m) =>
            m.module_type === type ? { ...m, content } : m,
          );
        }
        // 创建新模块（排在末尾）
        const maxOrder = prev.reduce((mx, m) => Math.max(mx, m.sort_order), -1);
        return [
          ...prev,
          {
            id: -Date.now(),
            resume_id: resumeId,
            module_type: type,
            content,
            sort_order: maxOrder + 1,
            created_at: new Date().toISOString(),
          },
        ];
      });
    },
    [resumeId, setModules],
  );

  // ── 模块拖拽排序 / 添加 / 删除 ──────────────────────────────

  const handleReorder = useCallback((orderedTypes: ModuleType[]) => {
    setModules((prev) => {
      const map = new Map(prev.map((m) => [m.module_type, m]));
      return orderedTypes
        .map((t, i) => {
          const m = map.get(t);
          return m ? { ...m, sort_order: i } : null;
        })
        .filter((m): m is ResumeModule => m !== null);
    });
  }, [setModules]);

  const handleAddModule = useCallback(
    (type: ModuleType) => {
      setModules((prev) => {
        if (prev.some((m) => m.module_type === type)) return prev;
        const maxOrder = prev.reduce((mx, m) => Math.max(mx, m.sort_order), -1);
        return [
          ...prev,
          {
            id: -Date.now(),
            resume_id: resumeId,
            module_type: type,
            content: {},
            sort_order: maxOrder + 1,
            created_at: new Date().toISOString(),
          },
        ];
      });
      // 新添加的模块自动展开
      setExpandedType(type);
    },
    [resumeId, setModules],
  );

  const handleRemoveModule = useCallback((type: ModuleType) => {
    setModules((prev) => prev.filter((m) => m.module_type !== type));
    setExpandedType((cur) => (cur === type ? null : cur));
  }, [setModules]);

  // ── 展开/折叠模块（手风琴模式） ────────────────────────────

  const handleToggleExpand = useCallback((type: ModuleType) => {
    setExpandedType((cur) => (cur === type ? null : type));
  }, []);

  // ── AI 生成 ─────────────────────────────────────────────────

  const handleAIGenerate = useCallback(
    (type: ModuleType, action?: AIAction, customPrompt?: string) => {
      setShowAIChat(true);
      const label = MODULE_LABELS[type];
      let question: string;
      switch (action) {
        case "polish":
          question = `请帮我润色${label}模块的内容，使其更专业、更简洁`;
          break;
        case "expand":
          question = `请帮我扩展${label}模块的内容，增加更多细节和成果描述`;
          break;
        case "translate":
          question = `请帮我把${label}模块的内容翻译成英文`;
          break;
        case "custom":
          question = customPrompt
            ? `针对${label}模块：${customPrompt}`
            : `请帮我生成${label}模块的内容`;
          break;
        default:
          question = `请帮我生成${label}模块的内容`;
      }
      setAiQuestion(question);
      setAiTrigger((t) => t + 1);
    },
    [],
  );

  // ── 手动保存草稿 ────────────────────────────────────────────

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
      notifyListRefresh();
    } catch {
      setSaveStatus("error");
    } finally {
      setSaving(false);
    }
  }, [resume, resumeId]);

  // ── 保存并完成 ──────────────────────────────────────────────

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
      notifyListRefresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "保存失败");
      setSaveStatus("error");
    } finally {
      setSaving(false);
    }
  }, [resume, resumeId, version]);

  // ── 浮层面板切换回调（稳定引用，避免子组件因新函数引用重渲染） ──
  const handleTogglePreviewCollapse = useCallback(() => {
    setPreviewCollapsed((v) => !v);
  }, []);
  const handleCloseStylePanel = useCallback(() => setShowStylePanel(false), []);
  const handleCloseAIChat = useCallback(() => setShowAIChat(false), []);

  // ── 渲染：加载中 ────────────────────────────────────────────

  if (loading) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center bg-[var(--color-bg)]">
        <span
          className="inline-block w-8 h-8 rounded-full border-2
            border-indigo-400 border-t-transparent animate-spin"
          aria-hidden="true"
        />
        <p className="text-sm text-[var(--color-text-muted)] mt-3">加载编辑器...</p>
      </div>
    );
  }

  // ── 渲染：错误状态 ──────────────────────────────────────────

  if (error && !resume) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center bg-[var(--color-bg)] px-6">
        <div className="w-16 h-16 rounded-2xl bg-red-500/10 border border-red-500/15
          flex items-center justify-center text-red-400 mb-5">
          <Warning size={28} weight="duotone" aria-hidden="true" />
        </div>
        <p className="text-base text-[var(--color-text-secondary)] mb-1.5">
          加载失败
        </p>
        <p className="text-sm text-[var(--color-text-muted)] mb-5 text-center max-w-sm">
          {error}
        </p>
        <button
          onClick={loadResume}
          className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl text-sm
            font-medium bg-indigo-500/15 text-indigo-300 border border-indigo-500/30
            hover:bg-indigo-500/25 active:scale-[0.98] motion-reduce:active:scale-100
            transition-all cursor-pointer"
        >
          <ArrowsClockwise size={14} weight="bold" aria-hidden="true" />
          重试
        </button>
      </div>
    );
  }

  if (!resume) return null;

  // ── 渲染：主布局（两栏） ────────────────────────────────────

  return (
    <div className="flex-1 flex flex-col overflow-hidden bg-[var(--color-bg)]">
      {/* ── 顶部工具栏 ── */}
      <div className="shrink-0 flex items-center justify-between gap-3 px-4 py-2.5
        border-b border-[var(--color-border)] bg-[var(--color-bg)]">
        {/* 左侧：文件名 + 保存状态 */}
        <div className="flex items-center gap-3 min-w-0">
          <input
            type="text"
            value={filename}
            onChange={(e) => setFilename(e.target.value)}
            placeholder="未命名简历"
            className="px-2 py-1 rounded-lg text-sm font-medium text-[var(--color-text)]
              bg-white/5 border border-transparent
              hover:border-[var(--color-border)]
              focus:outline-none focus:ring-2 focus:ring-indigo-500/40
              focus:border-indigo-500/50 focus:bg-white/8
              transition-all duration-150 min-w-[120px] max-w-[240px]"
            aria-label="文件名"
          />

          {/* 保存状态指示器 */}
          {saveStatus === "saving" && (
            <span className="flex items-center gap-1 text-[11px] text-[var(--color-text-muted)]">
              <span
                className="inline-block w-3 h-3 rounded-full border-2
                  border-indigo-400 border-t-transparent animate-spin"
                aria-hidden="true"
              />
              保存中...
            </span>
          )}
          {saveStatus === "saved" && (
            <span className="flex items-center gap-1 text-[11px] text-emerald-400">
              <Check size={11} weight="bold" aria-hidden="true" />
              已保存
            </span>
          )}
          {saveStatus === "error" && (
            <span className="flex items-center gap-1 text-[11px] text-red-400">
              <Warning size={11} weight="bold" aria-hidden="true" />
              保存失败
            </span>
          )}
        </div>

        {/* 右侧：操作按钮 */}
        <div className="flex items-center gap-1.5 shrink-0">
          {/* 撤销/重做 */}
          <button
            onClick={undo}
            disabled={!canUndo}
            className="inline-flex items-center justify-center w-7 h-7 rounded-lg
              text-[var(--color-text-muted)] border border-[var(--color-border)]
              hover:text-indigo-400 hover:border-indigo-500/30 hover:bg-indigo-500/8
              disabled:opacity-30 disabled:cursor-not-allowed
              active:scale-[0.95] motion-reduce:active:scale-100
              transition-all cursor-pointer"
            aria-label="撤销 (Ctrl+Z)"
            title="撤销 (Ctrl+Z)"
          >
            <ArrowCounterClockwise size={13} weight="regular" aria-hidden="true" />
          </button>
          <button
            onClick={redo}
            disabled={!canRedo}
            className="inline-flex items-center justify-center w-7 h-7 rounded-lg
              text-[var(--color-text-muted)] border border-[var(--color-border)]
              hover:text-indigo-400 hover:border-indigo-500/30 hover:bg-indigo-500/8
              disabled:opacity-30 disabled:cursor-not-allowed
              active:scale-[0.95] motion-reduce:active:scale-100
              transition-all cursor-pointer"
            aria-label="重做 (Ctrl+Shift+Z)"
            title="重做 (Ctrl+Shift+Z)"
          >
            <ArrowClockwise size={13} weight="regular" aria-hidden="true" />
          </button>

          {/* 分隔线 */}
          <div className="w-px h-5 bg-[var(--color-border)] mx-0.5" />

          {/* 保存草稿 */}
          <button
            onClick={handleSaveDraft}
            disabled={saving}
            className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg
              text-xs font-medium border border-[var(--color-border)]
              text-[var(--color-text-secondary)]
              hover:text-indigo-400 hover:border-indigo-500/30 hover:bg-indigo-500/8
              disabled:opacity-40 disabled:cursor-not-allowed
              active:scale-[0.98] motion-reduce:active:scale-100
              transition-all cursor-pointer"
            aria-label="保存草稿"
          >
            <FloppyDisk size={13} weight="regular" aria-hidden="true" />
            草稿
          </button>

          {/* 保存并完成 */}
          <button
            onClick={handleSaveComplete}
            disabled={saving}
            className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg
              text-xs font-semibold text-white
              bg-linear-to-br from-indigo-500 to-purple-600
              hover:brightness-110
              disabled:opacity-40 disabled:cursor-not-allowed
              active:scale-[0.98] motion-reduce:active:scale-100
              transition-all cursor-pointer"
            aria-label="保存并完成"
          >
            {saving ? (
              <span
                className="inline-block w-3 h-3 rounded-full border-2
                  border-white border-t-transparent animate-spin"
                aria-hidden="true"
              />
            ) : (
              <Check size={13} weight="bold" aria-hidden="true" />
            )}
            完成
          </button>

          {/* 分隔线 */}
          <div className="w-px h-5 bg-[var(--color-border)] mx-0.5" />

          {/* 样式切换 */}
          <button
            onClick={() => setShowStylePanel((v) => !v)}
            className={`inline-flex items-center gap-1 px-2 py-1.5 rounded-lg
              text-[11px] font-medium border transition-all cursor-pointer
              ${showStylePanel
                ? "bg-indigo-500/15 text-indigo-300 border-indigo-500/30"
                : "border-[var(--color-border)] text-[var(--color-text-muted)] hover:text-indigo-400 hover:border-indigo-500/30 hover:bg-indigo-500/8"
              }`}
            aria-label="样式配置"
            aria-pressed={showStylePanel}
          >
            <PaintBrush size={12} weight={showStylePanel ? "fill" : "regular"} aria-hidden="true" />
            样式
          </button>

          {/* AI 助手切换 */}
          <button
            onClick={() => setShowAIChat((v) => !v)}
            className={`inline-flex items-center gap-1 px-2 py-1.5 rounded-lg
              text-[11px] font-medium border transition-all cursor-pointer
              ${showAIChat
                ? "bg-indigo-500/15 text-indigo-300 border-indigo-500/30"
                : "border-[var(--color-border)] text-[var(--color-text-muted)] hover:text-indigo-400 hover:border-indigo-500/30 hover:bg-indigo-500/8"
              }`}
            aria-label="AI 助手"
            aria-pressed={showAIChat}
          >
            <ChatCircleDots size={12} weight={showAIChat ? "fill" : "regular"} aria-hidden="true" />
            AI
          </button>
        </div>
      </div>

      {/* 错误提示条 */}
      {error && resume && (
        <div className="shrink-0 px-4 py-1.5 bg-red-500/10 border-b border-red-500/20
          text-xs text-red-400 flex items-center justify-between">
          <span>{error}</span>
          <button
            onClick={() => setError("")}
            className="text-red-400 hover:text-red-300 cursor-pointer"
            aria-label="关闭错误提示"
          >
            ×
          </button>
        </div>
      )}

      {/* ── 两栏主体 ── */}
      <div className="flex-1 flex overflow-hidden">
        {/* 左栏：卡片式模块编辑器 */}
        <div className={`flex-1 min-w-0 overflow-hidden ${previewCollapsed ? "max-w-2xl" : ""}`}>
          <ModuleCardEditor
            resumeId={resumeId}
            modules={modules}
            expandedType={expandedType}
            onToggleExpand={handleToggleExpand}
            onChange={handleModuleChange}
            onReorder={handleReorder}
            onAdd={handleAddModule}
            onRemove={handleRemoveModule}
            onAIGenerate={handleAIGenerate}
          />
        </div>

        {/* 右栏：A4 预览面板 */}
        <div className={`shrink-0 ${previewCollapsed ? "w-12" : "w-[45%] min-w-[400px]"}`}>
          <A4PreviewPanel
            resumeId={resumeId}
            previewKey={previewKey}
            collapsed={previewCollapsed}
            onToggleCollapse={handleTogglePreviewCollapse}
            modulesData={previewData}
          />
        </div>

        {/* 浮动覆盖层：样式面板 */}
        <StylePanel
          style={style}
          onChange={setStyle}
          show={showStylePanel}
          onToggle={handleCloseStylePanel}
        />

        {/* 浮动覆盖层：AI 聊天面板 */}
        <BuilderAIChat
          resumeId={resumeId}
          show={showAIChat}
          onToggle={handleCloseAIChat}
          externalQuestion={aiQuestion}
          externalTrigger={aiTrigger}
          onAgentDone={refreshModules}
        />
      </div>
    </div>
  );
}
