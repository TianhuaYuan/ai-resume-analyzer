/**
 * Task 2: ModuleCard — 可折叠卡片式模块编辑组件。
 *
 * 每个模块渲染为卡片：
 * - 头部：拖拽手柄 + 模块名称 + AI 按钮 + 删除按钮
 * - 身体（展开时）：复用 ModuleForm 的字段配置渲染内联表单
 * - 身体（折叠时）：内容摘要预览（前 50 字符或"空模块"提示）
 *
 * 支持展开/折叠动画、选中高亮、空模块半透明。
 */

import { memo, useRef, useEffect, useState, useCallback, useMemo } from "react";
import {
  DotsSixVertical,
  Sparkle,
  TrashSimple,
  CaretDown,
  Eyeglasses,
  PencilSimple,
} from "@phosphor-icons/react";
import type { ModuleType, ModuleContent } from "../../api/builder";
import { MODULE_LABELS, isModuleEmpty } from "./ModuleList";
import {
  FieldRenderer,
  EntriesEditor,
  SkillsForm,
  InterestsForm,
  SocialLinksForm,
  TextContentForm,
  CustomFieldsEditor,
  BASIC_INFO_FIELDS,
  ENTRY_FIELD_CONFIGS,
  SOCIAL_LINK_FIELDS,
  getString,
  getListString,
  getEntries,
} from "./ModuleForm";
import { InlineAIPanel } from "./InlineAIPanel";
import { AvatarUpload } from "./AvatarUpload";

// ── AI 动作类型 ────────────────────────────────────────────────

export type AIAction = "generate" | "polish" | "expand" | "translate" | "custom";

// ── Props ──────────────────────────────────────────────────────

interface ModuleCardProps {
  /** 简历 ID（用于内联 AI 和头像上传） */
  resumeId: number;
  /** 模块类型 */
  moduleType: ModuleType;
  /** 模块内容 */
  content: ModuleContent;
  /** 是否展开 */
  expanded: boolean;
  /** 是否被拖拽中 */
  isDragging?: boolean;
  /** 是否为拖拽放置目标 */
  isDropTarget?: boolean;
  /** 在列表中的索引（拖拽回调用） */
  index: number;
  /** 点击头部切换展开/折叠（稳定引用，传 moduleType） */
  onToggleExpand: (type: ModuleType) => void;
  /** 内容变更回调（稳定引用，传 moduleType + content） */
  onChange: (type: ModuleType, content: ModuleContent) => void;
  /** AI 生成回调（稳定引用，传 moduleType + action） */
  onAIGenerate: (type: ModuleType, action?: AIAction, customPrompt?: string) => void;
  /** 删除模块回调（稳定引用，传 moduleType） */
  onRemove: (type: ModuleType) => void;
  /** 拖拽开始（稳定引用，传 index） */
  onDragStart: (index: number) => void;
  /** 拖拽经过（稳定引用，传 e + index） */
  onDragOver: (e: React.DragEvent, index: number) => void;
  /** 拖拽放下（稳定引用，传 e + index） */
  onDrop: (e: React.DragEvent, index: number) => void;
  /** 拖拽结束（稳定引用） */
  onDragEnd: () => void;
  /** 触摸拖拽开始（稳定引用，传 index） */
  onTouchDragStart?: (index: number) => void;
}

// ── 内容摘要提取 ────────────────────────────────────────────────

