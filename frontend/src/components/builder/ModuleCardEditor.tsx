/**
 * Task 3: ModuleCardEditor — 卡片式模块列表编辑器。
 *
 * 将多个 ModuleCard 纵向排列，支持：
 * - HTML5 拖拽排序（复用 ModuleList 的 dragIndex/dropIndex 逻辑）
 * - 底部"添加模块"按钮（已添加的模块灰色禁用）
 * - 同时只有一个卡片展开（手风琴模式）
 * - 新添加的模块自动展开并滚动到可视区域
 * - 模块内容变更实时回调 onChange
 */

import { memo, useState, useMemo, useRef, useCallback, useEffect, useLayoutEffect } from "react";
import { Plus, CaretDown, MagnifyingGlass } from "@phosphor-icons/react";
import type { ModuleType, ResumeModule, ModuleContent } from "../../api/builder";
import { MODULE_ORDER, MODULE_LABELS } from "./ModuleList";
import { ModuleCard } from "./ModuleCard";
import type { AIAction } from "./ModuleCard";

// ── Props ──────────────────────────────────────────────────────

interface ModuleCardEditorProps {
  /** 简历 ID（透传给 ModuleCard 供内联 AI 和头像上传使用） */
  resumeId: number;
  /** 当前简历的全部模块 */
  modules: ResumeModule[];
  /** 当前展开的模块类型（null = 全部折叠） */
  expandedType: ModuleType | null;
  /** 展开/折叠模块回调 */
  onToggleExpand: (type: ModuleType) => void;
  /** 模块内容变更回调 */
  onChange: (type: ModuleType, content: ModuleContent) => void;
  /** 拖拽排序完成回调（新顺序的模块类型数组） */
  onReorder: (ordered: ModuleType[]) => void;
  /** 添加模块回调 */
  onAdd: (type: ModuleType) => void;
  /** 删除模块回调 */
  onRemove: (type: ModuleType) => void;
  /** AI 生成回调（action 指定具体操作类型，customPrompt 用于自定义提示词） */
  onAIGenerate: (type: ModuleType, action?: AIAction, customPrompt?: string) => void;
}

// ── 主组件 ──────────────────────────────────────────────────────

