/**
 * BuilderPage — 简历编辑器主编排页面。
 *
 * 两栏布局：ModuleCardEditor（左）| A4PreviewPanel（右）
 * 顶部工具栏：文件名编辑、保存草稿、保存完成、样式切换、AI 切换
 *
 * 核心机制：
 * - 挂载时加载 builder 简历 + 获取编辑锁
 * - 编辑锁心跳续期 60s，卸载时释放
 * - 编辑默认仅保留在本地，用户显式选择“保存草稿”或“保存并完成”才持久化
 * - 预览防抖：内容变更后 300ms 刷新 iframe
 * - 样式状态本地管理，随草稿保存
 * - StylePanel 和 BuilderAIChat 为浮动覆盖层
 */

import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { Save, Check, Paintbrush, TriangleAlert, RefreshCw, RotateCcw, RotateCw, GitBranch, ClipboardList, LayoutGrid, Globe, ChevronDown, Plus, Eye, Pencil, ScanSearch } from "lucide-react";
import {
  getBuilderResume,
  saveDraft,
  saveComplete,
  acquireEditLock,
  renewEditLock,
  releaseEditLock,
  translateResume,
} from "../api/builder";
import VersionHistoryDialog from "../components/VersionHistoryDialog";
import PendingChangesDialog from "../components/PendingChangesDialog";
import PasteResumeDialog from "../components/builder/PasteResumeDialog";
import type {
  BuilderResume,
  ResumeModule,
  ResumeStyle,
  ModuleType,
  ModuleContent,
  ResumeModuleInput,
} from "../api/builder";
import { ModuleCardEditor } from "../components/builder/ModuleCardEditor";
import { A4PreviewPanel } from "../components/builder/A4PreviewPanel";
import { StylePanel } from "../components/builder/StylePanel";
import { TemplateSheet } from "../components/builder/TemplateSheet";
import { getTemplateConfigs } from "../components/templates/registry";
import AtsAuditReport from "../components/AtsAuditReport";
import { trackEvent } from "../api/analytics";
import { copyResume, getResumeFamily, auditResume } from "../api/resumes";
import { listPendingChanges } from "../api/pendingChanges";
import type { ResumeFamilyItem, AtsAuditResult } from "../api/resumes";
import { useToast } from "../components/Toast";
import { useNavigate } from "react-router-dom";
import { useHistory } from "../hooks/useHistory";
import { confirmUnsavedChanges, registerUnsavedChangesGuard } from "../utils/unsavedChanges";

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

// ── 多语言版本标签辅助 ────────────────────────────────────────
const LANG_LABELS: Record<string, string> = {
  zh: "中文",
  en: "英文",
  ja: "日文",
  ko: "韩文",
};
function langLabel(lang: string | null): string {
  if (!lang) return "原文";
  return LANG_LABELS[lang] ?? lang.toUpperCase();
}

// ── 主组件 ────────────────────────────────────────────────────