/** 从模块内容中提取摘要文本（前 50 字符） */
function getContentSummary(moduleType: ModuleType, content: ModuleContent): string {
  if (!content || Object.keys(content).length === 0) return "空模块";

  // basic_info：显示姓名 + 求职意向
  if (moduleType === "basic_info") {
    const name = getString(content, "name");
    const jobTitle = getString(content, "job_title");
    return [name, jobTitle].filter(Boolean).join(" · ") || "空模块";
  }

  // 条目类模块：显示条目数 + 第一条摘要
  const entryFields = ENTRY_FIELD_CONFIGS[moduleType];
  if (entryFields) {
    const entries = getEntries(content);
    if (entries.length === 0) return "空模块";
    const firstEntry = entries[0];
    const firstField = entryFields[0];
    const firstValue = firstField ? getString(firstEntry, firstField.key) : "";
    return `${entries.length} 条 · ${firstValue || "未命名"}`;
  }

  // skills：显示分类数
  if (moduleType === "skills") {
    const categories = content.categories;
    if (Array.isArray(categories) && categories.length > 0) {
      return `${categories.length} 个分类`;
    }
    return "空模块";
  }

  // interests：显示兴趣项数
  if (moduleType === "interests") {
    const items = content.items;
    if (Array.isArray(items) && items.length > 0) {
      return `${items.length} 项 · ${items.slice(0, 3).join(", ")}`;
    }
    return "空模块";
  }

  // social_links：显示已填字段数
  if (moduleType === "social_links") {
    const filled = SOCIAL_LINK_FIELDS.filter((f) => getString(content, f.key));
    return filled.length > 0 ? `${filled.length} 个链接` : "空模块";
  }

  // other / custom：显示标题或内容前 50 字符
  if (moduleType === "other" || moduleType === "custom") {
    const title = getString(content, "title");
    const text = getString(content, "content");
    return title || (text.slice(0, 50) + (text.length > 50 ? "..." : "")) || "空模块";
  }

  return "空模块";
}

// ── 模块文本提取（供 InlineAIPanel 使用） ────────────────────

/** 从模块内容中提取纯文本，用于 AI 优化/检查/改写 */
function getModuleText(moduleType: ModuleType, content: ModuleContent): string {
  if (!content || Object.keys(content).length === 0) return "";

  if (moduleType === "basic_info") {
    return [getString(content, "name"), getString(content, "job_title"), getString(content, "summary")]
      .filter(Boolean)
      .join("\n");
  }

  const entryFields = ENTRY_FIELD_CONFIGS[moduleType];
  if (entryFields) {
    const entries = getEntries(content);
    return entries
      .map((entry) =>
        entryFields
          .map((f) => {
            const val = f.type === "list" ? getListString(entry, f.key) : getString(entry, f.key);
            return val ? `${f.label}: ${val}` : "";
          })
          .filter(Boolean)
          .join("\n"),
      )
      .join("\n\n---\n\n");
  }

  if (moduleType === "skills") {
    const cats = content.categories;
    if (!Array.isArray(cats)) return "";
    return (cats as Array<{ name: string; items: string[] }>)
      .map((c) => `${c.name}: ${c.items.join(", ")}`)
      .join("\n");
  }

  if (moduleType === "interests") {
    const items = content.items;
    return Array.isArray(items) ? (items as string[]).join(", ") : "";
  }

  if (moduleType === "social_links") {
    return SOCIAL_LINK_FIELDS.map((f) => {
      const v = getString(content, f.key);
      return v ? `${f.label}: ${v}` : "";
    })
      .filter(Boolean)
      .join("\n");
  }

  // other / custom
  const title = getString(content, "title");
  const text = getString(content, "content");
  return [title, text].filter(Boolean).join("\n");
}

/** AI 结果应用到模块内容的主文本字段 */
function applyAIToContent(moduleType: ModuleType, content: ModuleContent, newText: string): ModuleContent {
  if (moduleType === "basic_info") {
    return { ...content, summary: newText };
  }

  const entryFields = ENTRY_FIELD_CONFIGS[moduleType];
  if (entryFields) {
    const entries = getEntries(content);
    if (entries.length > 0) {
      // 更新第一条目的 description 字段
      const descField = entryFields.find((f) => f.key === "description");
      if (descField) {
        const newEntries = [...entries];
        newEntries[0] = { ...newEntries[0], description: newText };
        return { ...content, entries: newEntries };
      }
    }
    return content;
  }

  if (moduleType === "other" || moduleType === "custom") {
    return { ...content, content: newText };
  }

  return content;
}