function ModuleCardEditorImpl({
  resumeId,
  modules,
  expandedType,
  onToggleExpand,
  onChange,
  onReorder,
  onAdd,
  onRemove,
  onAIGenerate,
}: ModuleCardEditorProps) {
  const [showAddMenu, setShowAddMenu] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [dragIndex, setDragIndex] = useState<number | null>(null);
  const [dropIndex, setDropIndex] = useState<number | null>(null);

  // 新添加模块的滚动目标
  const newModuleRef = useRef<HTMLDivElement | null>(null);
  // 列表容器（用于 FLIP 动画位置记录和触摸事件）
  const containerRef = useRef<HTMLDivElement>(null);
  // 触摸拖拽状态
  const touchDragRef = useRef<number | null>(null);

  // 已添加模块按 sort_order 排序
  const sortedModules = useMemo(
    () => [...modules].sort((a, b) => a.sort_order - b.sort_order),
    [modules],
  );

  const existingTypes = useMemo(
    () => new Set(modules.map((m) => m.module_type)),
    [modules],
  );
  const availableTypes = useMemo(() => {
    const available = MODULE_ORDER.filter((t) => !existingTypes.has(t));
    if (!searchQuery.trim()) return available;
    const q = searchQuery.trim().toLowerCase();
    return available.filter((t) => MODULE_LABELS[t].toLowerCase().includes(q));
  }, [existingTypes, searchQuery]);

  // ── 拖拽逻辑 ────────────────────────────────────────────────

  /** 记录所有卡片的当前位置（FLIP 动画 First 阶段） */
  const recordFlipPositions = useCallback(() => {
    if (!containerRef.current) return;
    const cards = containerRef.current.querySelectorAll<HTMLElement>("[data-flip-id]");
    cards.forEach((card) => {
      const rect = card.getBoundingClientRect();
      card.setAttribute("data-old-top", String(rect.top));
    });
  }, []);

  /** 模块顺序签名 — 只有顺序变化时才触发 FLIP，内容变化不触发 */
  const orderKey = useMemo(
    () => sortedModules.map((m) => m.module_type).join(","),
    [sortedModules],
  );
  const prevOrderRef = useRef(orderKey);

  /** FLIP 动画 Last + Invert + Play — 仅在模块顺序变化时执行 */
  useLayoutEffect(() => {
    if (prevOrderRef.current === orderKey) return;
    prevOrderRef.current = orderKey;

    if (!containerRef.current) return;
    const cards = containerRef.current.querySelectorAll<HTMLElement>("[data-flip-id]");
    let hasFLIP = false;

    cards.forEach((card) => {
      const oldTopStr = card.getAttribute("data-old-top");
      if (!oldTopStr) return;

      const oldTop = parseFloat(oldTopStr);
      const newTop = card.getBoundingClientRect().top;
      const deltaY = oldTop - newTop;

      card.removeAttribute("data-old-top");

      if (Math.abs(deltaY) > 1) {
        hasFLIP = true;
        card.style.transform = `translateY(${deltaY}px)`;
        card.style.transition = "none";
      }
    });

    if (hasFLIP) {
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          cards.forEach((card) => {
            card.style.transition = "transform 300ms cubic-bezier(0.2, 0, 0, 1)";
            card.style.transform = "";
          });
        });
      });
    }
  }, [orderKey]);

  const handleDragStart = useCallback((index: number) => {
    setDragIndex(index);
    setDropIndex(index);
  }, []);

  const handleDragOver = useCallback((e: React.DragEvent, index: number) => {
    e.preventDefault();
    e.stopPropagation();
    setDropIndex((prev) => (prev !== index ? index : prev));
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent, targetIndex: number) => {
      e.preventDefault();
      e.stopPropagation();
      if (dragIndex === null || dragIndex === targetIndex) {
        setDragIndex(null);
        setDropIndex(null);
        return;
      }
      // FLIP: 记录旧位置
      recordFlipPositions();
      const ordered = sortedModules.map((m) => m.module_type);
      const [moved] = ordered.splice(dragIndex, 1);
      ordered.splice(targetIndex, 0, moved);
      onReorder(ordered);
      setDragIndex(null);
      setDropIndex(null);
    },
    [dragIndex, sortedModules, onReorder, recordFlipPositions],
  );

  const handleDragEnd = useCallback(() => {
    setDragIndex(null);
    setDropIndex(null);
  }, []);

  // ── 触摸拖拽（移动设备基本支持） ────────────────────────────

  const handleTouchDragStart = useCallback((index: number) => {
    touchDragRef.current = index;
    setDragIndex(index);
    setDropIndex(index);
  }, []);

  const handleTouchMove = useCallback(
    (e: React.TouchEvent) => {
      if (touchDragRef.current === null) return;
      e.preventDefault();
      const touch = e.touches[0];
      const element = document.elementFromPoint(touch.clientX, touch.clientY);
      const cardWrapper = element?.closest("[data-flip-id]");
      if (cardWrapper) {
        const flipId = cardWrapper.getAttribute("data-flip-id");
        if (flipId) {
          const index = sortedModules.findIndex((m) => m.module_type === flipId);
          if (index !== -1 && index !== touchDragRef.current) {
            setDropIndex(index);
          }
        }
      }
    },
    [sortedModules],
  );

  const handleTouchEnd = useCallback(() => {
    if (touchDragRef.current === null) return;

    if (dragIndex !== null && dropIndex !== null && dragIndex !== dropIndex) {
      recordFlipPositions();
      const ordered = sortedModules.map((m) => m.module_type);
      const [moved] = ordered.splice(dragIndex, 1);
      ordered.splice(dropIndex, 0, moved);
      onReorder(ordered);
    }

    touchDragRef.current = null;
    setDragIndex(null);
    setDropIndex(null);
  }, [dragIndex, dropIndex, sortedModules, onReorder, recordFlipPositions]);

  // ── 添加模块 ────────────────────────────────────────────────

  const handleAdd = useCallback(
    (type: ModuleType) => {
      onAdd(type);
      setShowAddMenu(false);
      setSearchQuery("");
    },
    [onAdd],
  );

  // 新添加模块后自动展开 + 滚动到可视区域
  // 检测：如果 modules 最后一个的 sort_order 比之前大（新添加），触发滚动
  const lastCountRef = useRef(modules.length);
  useEffect(() => {
    if (modules.length > lastCountRef.current) {
      // 新模块添加了，等 DOM 渲染后滚动
      requestAnimationFrame(() => {
        newModuleRef.current?.scrollIntoView({
          behavior: "smooth",
          block: "center",
        });
      });
    }
    lastCountRef.current = modules.length;
  }, [modules.length]);

  // 判断最新添加的模块（sort_order 最大的）
  const lastModuleType = useMemo(() => {
    if (sortedModules.length === 0) return null;
    return sortedModules[sortedModules.length - 1].module_type;
  }, [sortedModules]);

  return (
    <div className="flex flex-col h-full bg-[var(--color-bg)] border-r border-[var(--color-border)]/50">
      {/* 模块卡片列表 */}
      <div
        ref={containerRef}
        onTouchMove={handleTouchMove}
        onTouchEnd={handleTouchEnd}
        className="flex-1 overflow-y-auto px-3 py-3 space-y-2"
      >
        {sortedModules.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 text-center">
            <p className="text-sm text-[var(--color-text-muted)] mb-1">暂无模块</p>
            <p className="text-xs text-[var(--color-text-muted)]">
              点击下方「添加模块」开始构建简历
            </p>
          </div>
        ) : (
          sortedModules.map((module, index) => {
            const type = module.module_type;
            const isExpanded = expandedType === type;
            const isDragging = dragIndex === index;
            const isDropTarget = dropIndex === index && dragIndex !== null && dragIndex !== index;
            const isNew = type === lastModuleType && modules.length > lastCountRef.current;

            return (
              <div key={type} data-flip-id={type} className="relative">
                {/* 拖拽放置指示线 */}
                {isDropTarget && (
                  <div
                    className="absolute -top-1 left-2 right-2 h-0.5 bg-brand rounded-full
                      shadow-[0_0_8px_rgba(0,113,227,0.6)] z-10 pointer-events-none"
                    aria-hidden="true"
                  />
                )}
                <div ref={isNew ? newModuleRef : undefined}>
                  <ModuleCard
                    resumeId={resumeId}
                    moduleType={type}
                    content={module.content}
                    expanded={isExpanded}
                    isDragging={isDragging}
                    isDropTarget={isDropTarget}
                    index={index}
                    onToggleExpand={onToggleExpand}
                    onChange={onChange}
                    onAIGenerate={onAIGenerate}
                    onRemove={onRemove}
                    onDragStart={handleDragStart}
                    onDragOver={handleDragOver}
                    onDrop={handleDrop}
                    onDragEnd={handleDragEnd}
                    onTouchDragStart={handleTouchDragStart}
                  />
                </div>
              </div>
            );
          })
        )}
      </div>

      {/* 添加模块 */}
      <div className="shrink-0 p-2 border-t border-[var(--color-border)]">
        {showAddMenu ? (
          <div className="border border-[var(--color-border)] rounded-lg p-1
            bg-[var(--color-bg)]">
            <div className="flex items-center justify-between px-2 py-1 mb-1">
              <span className="text-[10px] font-medium text-[var(--color-text-muted)] uppercase tracking-wider">
                添加模块
              </span>
              <button
                onClick={() => {
                  setShowAddMenu(false);
                  setSearchQuery("");
                }}
                className="text-[10px] text-[var(--color-text-muted)]
                  hover:text-[var(--color-text)] cursor-pointer"
              >
                取消
              </button>
            </div>
            {/* 搜索框 */}
            <div className="relative mb-1.5">
              <MagnifyingGlass
                size={11}
                weight="bold"
                className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[var(--color-text-muted)] pointer-events-none"
                aria-hidden="true"
              />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="搜索模块..."
                className="w-full pl-7 pr-2 py-1.5 rounded-md text-xs
                  text-[var(--color-text)]
                  bg-[#F2F2F7] border border-transparent
                  placeholder:text-[var(--color-text-muted)]
                  focus:outline-none focus:bg-white focus:ring-2 focus:ring-brand/40
                  focus:border-brand/40 transition-all duration-150"
                aria-label="搜索模块"
              />
            </div>
            <div className="max-h-40 overflow-y-auto">
              {availableTypes.length === 0 ? (
                <p className="px-2 py-1.5 text-[10px] text-[var(--color-text-muted)]">
                  {searchQuery.trim() ? "未找到匹配的模块" : "全部模块已添加"}
                </p>
              ) : (
                <div className="grid grid-cols-2 gap-1">
                  {availableTypes.map((type) => (
                    <button
                      key={type}
                      onClick={() => handleAdd(type)}
                      className="flex items-center gap-1.5 px-2 py-1.5 rounded-md text-xs
                        text-[var(--color-text-secondary)] hover:text-brand hover:bg-brand/10
                        transition-colors cursor-pointer text-left"
                      aria-label={`添加${MODULE_LABELS[type]}`}
                    >
                      <Plus size={11} weight="bold" aria-hidden="true" />
                      {MODULE_LABELS[type]}
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
        ) : (
          <button
            onClick={() => setShowAddMenu(true)}
            disabled={availableTypes.length === 0}
            className="btn-tool w-full justify-center border-dashed text-[var(--color-text-secondary)]"
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

export const ModuleCardEditor = memo(ModuleCardEditorImpl);