export function BuilderPage({ resumeId }: BuilderPageProps) {
  // 加载与错误状态
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const toast = useToast();

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
  const [showTemplateSheet, setShowTemplateSheet] = useState(false);
  const [previewCollapsed, setPreviewCollapsed] = useState(false);
  const [mobilePreviewOpen, setMobilePreviewOpen] = useState(false);
  const [previewKey, setPreviewKey] = useState(0);

  // 保存状态
  const [saving, setSaving] = useState(false);
  const [saveStatus, setSaveStatus] = useState<"idle" | "saving" | "saved" | "error">("idle");
  // T17: 最近一次成功的保存模式（draft → 草稿即时保存；complete → 已保存并完成）
  const [lastSaveMode, setLastSaveMode] = useState<"draft" | "complete" | null>(null);
  // 未保存修改标记：编辑后置 true，仅显式"草稿/完成"保存成功后置 false。
  // 不再自动保存——修改内容不落库，直到用户主动点击保存（配合 beforeunload 提示）。
  const [isDirty, setIsDirty] = useState(false);

  // T17: 索引新鲜度（从 GET /resumes/{id} 的 is_indexed / is_stale 读取）
  const [indexInfo, setIndexInfo] = useState<{ is_indexed: boolean; is_stale: boolean } | null>(null);

  // T18: 版本历史弹窗
  const [showVersionHistory, setShowVersionHistory] = useState(false);

  // P0-A: ATS 审计弹窗
  const [showAtsAudit, setShowAtsAudit] = useState(false);
  const [atsAuditResult, setAtsAuditResult] = useState<AtsAuditResult | null>(null);
  const [atsAuditLoading, setAtsAuditLoading] = useState(false);

  // 粘贴简历文本弹窗
  const [showPasteDialog, setShowPasteDialog] = useState(false);

  // E2: 待审阅改动（rewrite_star/translate/rewrite_resume 落库的字段级 diff 审阅队列）
  const [showPendingChanges, setShowPendingChanges] = useState(false);
  const [pendingCount, setPendingCount] = useState<number | null>(null);

  // 上传简历懒物化标记：false = LLM 反解析失败，需提示用户粘贴导入
  const [materialized, setMaterialized] = useState(true);

  // ── 多语言版本管理（G） ─────────────────────────────────────
  const navigate = useNavigate();
  const [family, setFamily] = useState<ResumeFamilyItem[] | null>(null);
  const [showLangMenu, setShowLangMenu] = useState(false);
  const [langBusy, setLangBusy] = useState(false);

  // 新建语言版本：copyResume → 自动翻译副本 → 跳转新副本
  const handleCreateLangVersion = useCallback(
    async (language: string) => {
      if (langBusy) return;
      if (!confirmUnsavedChanges()) return;
      setLangBusy(true);
      try {
        const res = (await copyResume(resumeId, language)) as { id?: number };
        if (!res?.id) throw new Error("创建语言版本失败");
        // 自动翻译副本为目标语言（LLM 调用，翻译中按钮禁用；失败保留未翻译副本）
        await translateResume(res.id, language);
        navigate(`/resumes/${res.id}/edit`);
      } catch (err) {
        setError(err instanceof Error ? err.message : "创建语言版本失败");
        setLangBusy(false);
      }
    },
    [resumeId, langBusy, navigate],
  );

  // Refs（避免闭包陷阱）
  const lockTokenRef = useRef<string | null>(null);
  const modulesRef = useRef(modules);
  const filenameRef = useRef(filename);
  const styleRef = useRef(style);
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
      // 多语言版本族（best-effort，失败静默为空）
      getResumeFamily(resumeId).then(setFamily).catch(() => setFamily([]));
      setVersion(data.version);
      setStyle(data.style ?? DEFAULT_STYLE);
      // T17 渲染优化：索引新鲜度并入 builder 响应，无需再单独拉 getResume
      setIndexInfo({
        is_indexed: data.is_indexed ?? false,
        is_stale: data.is_stale ?? false,
      });
      setMaterialized(data.modules_materialized ?? true);
      setExpandedType("basic_info");
      setSaveStatus("idle");
      setIsDirty(false); // 加载完成即与已保存一致，无未保存修改
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
    // 移除 500ms 硬编码防抖延迟：onAgentDone 每轮只触发一次，前置 sleep 是纯浪费，
    // 会让每次 agent 回复（含问候）凭空 +500ms 才更新模块。
    try {
      const data = await getBuilderResume(resumeId);
      setResume(data);
      resetHistory(data.modules ?? []);
      setVersion(data.version);
      setMaterialized(data.modules_materialized ?? true);
      // 索引新鲜度同步（builder 响应已并入）
      setIndexInfo({
        is_indexed: data.is_indexed ?? false,
        is_stale: data.is_stale ?? false,
      });
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

  // ── E2: 待审阅改动数量（入口徽标） ────────────────────────────
  // 挂载时 + 改写类工具落库通知（resume:modules-refresh）后刷新计数。
  const loadPendingCount = useCallback(async () => {
    try {
      const res = await listPendingChanges(resumeId);
      setPendingCount(res.total ?? 0);
    } catch {
      // 静默失败，入口不显示数量徽标
    }
  }, [resumeId]);

  useEffect(() => {
    void loadPendingCount();
    const sync = () => {
      void loadPendingCount();
    };
    window.addEventListener("resume:modules-refresh", sync);
    return () => window.removeEventListener("resume:modules-refresh", sync);
  }, [loadPendingCount]);

  // ── T17: 索引新鲜度（懒索引脏标记 is_indexed / is_stale） ──

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

  // ── 未保存修改追踪（不再自动保存：用户显式点击「草稿/完成」才落库） ──

  // 首次加载 / 简历重载（firstEditRef=true，loadResume 完成时重置）不置脏；
  // 之后 modules/filename/style 任一变化 → 标记未保存，同时清除"已保存"提示。
  // 依赖不能含 resume：保存成功后 handleSaveComplete 会 setResume(result) 回填，
  // 若把 resume 当触发源会误把刚保存的内容重新标记为"未保存"（"完成"按钮看起来没反应）。
  useEffect(() => {
    if (firstEditRef.current) {
      firstEditRef.current = false;
      return;
    }
    if (!resumeId) return;
    setIsDirty(true);
    setSaveStatus("idle");
  }, [modules, filename, style, resumeId]);

  // 未保存时关闭/刷新页面提示确认（浏览器原生 beforeunload；
  // 站内路由切换不在保护范围，需用户主动保存后再离开）
  useEffect(() => {
    if (!isDirty) return;
    const handleBeforeUnload = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [isDirty]);

  useEffect(
    () => registerUnsavedChangesGuard(
      () => !isDirty || window.confirm("当前简历有未保存的修改，确定离开并放弃这些修改吗？"),
    ),
    [isDirty],
  );

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

  // ── P0-A: ATS 审计 ─────────────────────────────────────────

  const handleAtsAudit = useCallback(async () => {
    if (!resume) return;
    setAtsAuditLoading(true);
    setAtsAuditResult(null);
    setShowAtsAudit(true);
    try {
      const result = await auditResume(resume.id);
      setAtsAuditResult(result);
    } catch (err) {
      setAtsAuditResult(null);
      // 错误由弹窗内显示
    } finally {
      setAtsAuditLoading(false);
    }
  }, [resume]);

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
      setLastSaveMode("draft"); // T17: 草稿即时保存（不等待向量）
      setIsDirty(false); // 已显式保存，清除未保存标记
      notifyListRefresh();
      toast.success("草稿已保存");
    } catch (e) {
      setSaveStatus("error");
      toast.error(e instanceof Error ? e.message : "保存草稿失败");
    } finally {
      setSaving(false);
    }
  }, [resume, resumeId, toast]);

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
      setLastSaveMode("complete"); // T17: 保存并完成（触发索引预热）→ 提示可开始问答/检索
      setIsDirty(false); // 已保存并完成，清除未保存标记
      notifyListRefresh();
      // T17: complete 会触发索引预热，刷新索引新鲜度标识（builder 响应已并入）
      setIndexInfo({
        is_indexed: result.is_indexed ?? false,
        is_stale: result.is_stale ?? false,
      });
      toast.success("已保存并完成，可开始问答/检索");
    } catch (e) {
      const msg = e instanceof Error ? e.message : "保存失败";
      setError(msg);
      setSaveStatus("error");
      toast.error(msg);
    } finally {
      setSaving(false);
    }
  }, [resume, resumeId, version, toast]);

  // ── 浮层面板切换回调（稳定引用，避免子组件因新函数引用重渲染） ──
  const handleTogglePreviewCollapse = useCallback(() => {
    setPreviewCollapsed((v) => !v);
  }, []);
  const handleCloseStylePanel = useCallback(() => setShowStylePanel(false), []);

  // ── 模板切换（只改模板结构 + 间距；不再覆盖用户自定义主题色 accent_color，
  //    主题色独立在样式面板控制，修复"切模板把用户主题色抹掉"） ──
  const handleSetTemplate = useCallback((templateId: string) => {
    const template = getTemplateConfigs().find((t) => t.id === templateId);
    if (!template) return;
    setStyle((prev) => ({
      ...prev,
      template_id: templateId,
      margin: `${template.spacing.contentPadding}px`,
      section_spacing: `${template.spacing.sectionGap}px`,
      spacing: `${template.spacing.itemGap}px`,
    }));
    setShowTemplateSheet(false);
  }, []);

  // ── 粘贴简历文本回调 ──
  const handlePasteParsed = useCallback(
    (parsedModules: ResumeModuleInput[], parsedFilename?: string) => {
      // 把解析的模块转为 ResumeModule 格式并替换当前内容
      const newModules: ResumeModule[] = parsedModules.map((m, i) => ({
        id: -Date.now() - i,
        resume_id: resumeId,
        module_type: m.module_type,
        content: m.content,
        sort_order: m.sort_order,
        created_at: new Date().toISOString(),
      }));
      setModules(newModules);
      if (parsedFilename) setFilename(parsedFilename);
      // 自动展开第一个模块
      if (newModules.length > 0) {
        setExpandedType(newModules[0].module_type);
      }
    },
    [resumeId, setModules],
  );

  // ── 渲染：加载中 ────────────────────────────────────────────

  if (loading) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center bg-[var(--color-bg)]">
        <span
          className="inline-block w-8 h-8 rounded-full border-2
            border-brand border-t-transparent animate-spin"
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
        <div className="w-16 h-16 rounded-input bg-danger/10 border border-danger/15
          flex items-center justify-center text-danger mb-5">
          <TriangleAlert size={28} fill="currentColor" aria-hidden="true" />
        </div>
        <p className="text-base text-[var(--color-text-secondary)] mb-1.5">
          加载失败
        </p>
        <p className="text-sm text-[var(--color-text-muted)] mb-5 text-center max-w-sm">
          {error}
        </p>
        <button
          onClick={loadResume}
          className="inline-flex items-center gap-1.5 px-4 py-2 rounded-list text-sm
            font-medium bg-brand/15 text-brand border border-brand/30
            hover:bg-brand/25 active:scale-[0.98] motion-reduce:active:scale-100
            transition-all cursor-pointer"
        >
          <RefreshCw size={14} strokeWidth={2.25} aria-hidden="true" />
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
      <div className="shrink-0 flex flex-col items-stretch sm:flex-row sm:items-center sm:justify-between gap-2 sm:gap-3 px-3 sm:px-4 py-2.5
        border-b border-[var(--color-border)] bg-white/80 backdrop-blur-xl">
        {/* 左侧：文件名 + 保存状态 */}
        <div className="flex w-full sm:w-auto flex-wrap items-center gap-2 sm:gap-3 min-w-0">
          <input
            type="text"
            value={filename}
            onChange={(e) => setFilename(e.target.value)}
            placeholder="未命名简历"
            className="px-2 py-1 rounded-full text-sm font-medium text-[var(--color-text)]
              bg-[#F2F2F7] border border-transparent
              hover:border-[var(--color-border)]
              focus:outline-none focus:bg-white focus:border-brand/40
              focus:ring-4 focus:ring-brand/15
              transition-all duration-150 min-w-0 w-[min(55vw,200px)] sm:min-w-[120px] sm:max-w-[240px]"
            aria-label="文件名"
          />

          {/* 多语言版本管理（G）：下拉列同 family 版本 + 新建语言版 */}
          <div className="relative shrink-0">
            <button
              onClick={() => {
                setShowLangMenu((v) => !v);
                if (family === null) {
                  getResumeFamily(resumeId).then(setFamily).catch(() => setFamily([]));
                }
              }}
              className="btn-tool"
              aria-label="语言版本"
              title="语言版本管理"
            >
              <Globe size={13} aria-hidden="true" />
              {resume?.language ? langLabel(resume.language) : "语言"}
              <ChevronDown size={10} strokeWidth={2.25} aria-hidden="true" />
            </button>

            {showLangMenu && (
              <div className="absolute left-0 top-full mt-1.5 z-30 min-w-[230px] rounded-list
                bg-white shadow-lg border border-[var(--color-border)] overflow-hidden animate-fade-in-up motion-reduce:animate-none">
                <div className="px-3 py-2 text-[10px] font-medium text-[var(--color-text-muted)] uppercase tracking-wider">
                  语言版本
                </div>

                {family === null ? (
                  <div className="px-3 py-4 text-xs text-[var(--color-text-muted)] text-center">加载中...</div>
                ) : family.length === 0 ? (
                  <div className="px-3 py-4 text-xs text-[var(--color-text-muted)] text-center">暂无其他版本</div>
                ) : (
                  <div className="max-h-56 overflow-y-auto">
                    {family.map((v) => (
                      <button
                        key={v.id}
                        onClick={() => {
                          if (v.id !== resumeId && confirmUnsavedChanges()) {
                            navigate(`/resumes/${v.id}/edit`);
                          }
                          setShowLangMenu(false);
                        }}
                        className={`w-full flex items-center justify-between gap-2 px-3 py-2 text-left
                          text-xs hover:bg-[var(--color-bg-secondary)] transition-colors cursor-pointer
                          ${v.id === resumeId ? "text-brand font-medium" : "text-[var(--color-text-secondary)]"}`}
                      >
                        <span className="truncate">{v.filename}</span>
                        <span className={`shrink-0 px-1.5 py-0.5 rounded text-[10px] font-medium
                          ${v.id === resumeId
                            ? "bg-brand/10 text-brand"
                            : "bg-[#F2F2F7] text-[var(--color-text-muted)]"}`}>
                          {langLabel(v.language)}
                        </span>
                      </button>
                    ))}
                  </div>
                )}

                <div className="border-t border-[var(--color-border)] p-1.5 space-y-0.5">
                  <div className="px-3 py-1 text-[10px] font-medium text-[var(--color-text-muted)]">
                    新建语言版本
                  </div>
                  {["zh", "en"].map((lang) => (
                    <button
                      key={lang}
                      onClick={() => handleCreateLangVersion(lang)}
                      disabled={langBusy}
                      className="w-full flex items-center gap-1.5 px-3 py-1.5 text-xs
                        text-[var(--color-text-secondary)] hover:text-brand hover:bg-[var(--color-bg-secondary)]
                        disabled:opacity-40 disabled:cursor-not-allowed transition-colors cursor-pointer"
                    >
                      <Plus size={12} strokeWidth={2.25} aria-hidden="true" />
                      {langBusy ? "翻译中..." : `新建${langLabel(lang)}版`}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* 保存状态指示器（优先级：saving > error > 未保存 > 已保存） */}
          {saveStatus === "saving" && (
            <span className="flex items-center gap-1 text-[11px] text-[var(--color-text-muted)]">
              <span
                className="inline-block w-3 h-3 rounded-full border-2
                  border-brand border-t-transparent animate-spin"
                aria-hidden="true"
              />
              保存中...
            </span>
          )}
          {saveStatus === "error" && (
            <span className="flex items-center gap-1 text-[11px] text-danger">
              <TriangleAlert size={11} strokeWidth={2.25} aria-hidden="true" />
              保存失败
            </span>
          )}
          {isDirty && saveStatus !== "saving" && saveStatus !== "error" && (
            <span
              className="flex items-center gap-1 text-[11px] text-warning"
              title="有未保存的修改，点击「草稿」或「完成」保存"
            >
              <TriangleAlert size={11} strokeWidth={2.25} aria-hidden="true" />
              未保存的修改
            </span>
          )}
          {!isDirty && saveStatus === "saved" && (
            <span
              className="flex items-center gap-1 text-[11px] text-success"
              title={lastSaveMode === "complete" ? "已保存并完成，可开始问答/检索" : "草稿已保存"}
            >
              <Check size={11} strokeWidth={2.25} aria-hidden="true" />
              {lastSaveMode === "complete"
                ? "已保存并完成，可开始问答/检索"
                : "已保存"}
            </span>
          )}

          {/* T17: 索引新鲜度标识（懒索引脏标记 is_indexed / is_stale） */}
          {resume.status !== "draft" && indexInfo && !indexInfo.is_indexed && (
            <span
              className="hidden sm:inline-flex items-center gap-1 px-2 py-0.5 rounded-full
                text-[10px] font-medium bg-sky-500/15 text-sky-600
                border border-sky-500/30 shrink-0"
              title="尚未建立检索索引，首次问答时会自动建立"
            >
              未建索引
            </span>
          )}
          {resume.status !== "draft" && indexInfo && indexInfo.is_indexed && indexInfo.is_stale && (
            <span
              className="hidden sm:inline-flex items-center gap-1 px-2 py-0.5 rounded-full
                text-[10px] font-medium bg-warning/15 text-warning
                border border-warning/30 shrink-0"
              title="内容已更新，检索将自动重建"
            >
              索引待重建
            </span>
          )}
          {resume.status !== "draft" && indexInfo && indexInfo.is_indexed && !indexInfo.is_stale && (
            <span
              className="hidden sm:inline-flex items-center gap-1 px-2 py-0.5 rounded-full
                text-[10px] font-medium bg-success/15 text-success
                border border-success/30 shrink-0"
              title="检索索引已就绪"
            >
              索引已就绪
            </span>
          )}
        </div>

        {/* 右侧：操作按钮 */}
        <div className="flex w-full sm:w-auto flex-wrap items-center gap-1.5 sm:shrink-0">
          <button
            type="button"
            onClick={() => setMobilePreviewOpen((value) => !value)}
            className="btn-tool sm:hidden"
            aria-label={mobilePreviewOpen ? "返回编辑" : "预览简历"}
          >
            {mobilePreviewOpen ? <Pencil size={13} aria-hidden="true" /> : <Eye size={13} aria-hidden="true" />}
            {mobilePreviewOpen ? "编辑" : "预览"}
          </button>
          {/* 撤销/重做 */}
          <button
            onClick={undo}
            disabled={!canUndo}
            className="btn-tool-icon"
            aria-label="撤销 (Ctrl+Z)"
            title="撤销 (Ctrl+Z)"
          >
            <RotateCcw size={13} aria-hidden="true" />
          </button>
          <button
            onClick={redo}
            disabled={!canRedo}
            className="btn-tool-icon"
            aria-label="重做 (Ctrl+Shift+Z)"
            title="重做 (Ctrl+Shift+Z)"
          >
            <RotateCw size={13} aria-hidden="true" />
          </button>

          {/* 分隔线 */}
          <div className="w-px h-5 bg-[var(--color-border)] mx-0.5" />

          {/* 粘贴简历文本 */}
          <button
            onClick={() => setShowPasteDialog(true)}
            className="btn-tool"
            aria-label="粘贴简历文本"
            title="粘贴简历文本"
          >
            <ClipboardList size={13} aria-hidden="true" />
            粘贴导入
          </button>

          {/* 分隔线 */}
          <div className="w-px h-5 bg-[var(--color-border)] mx-0.5" />

          {/* 保存草稿 */}
          <button
            onClick={handleSaveDraft}
            disabled={saving}
            className="inline-flex min-h-10 sm:min-h-0 items-center gap-1 px-2.5 py-1.5 rounded-full
              text-xs font-medium text-[var(--color-text-secondary)]
              bg-[var(--color-bg-secondary)] hover:bg-[var(--color-bg-secondary)]
              disabled:opacity-40 disabled:cursor-not-allowed
              active:scale-[0.98] motion-reduce:active:scale-100
              transition-all cursor-pointer"
            aria-label="保存草稿"
          >
            <Save size={13} aria-hidden="true" />
            草稿
          </button>

          {/* 保存并完成 */}
          <button
            onClick={handleSaveComplete}
            disabled={saving}
            className="inline-flex min-h-10 sm:min-h-0 items-center gap-1 px-2.5 py-1.5 rounded-full
              text-xs font-semibold text-white bg-brand
              hover:bg-brand-hover hover:scale-[1.02]
              disabled:opacity-40 disabled:cursor-not-allowed
              active:scale-[0.98] motion-reduce:active:scale-100
              transition-all duration-300 cursor-pointer"
            aria-label="保存并完成"
          >
            {saving ? (
              <span
                className="inline-block w-3 h-3 rounded-full border-2
                  border-white border-t-transparent animate-spin"
                aria-hidden="true"
              />
            ) : (
              <Check size={13} strokeWidth={2.25} aria-hidden="true" />
            )}
            完成
          </button>

          {/* 分隔线 */}
          <div className="w-px h-5 bg-[var(--color-border)] mx-0.5" />

          {/* 模板切换 */}
          <button
            onClick={() => setShowTemplateSheet(true)}
            className="btn-tool"
            aria-label="切换模板"
            title="切换简历模板"
          >
            <LayoutGrid size={12} aria-hidden="true" />
            模板
          </button>

          {/* 样式切换 */}
          <button
            onClick={() => setShowStylePanel((v) => !v)}
            className={`btn-tool ${showStylePanel ? "btn-tool-active" : ""}`}
            aria-label="样式配置"
            aria-pressed={showStylePanel}
          >
            <Paintbrush size={12} fill={showStylePanel ? "currentColor" : "none"} aria-hidden="true" />
            样式
          </button>

          {/* T18: 版本历史 */}
          <button
            onClick={() => setShowVersionHistory(true)}
            className="btn-tool"
            aria-label="版本历史"
            title="查看检索索引版本历史"
          >
            <GitBranch size={12} aria-hidden="true" />
            版本
          </button>

          {/* P0-A: ATS 审计 */}
          <button
            onClick={handleAtsAudit}
            className="btn-tool"
            aria-label="ATS 审计"
            title="模拟 ATS 解析，检测简历可读性问题"
          >
            <ScanSearch size={12} aria-hidden="true" />
            ATS
          </button>

          {/* E2: 待审阅改动（AI 改写/翻译的字段级 diff 审阅队列） */}
          <button
            onClick={() => {
              setShowPendingChanges(true);
              void loadPendingCount();
            }}
            className="btn-tool relative"
            aria-label="待审阅改动"
            title="审阅 AI 改写的字段级改动"
          >
            <ClipboardList size={12} aria-hidden="true" />
            待审阅
            {pendingCount !== null && pendingCount > 0 && (
              <span
                className="absolute -top-1 -right-1 min-w-4 h-4 px-0.5 rounded-full
                  bg-danger text-white text-[9px] font-bold
                  flex items-center justify-center"
              >
                {pendingCount > 99 ? "99+" : pendingCount}
              </span>
            )}
          </button>
        </div>
      </div>

      {/* 错误提示条 */}
      {error && resume && (
        <div className="shrink-0 px-4 py-1.5 bg-danger/10 border-b border-danger/20
          text-xs text-danger flex items-center justify-between">
          <span>{error}</span>
          <button
            onClick={() => setError("")}
            className="text-danger hover:text-danger cursor-pointer"
            aria-label="关闭错误提示"
          >
            ×
          </button>
        </div>
      )}

      {/* 上传简历物化失败提示：解析结果未能自动转为模块，引导粘贴导入 */}
      {materialized === false && (
        <div className="shrink-0 px-4 py-2 bg-warning/10 border-b border-warning/20
          text-xs text-warning flex items-center justify-between gap-3">
          <span>简历解析结果未能自动转为可编辑模块。</span>
          <button
            onClick={() => setShowPasteDialog(true)}
            className="inline-flex items-center gap-1 px-3 py-1 rounded-full bg-brand/10 text-brand border border-brand/20
              hover:bg-brand/20 transition-all cursor-pointer shrink-0"
          >
            <ClipboardList size={12} strokeWidth={2.25} aria-hidden="true" />
            粘贴导入恢复
          </button>
        </div>
      )}

      {/* ── 两栏主体 ── */}
      <div className="flex-1 flex overflow-hidden">
        {/* 左栏：卡片式模块编辑器 */}
        <div className={`${mobilePreviewOpen ? "hidden sm:block" : "block"} w-full min-w-0 overflow-hidden sm:w-auto ${previewCollapsed ? "sm:max-w-2xl" : "sm:w-[45%] sm:min-w-[380px] sm:max-w-[520px]"}`}>
          <ModuleCardEditor
            resumeId={resumeId}
            modules={modules}
            expandedType={expandedType}
            onToggleExpand={handleToggleExpand}
            onChange={handleModuleChange}
            onReorder={handleReorder}
            onAdd={handleAddModule}
            onRemove={handleRemoveModule}
          />
        </div>

        {/* 右栏：A4 预览面板 */}
        <div className={`${mobilePreviewOpen ? "block" : "hidden sm:block"} flex-1 min-w-0 ${previewCollapsed ? "w-12 shrink-0" : ""}`}>
          <A4PreviewPanel
            resumeId={resumeId}
            previewKey={previewKey}
            collapsed={previewCollapsed}
            onToggleCollapse={handleTogglePreviewCollapse}
            modulesData={previewData}
            onSelectSection={setExpandedType}
          />
        </div>

        {/* 浮动覆盖层：样式面板 */}
        <StylePanel
          style={style}
          onChange={setStyle}
          show={showStylePanel}
          onToggle={handleCloseStylePanel}
        />

        {/* 浮动覆盖层：模板切换抽屉 */}
        <TemplateSheet
          open={showTemplateSheet}
          onClose={() => setShowTemplateSheet(false)}
          modules={modules}
          style={style}
          currentTemplateId={style.template_id}
          onSelect={handleSetTemplate}
        />

        {/* T18: 版本历史弹窗 */}
        <VersionHistoryDialog
          resumeId={resumeId}
          resumeFilename={filename}
          open={showVersionHistory}
          onClose={() => setShowVersionHistory(false)}
        />

        {/* 粘贴简历文本弹窗 */}
        <PasteResumeDialog
          open={showPasteDialog}
          onClose={() => setShowPasteDialog(false)}
          onParsed={handlePasteParsed}
        />

        {/* P0-A: ATS 审计弹窗 */}
        {showAtsAudit && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
            <div className="bg-[var(--color-bg)] rounded-list shadow-2xl w-full max-w-lg max-h-[80vh] overflow-y-auto p-6">
              {atsAuditLoading ? (
                <div className="text-center py-12">
                  <div className="animate-spin w-8 h-8 border-2 border-[var(--color-accent)] border-t-transparent rounded-full mx-auto mb-4" />
                  <div className="text-sm text-[var(--color-text-secondary)]">
                    正在执行 ATS 审计...
                  </div>
                </div>
              ) : atsAuditResult ? (
                <AtsAuditReport
                  result={atsAuditResult}
                  onClose={() => setShowAtsAudit(false)}
                />
              ) : (
                <div className="text-center py-12">
                  <div className="text-sm text-danger">
                    ATS 审计失败，请稍后重试
                  </div>
                  <button
                    onClick={() => setShowAtsAudit(false)}
                    className="mt-4 px-4 py-2 rounded-action bg-[var(--color-bg-secondary)] text-[var(--color-text-secondary)] text-sm hover:bg-[var(--color-bg-tertiary)]"
                  >
                    关闭
                  </button>
                </div>
              )}
            </div>
          </div>
        )}

        {/* E2: 待审阅改动弹窗 */}
        <PendingChangesDialog
          resumeId={resumeId}
          open={showPendingChanges}
          onClose={() => {
            setShowPendingChanges(false);
            void loadPendingCount();
          }}
          onChanged={loadPendingCount}
        />
      </div>
    </div>
  );
}