// ── 内联表单渲染 ────────────────────────────────────────────────

/** 渲染模块对应的内联表单字段（复用 ModuleForm 的子组件） */
function ModuleInlineForm({
  resumeId,
  moduleType,
  content,
  onChange,
}: {
  resumeId: number;
  moduleType: ModuleType;
  content: ModuleContent;
  onChange: (content: ModuleContent) => void;
}) {
  const label = MODULE_LABELS[moduleType];
  const entryFields = ENTRY_FIELD_CONFIGS[moduleType];

  if (moduleType === "basic_info") {
    return (
      <div className="space-y-3">
        {/* 头像上传 */}
        <div className="flex justify-center">
          <AvatarUpload
            resumeId={resumeId}
            avatarUrl={getString(content, "avatar") || null}
            onUpload={(url) => onChange({ ...content, avatar: url })}
            onDelete={() => {
              const next = { ...content };
              delete next.avatar;
              onChange(next);
            }}
          />
        </div>
        {/* 常规字段 */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {BASIC_INFO_FIELDS.map((field) => {
            const isFullWidth = field.type === "textarea";
            return (
              <div key={field.key} className={isFullWidth ? "sm:col-span-2" : ""}>
                <FieldRenderer
                  field={field}
                  value={getString(content, field.key)}
                  onChange={(v) => {
                    if (field.type === "number") {
                      onChange({ ...content, [field.key]: v === "" ? "" : Number(v) });
                    } else {
                      onChange({ ...content, [field.key]: v });
                    }
                  }}
                />
              </div>
            );
          })}
          <CustomFieldsEditor content={content} onChange={onChange} />
        </div>
      </div>
    );
  }

  if (entryFields) {
    return <EntriesEditor content={content} onChange={onChange} fields={entryFields} moduleLabel={label} />;
  }

  if (moduleType === "skills") {
    return <SkillsForm content={content} onChange={onChange} />;
  }

  if (moduleType === "interests") {
    return <InterestsForm content={content} onChange={onChange} />;
  }

  if (moduleType === "social_links") {
    return <SocialLinksForm content={content} onChange={onChange} />;
  }

  if (moduleType === "other" || moduleType === "custom") {
    return (
      <TextContentForm
        content={content}
        onChange={onChange}
        titleLabel={moduleType === "custom" ? "自定义标题" : "标题"}
        contentRequired
      />
    );
  }

  return null;
}

// ── 主组件 ──────────────────────────────────────────────────────

function ModuleCardImpl({
  resumeId,
  moduleType,
  content,
  expanded,
  isDragging = false,
  isDropTarget = false,
  index,
  onToggleExpand,
  onChange,
  onAIGenerate,
  onRemove,
  onDragStart,
  onDragOver,
  onDrop,
  onDragEnd,
  onTouchDragStart,
}: ModuleCardProps) {
  const label = MODULE_LABELS[moduleType];
  const isEmpty = isModuleEmpty(content);
  // useMemo 避免每次按键都重算摘要和文本
  const summary = useMemo(() => getContentSummary(moduleType, content), [moduleType, content]);
  const bodyRef = useRef<HTMLDivElement>(null);
  const [bodyHeight, setBodyHeight] = useState<number | "auto">("auto");
  const [aiMode, setAiMode] = useState<"optimize" | "check" | "rewrite" | null>(null);

  const moduleText = useMemo(() => getModuleText(moduleType, content), [moduleType, content]);

  // ref 持有最新 content，使 handleAIApply 不依赖 content → 回调引用稳定
  const contentRef = useRef(content);
  contentRef.current = content;

  // 稳定回调：依赖 moduleType + 父级稳定引用，不会因为其他模块变化而重建
  const handleInternalChange = useCallback(
    (newContent: ModuleContent) => onChange(moduleType, newContent),
    [moduleType, onChange],
  );

  const handleAIApply = useCallback(
    (newText: string) => {
      const updated = applyAIToContent(moduleType, contentRef.current, newText);
      onChange(moduleType, updated);
    },
    [moduleType, onChange],
  );

  // 展开/折叠动画：测量内容高度用于 max-height transition
  // 依赖 expanded + aiMode：aiMode 变化时（打开/关闭 AI 面板）重新测量高度
  useEffect(() => {
    if (!bodyRef.current) return;
    if (expanded) {
      const scrollHeight = bodyRef.current.scrollHeight;
      setBodyHeight(scrollHeight);
      // 动画完成后设为 auto 以适应动态内容
      const timer = setTimeout(() => setBodyHeight("auto"), 300);
      return () => clearTimeout(timer);
    } else {
      // 折叠前先设置当前高度，再动画到 0
      const scrollHeight = bodyRef.current.scrollHeight;
      setBodyHeight(scrollHeight);
      requestAnimationFrame(() => {
        requestAnimationFrame(() => setBodyHeight(0));
      });
    }
  }, [expanded, aiMode]);

  return (
    <div
      className={`group rounded-xl border transition-all duration-200
        ${expanded
          ? "bg-brand/5 border-brand/30 shadow-lg shadow-brand/5"
          : "bg-[var(--color-bg-secondary)] border-[var(--color-border)] hover:border-[var(--color-border)] hover:bg-[var(--color-bg-secondary)]"
        }
        ${isEmpty ? "opacity-60" : "opacity-100"}
        ${isDragging ? "opacity-50 scale-[0.98]" : ""}
        ${isDropTarget ? "ring-1 ring-brand/20" : ""}`}
      onDragOver={(e) => onDragOver(e, index)}
      onDrop={(e) => onDrop(e, index)}
    >
      {/* 卡片头部 */}
      <div
        className="flex items-center gap-1.5 px-3 py-2.5 cursor-pointer select-none touch-none"
        onClick={() => onToggleExpand(moduleType)}
        draggable
        onDragStart={() => onDragStart(index)}
        onDragEnd={onDragEnd}
        onTouchStart={(e) => {
          if (e.target instanceof HTMLElement && e.target.closest('[data-drag-handle]')) {
            onTouchDragStart?.(index);
          }
        }}
        role="button"
        tabIndex={0}
        aria-label={`${label}${expanded ? "（已展开）" : "（已折叠）"}`}
        aria-expanded={expanded}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            onToggleExpand(moduleType);
          }
        }}
      >
        {/* 拖拽手柄 */}
        <span
          data-drag-handle
          className="shrink-0 cursor-grab active:cursor-grabbing text-[var(--color-text-muted)]
            hover:text-[var(--color-text-secondary)] transition-colors"
          title="拖拽排序"
        >
          <DotsSixVertical size={14} weight="bold" aria-hidden="true" />
        </span>

        {/* 模块名称 */}
        <span
          className={`flex-1 text-sm truncate ${
            expanded
              ? "text-brand font-medium"
              : "text-[var(--color-text-secondary)]"
          }`}
        >
          {label}
        </span>

        {/* 折叠时显示摘要 */}
        {!expanded && (
          <span className="text-[11px] text-[var(--color-text-muted)] truncate max-w-[200px]">
            {summary}
          </span>
        )}

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
            onAIGenerate(moduleType, "generate");
          }}
          className="shrink-0 p-1 rounded text-[var(--color-text-muted)]
            hover:text-brand hover:bg-brand/10
            opacity-0 group-hover:opacity-100
            active:scale-90 motion-reduce:active:scale-100
            transition-all cursor-pointer"
          aria-label={`AI 生成${label}`}
          title="AI 生成"
        >
          <Sparkle size={12} weight="fill" aria-hidden="true" />
        </button>

        {/* 删除按钮 */}
        <button
          onClick={(e) => {
            e.stopPropagation();
            onRemove(moduleType);
          }}
          className="shrink-0 p-1 rounded text-[var(--color-text-muted)]
            hover:text-red-400 hover:bg-red-500/10
            opacity-0 group-hover:opacity-100
            active:scale-90 motion-reduce:active:scale-100
            transition-all cursor-pointer"
          aria-label={`删除${label}`}
          title="删除模块"
        >
          <TrashSimple size={12} weight="regular" aria-hidden="true" />
        </button>

        {/* 展开/折叠箭头 */}
        <CaretDown
          size={12}
          weight="bold"
          className={`shrink-0 text-[var(--color-text-muted)] transition-transform duration-200
            ${expanded ? "rotate-180" : ""}`}
          aria-hidden="true"
        />
      </div>

      {/* 卡片身体 — 展开/折叠动画 */}
      <div
        ref={bodyRef}
        className="overflow-hidden transition-all duration-300 ease-in-out"
        style={{
          // bodyHeight 为 "auto" 时用 "none"（不限制高度），
          // 否则用具体像素值驱动 transition 动画。
          // 注意：不能写 `${bodyHeight}px`，因为 "auto"+"px"="autopx" 是无效 CSS，
          // 浏览器会保留上一个 max-height 值导致内容被裁剪。
          maxHeight: expanded
            ? bodyHeight === "auto"
              ? "none"
              : `${bodyHeight}px`
            : "0px",
          opacity: expanded ? 1 : 0,
        }}
      >
        <div className="px-3 pb-4 pt-1">
          <ModuleInlineForm
            resumeId={resumeId}
            moduleType={moduleType}
            content={content}
            onChange={handleInternalChange}
          />

          {/* 内联 AI 面板（optimize / check / rewrite） */}
          {aiMode && moduleText && (
            <div className="mt-3">
              <InlineAIPanel
                resumeId={resumeId}
                moduleType={moduleType}
                text={moduleText}
                mode={aiMode}
                onModeChange={setAiMode}
                onApply={handleAIApply}
              />
            </div>
          )}

          {/* AI 辅助条：优化 / 检查 / 改写 */}
          <div className="mt-3 pt-2 border-t border-[var(--color-border)]/50">
            <div className="flex items-center gap-1 flex-wrap">
              <button
                onClick={() => setAiMode(aiMode === "optimize" ? null : "optimize")}
                className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-[10px] font-medium
                  transition-all cursor-pointer
                  ${aiMode === "optimize"
                    ? "bg-brand/10 text-brand border border-brand/30"
                    : "text-[var(--color-text-muted)] hover:text-brand hover:bg-brand/10 border border-transparent"
                  }`}
                disabled={!moduleText}
                aria-label="一键优化"
                title="AI 一键优化：润色措辞、增强专业感"
              >
                <Sparkle size={10} weight="fill" aria-hidden="true" />
                优化
              </button>

              <button
                onClick={() => setAiMode(aiMode === "check" ? null : "check")}
                className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-[10px] font-medium
                  transition-all cursor-pointer
                  ${aiMode === "check"
                    ? "bg-brand/10 text-brand border border-brand/30"
                    : "text-[var(--color-text-muted)] hover:text-brand hover:bg-brand/10 border border-transparent"
                  }`}
                disabled={!moduleText}
                aria-label="智能检查"
                title="AI 智能检查：发现问题并给出修改建议"
              >
                <Eyeglasses size={10} weight="bold" aria-hidden="true" />
                检查
              </button>

              <button
                onClick={() => setAiMode(aiMode === "rewrite" ? null : "rewrite")}
                className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-[10px] font-medium
                  transition-all cursor-pointer
                  ${aiMode === "rewrite"
                    ? "bg-brand/10 text-brand border border-brand/30"
                    : "text-[var(--color-text-muted)] hover:text-brand hover:bg-brand/10 border border-transparent"
                  }`}
                disabled={!moduleText}
                aria-label="智能改写"
                title="AI 智能改写：按指令改写内容"
              >
                <PencilSimple size={10} weight="bold" aria-hidden="true" />
                改写
              </button>

              {!moduleText && (
                <span className="text-[10px] text-[var(--color-text-muted)] italic">
                  请先填写内容
                </span>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export const ModuleCard = memo(ModuleCardImpl);
