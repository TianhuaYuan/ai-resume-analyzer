/**
 * InlineDiffOverlay — 在预览区内联显示 AI 生成的变更 diff。
 *
 * 与 ResumeEditDiffDialog（弹窗）不同，此组件直接嵌入 Preview Panel，
 * 用户可以在上下文中查看变更并即时接受/拒绝/修改。
 *
 * 渲染规则（§5.5 设计文档）：
 * - 新增字段：绿色高亮背景 + 左边框
 * - 删除字段：红色删除线 + 灰色背景
 * - 修改字段：黄色高亮，before → after 并排
 * - 数组字段：逐项对比，标记新增/删除/未变
 *
 * 交互：
 * - [接受] 接受变更，触发 onAccept
 * - [拒绝] 拒绝变更，触发 onReject
 * - [修改] 输入修改指令，触发 onModify
 * - 点击 overlay 外部触发 onReject
 */

import { useState, useRef, useEffect, useCallback, useMemo, memo } from "react";
import {
  Check,
  X,
  PencilSimple,
  Plus,
  Minus,
  ArrowRight,
  CaretDown,
  CaretUp,
} from "@phosphor-icons/react";
import { MODULE_LABELS } from "../builder/ModuleList";

// ── 类型定义 ──────────────────────────────────────────────

export interface PendingDiff {
  module_type: string;
  entry_id?: string;
  before: Record<string, unknown>;
  after: Record<string, unknown>;
  status: "pending" | "accepted" | "rejected";
}

export interface InlineDiffOverlayProps {
  diff: PendingDiff;
  onAccept: () => void;
  onReject: () => void;
  onModify?: (instruction: string) => void;
}

// ── 字段级 Diff 结果 ─────────────────────────────────────

/** 字段变更类型 */
type FieldChangeKind = "added" | "removed" | "modified" | "unchanged";

/** 单个字段的 diff 描述 */
interface FieldDiff {
  key: string;
  kind: FieldChangeKind;
  before?: unknown;
  after?: unknown;
  /** 数组字段的逐项 diff */
  items?: ArrayDiffItem[];
}

/** 数组字段的逐项 diff */
interface ArrayDiffItem {
  kind: "added" | "removed" | "unchanged";
  value: unknown;
  index: number;
}

// ── 字段中文标签（常见简历字段 → 友好显示名）──────────────

const FIELD_LABELS: Record<string, string> = {
  school: "学校",
  degree: "学历",
  major: "专业",
  start_date: "开始时间",
  end_date: "结束时间",
  gpa: "GPA",
  description: "描述",
  company: "公司",
  position: "职位",
  achievements: "工作成果",
  name: "名称",
  issuer: "颁发机构",
  date: "日期",
  skill: "技能",
  level: "水平",
  title: "标题",
  content: "内容",
  summary: "摘要",
  url: "链接",
  language: "语言",
  proficiency: "熟练度",
  project_name: "项目名称",
  role: "角色",
  tech_stack: "技术栈",
  technologies: "技术栈",
  result: "成果",
};

function getFieldLabel(key: string): string {
  if (FIELD_LABELS[key]) return FIELD_LABELS[key];
  // snake_case → 中文友好显示
  return key.replace(/_/g, " ");
}

// ── 核心 diff 计算 ───────────────────────────────────────

/**
 * 对比 before/after 两个对象，逐字段生成 diff 描述。
 *
 * 策略：
 * - 值类型比较用 ===（含 undefined vs 有值）
 * - JSON.stringify 比较兜底（对象/数组深比较）
 * - 数组字段逐项对比（Set diff，保留顺序）
 */
export function computeDiff(
  before: Record<string, unknown>,
  after: Record<string, unknown>,
): FieldDiff[] {
  const allKeys = new Set([...Object.keys(before), ...Object.keys(after)]);
  const diffs: FieldDiff[] = [];

  for (const key of allKeys) {
    const bVal = before[key];
    const aVal = after[key];

    // 字段不存在判断
    const bExists = key in before && bVal !== undefined;
    const aExists = key in after && aVal !== undefined;

    if (!bExists && aExists) {
      // 新增字段
      diffs.push({ key, kind: "added", after: aVal });
    } else if (bExists && !aExists) {
      // 删除字段
      diffs.push({ key, kind: "removed", before: bVal });
    } else if (valuesEqual(bVal, aVal)) {
      // 未变化
      diffs.push({ key, kind: "unchanged", before: bVal, after: aVal });
    } else {
      // 修改字段
      const diff: FieldDiff = { key, kind: "modified", before: bVal, after: aVal };

      // 数组字段逐项对比
      if (Array.isArray(bVal) && Array.isArray(aVal)) {
        diff.items = computeArrayDiff(bVal, aVal);
      }

      diffs.push(diff);
    }
  }

  return diffs;
}

/** 两个值是否相等（深度比较用 JSON.stringify 兜底） */
function valuesEqual(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (a == null && b == null) return true;
  if (a == null || b == null) return false;
  try {
    return JSON.stringify(a) === JSON.stringify(b);
  } catch {
    return String(a) === String(b);
  }
}

/**
 * 数组逐项 diff（简易 Set 语义）。
 * - 相同 JSON 的项标记为 unchanged
 * - before 中有但 after 中没有的标记为 removed
 * - after 中有但 before 中没有的标记为 added
 */
function computeArrayDiff(
  beforeArr: unknown[],
  afterArr: unknown[],
): ArrayDiffItem[] {
  const beforeStrs = beforeArr.map((v) => JSON.stringify(v));
  const afterStrs = afterArr.map((v) => JSON.stringify(v));

  const beforeUsed = new Set<number>();
  const afterUsed = new Set<number>();
  const items: ArrayDiffItem[] = [];

  // 先标记 unchanged（保持 before 顺序）
  for (let i = 0; i < beforeArr.length; i++) {
    const matchIdx = afterStrs.findIndex(
      (s, j) => !afterUsed.has(j) && s === beforeStrs[i],
    );
    if (matchIdx >= 0) {
      items.push({ kind: "unchanged", value: beforeArr[i], index: items.length });
      beforeUsed.add(i);
      afterUsed.add(matchIdx);
    }
  }

  // removed（before 中剩余）
  for (let i = 0; i < beforeArr.length; i++) {
    if (!beforeUsed.has(i)) {
      items.push({ kind: "removed", value: beforeArr[i], index: items.length });
    }
  }

  // added（after 中剩余）
  for (let i = 0; i < afterArr.length; i++) {
    if (!afterUsed.has(i)) {
      items.push({ kind: "added", value: afterArr[i], index: items.length });
    }
  }

  return items;
}

// ── 字段值渲染 ───────────────────────────────────────────

/** 将任意值渲染为可读文本 */
function renderValue(val: unknown): string {
  if (val === undefined || val === null) return "（空）";
  if (typeof val === "string") return val;
  if (typeof val === "number" || typeof val === "boolean") return String(val);
  if (Array.isArray(val)) {
    if (val.length === 0) return "（空数组）";
    return val.map((v) => (typeof v === "string" ? v : JSON.stringify(v))).join(", ");
  }
  if (typeof val === "object") {
    return JSON.stringify(val, null, 2);
  }
  return String(val);
}

// ── 字段 Diff 行 ─────────────────────────────────────────

const FieldDiffRow = memo(function FieldDiffRow({ diff }: { diff: FieldDiff }) {
  const [expanded, setExpanded] = useState(true);

  if (diff.kind === "unchanged") return null;

  const label = getFieldLabel(diff.key);

  return (
    <div
      className={`rounded-lg border transition-all duration-300 ${
        diff.kind === "added"
          ? "border-emerald-500/30 bg-emerald-500/5"
          : diff.kind === "removed"
          ? "border-red-500/30 bg-red-500/5"
          : "border-amber-500/30 bg-amber-500/5"
      }`}
    >
      {/* 字段标题行 */}
      <div className="flex items-center gap-2 px-3 py-2">
        {diff.kind === "added" && (
          <span className="flex items-center justify-center w-4 h-4 rounded-full bg-emerald-500/20">
            <Plus size={10} weight="bold" className="text-emerald-600" />
          </span>
        )}
        {diff.kind === "removed" && (
          <span className="flex items-center justify-center w-4 h-4 rounded-full bg-red-500/20">
            <Minus size={10} weight="bold" className="text-red-600" />
          </span>
        )}
        {diff.kind === "modified" && (
          <span className="flex items-center justify-center w-4 h-4 rounded-full bg-amber-500/20">
            <PencilSimple size={10} weight="bold" className="text-amber-600" />
          </span>
        )}

        <span className="text-[11px] font-medium text-[var(--color-text-secondary)]">
          {label}
        </span>

        {diff.kind === "modified" && Array.isArray(diff.before) && Array.isArray(diff.after) && (
          <button
            onClick={() => setExpanded(!expanded)}
            className="ml-auto p-0.5 rounded text-[var(--color-text-muted)]
              hover:text-[var(--color-text-secondary)] transition-colors cursor-pointer"
            aria-label={expanded ? "折叠" : "展开"}
          >
            {expanded ? <CaretUp size={12} /> : <CaretDown size={12} />}
          </button>
        )}
      </div>

      {/* 内容区 */}
      <div className="px-3 pb-2.5">
        {/* 新增字段：只显示 after */}
        {diff.kind === "added" && (
          <div className="pl-5 border-l-2 border-emerald-500/40 ml-0.5">
            <span className="text-xs text-[var(--color-text-secondary)] leading-relaxed whitespace-pre-wrap break-words">
              {renderValue(diff.after)}
            </span>
          </div>
        )}

        {/* 删除字段：只显示 before，带删除线 */}
        {diff.kind === "removed" && (
          <div className="pl-5 border-l-2 border-red-500/40 ml-0.5 opacity-50">
            <span className="text-xs text-[var(--color-text-secondary)] leading-relaxed whitespace-pre-wrap break-words line-through">
              {renderValue(diff.before)}
            </span>
          </div>
        )}

        {/* 修改字段：并排或逐项 */}
        {diff.kind === "modified" && (
          <>
            {/* 数组字段逐项 diff */}
            {diff.items && diff.items.length > 0 && expanded ? (
              <div className="pl-5 ml-0.5 space-y-1">
                {diff.items.map((item, idx) => (
                  <div
                    key={idx}
                    className={`text-xs leading-relaxed px-2 py-1 rounded ${
                      item.kind === "added"
                        ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border-l-2 border-emerald-500/50"
                        : item.kind === "removed"
                        ? "bg-red-500/10 text-red-600/70 line-through border-l-2 border-red-500/50"
                        : "text-[var(--color-text-secondary)]"
                    }`}
                  >
                    {item.kind === "added" && (
                      <span className="inline-block w-3 text-center text-emerald-500 mr-1">+</span>
                    )}
                    {item.kind === "removed" && (
                      <span className="inline-block w-3 text-center text-red-500 mr-1">-</span>
                    )}
                    {item.kind === "unchanged" && (
                      <span className="inline-block w-3 text-center text-[var(--color-text-muted)] mr-1"> </span>
                    )}
                    {typeof item.value === "string"
                      ? item.value
                      : JSON.stringify(item.value)}
                  </div>
                ))}
              </div>
            ) : !diff.items ? (
              /* 非数组字段：before → after 并排 */
              <div className="grid grid-cols-[1fr_auto_1fr] gap-2 items-start pl-5 ml-0.5">
                {/* Before */}
                <div className="rounded px-2 py-1 bg-red-500/5 border border-red-500/15">
                  <div className="text-[9px] font-medium text-red-500/60 uppercase tracking-wider mb-0.5">
                    修改前
                  </div>
                  <span className="text-xs text-[var(--color-text-secondary)] leading-relaxed whitespace-pre-wrap break-words line-through opacity-60">
                    {renderValue(diff.before)}
                  </span>
                </div>

                {/* Arrow */}
                <div className="flex items-center pt-4 text-[var(--color-text-muted)]">
                  <ArrowRight size={14} weight="bold" />
                </div>

                {/* After */}
                <div className="rounded px-2 py-1 bg-emerald-500/5 border border-emerald-500/15">
                  <div className="text-[9px] font-medium text-emerald-600/60 uppercase tracking-wider mb-0.5">
                    修改后
                  </div>
                  <span className="text-xs text-[var(--color-text-secondary)] leading-relaxed whitespace-pre-wrap break-words">
                    {renderValue(diff.after)}
                  </span>
                </div>
              </div>
            ) : null}
          </>
        )}
      </div>
    </div>
  );
});

// ── 修改指令输入框 ───────────────────────────────────────

function ModifyInput({
  onSubmit,
  onCancel,
}: {
  onSubmit: (instruction: string) => void;
  onCancel: () => void;
}) {
  const [value, setValue] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const handleSubmit = useCallback(() => {
    const trimmed = value.trim();
    if (trimmed) {
      onSubmit(trimmed);
    }
  }, [value, onSubmit]);

  return (
    <div className="flex items-center gap-1.5 animate-fade-in-down">
      <input
        ref={inputRef}
        type="text"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            handleSubmit();
          } else if (e.key === "Escape") {
            onCancel();
          }
        }}
        placeholder="描述你想要的修改..."
        className="flex-1 px-2.5 py-1.5 rounded-lg text-xs
          bg-[var(--color-bg-secondary)] border border-[var(--color-border)]
          focus:outline-none focus:border-brand/40 focus:ring-2 focus:ring-brand/10
          transition-all"
      />
      <button
        onClick={handleSubmit}
        disabled={!value.trim()}
        className="px-2 py-1.5 rounded-lg text-xs font-medium
          bg-brand text-white hover:bg-brand/90
          disabled:opacity-40 disabled:cursor-not-allowed
          active:scale-[0.97] transition-all cursor-pointer"
      >
        发送
      </button>
      <button
        onClick={onCancel}
        className="px-2 py-1.5 rounded-lg text-xs font-medium
          text-[var(--color-text-muted)] hover:text-[var(--color-text-secondary)]
          hover:bg-[var(--color-bg-secondary)]
          active:scale-[0.97] transition-all cursor-pointer"
      >
        取消
      </button>
    </div>
  );
}

// ── 主组件 ───────────────────────────────────────────────

/**
 * InlineDiffOverlay — 在预览区内联渲染 AI 变更 diff。
 *
 * 组件结构：
 * ┌─ 变更预览卡片 ──────────────────────────┐
 * │ 模块标题 + 状态徽标                        │
 * │                                           │
 * │ FieldDiffRow (逐字段变更)                  │
 * │   - added: 绿色                           │
 * │   - removed: 红色删除线                     │
 * │   - modified: 黄色 before → after          │
 * │                                           │
 * │ ┌─ 浮动操作栏 ──────────────────────┐     │
 * │ │ [接受] [拒绝] [修改]               │     │
 * │ └───────────────────────────────────┘     │
 * └───────────────────────────────────────────┘
 */
export default function InlineDiffOverlay({
  diff,
  onAccept,
  onReject,
  onModify,
}: InlineDiffOverlayProps) {
  const overlayRef = useRef<HTMLDivElement>(null);
  const [showModify, setShowModify] = useState(false);

  // ── 点击外部关闭（reject） ──
  useEffect(() => {
    if (diff.status !== "pending") return;

    const handleClickOutside = (e: MouseEvent) => {
      if (overlayRef.current && !overlayRef.current.contains(e.target as Node)) {
        onReject();
      }
    };

    // 延迟绑定，避免渲染时立刻触发
    const timer = setTimeout(() => {
      document.addEventListener("mousedown", handleClickOutside, true);
    }, 100);

    return () => {
      clearTimeout(timer);
      document.removeEventListener("mousedown", handleClickOutside, true);
    };
  }, [diff.status, onReject]);

  // ── Escape 键关闭 ──
  useEffect(() => {
    if (diff.status !== "pending") return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onReject();
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [diff.status, onReject]);

  // ── 计算 diff ──
  const fieldDiffs = useMemo(
    () => computeDiff(diff.before, diff.after),
    [diff.before, diff.after],
  );

  const changedFields = useMemo(
    () => fieldDiffs.filter((f) => f.kind !== "unchanged"),
    [fieldDiffs],
  );

  const changeStats = useMemo(() => {
    const added = changedFields.filter((f) => f.kind === "added").length;
    const removed = changedFields.filter((f) => f.kind === "removed").length;
    const modified = changedFields.filter((f) => f.kind === "modified").length;
    return { added, removed, modified, total: changedFields.length };
  }, [changedFields]);

  // ── 模块标签 ──
  const moduleLabel = MODULE_LABELS[diff.module_type as keyof typeof MODULE_LABELS] ?? diff.module_type;

  // ── 已决断状态（accepted/rejected）渲染简化卡片 ──
  if (diff.status === "accepted") {
    return (
      <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/5 px-3 py-2 animate-fade-in">
        <div className="flex items-center gap-1.5 text-xs text-emerald-600">
          <Check size={12} weight="bold" />
          <span className="font-medium">{moduleLabel}</span>
          <span className="text-emerald-500/60">变更已接受</span>
        </div>
      </div>
    );
  }

  if (diff.status === "rejected") {
    return (
      <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-secondary)]/50 px-3 py-2 animate-fade-in opacity-60">
        <div className="flex items-center gap-1.5 text-xs text-[var(--color-text-muted)]">
          <X size={12} weight="bold" />
          <span className="font-medium">{moduleLabel}</span>
          <span>变更已拒绝</span>
        </div>
      </div>
    );
  }

  // ── pending 状态：完整 diff 视图 ──
  return (
    <div
      ref={overlayRef}
      className="rounded-xl border border-amber-500/25 bg-[var(--color-bg)]/95 backdrop-blur-sm
        shadow-lg shadow-black/5 animate-slide-in-top
        flex flex-col max-h-[70vh] overflow-hidden"
    >
      {/* 头部 */}
      <div className="flex items-center gap-2 px-3.5 py-2.5 border-b border-[var(--color-border)] shrink-0">
        <div className="shrink-0 w-5 h-5 rounded-md bg-amber-500/10 flex items-center justify-center">
          <PencilSimple size={11} weight="bold" className="text-amber-600" />
        </div>
        <div className="flex-1 min-w-0">
          <span className="text-xs font-medium text-[var(--color-text)]">
            {moduleLabel}
          </span>
          {diff.entry_id && (
            <span className="text-[10px] text-[var(--color-text-muted)] ml-1.5">
              #{diff.entry_id.slice(-6)}
            </span>
          )}
        </div>

        {/* 变更统计 */}
        <div className="flex items-center gap-1.5 text-[10px] shrink-0">
          {changeStats.modified > 0 && (
            <span className="px-1.5 py-0.5 rounded-full bg-amber-500/10 text-amber-600 font-medium">
              {changeStats.modified} 修改
            </span>
          )}
          {changeStats.added > 0 && (
            <span className="px-1.5 py-0.5 rounded-full bg-emerald-500/10 text-emerald-600 font-medium">
              {changeStats.added} 新增
            </span>
          )}
          {changeStats.removed > 0 && (
            <span className="px-1.5 py-0.5 rounded-full bg-red-500/10 text-red-500 font-medium">
              {changeStats.removed} 删除
            </span>
          )}
        </div>
      </div>

      {/* 字段变更列表 */}
      <div className="flex-1 overflow-y-auto px-3 py-2.5 space-y-1.5">
        {changedFields.length === 0 ? (
          <div className="flex items-center justify-center py-6 text-center">
            <p className="text-xs text-[var(--color-text-muted)]">未检测到字段变化</p>
          </div>
        ) : (
          changedFields.map((fd) => <FieldDiffRow key={fd.key} diff={fd} />)
        )}
      </div>

      {/* 浮动操作栏 */}
      <div className="shrink-0 border-t border-[var(--color-border)] px-3 py-2.5">
        {showModify && onModify ? (
          <ModifyInput
            onSubmit={(instruction) => {
              setShowModify(false);
              onModify(instruction);
            }}
            onCancel={() => setShowModify(false)}
          />
        ) : (
          <div className="flex items-center gap-1.5">
            {/* 接受 */}
            <button
              onClick={onAccept}
              className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium
                bg-emerald-500/10 text-emerald-600 border border-emerald-500/20
                hover:bg-emerald-500/20 hover:border-emerald-500/30
                active:scale-[0.97] motion-reduce:active:scale-100
                transition-all cursor-pointer"
            >
              <Check size={12} weight="bold" />
              接受
            </button>

            {/* 拒绝 */}
            <button
              onClick={onReject}
              className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium
                bg-red-500/10 text-red-500 border border-red-500/20
                hover:bg-red-500/20 hover:border-red-500/30
                active:scale-[0.97] motion-reduce:active:scale-100
                transition-all cursor-pointer"
            >
              <X size={12} weight="bold" />
              拒绝
            </button>

            {/* 修改（需 onModify 回调才显示） */}
            {onModify && (
              <button
                onClick={() => setShowModify(true)}
                className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium
                  text-[var(--color-text-secondary)] border border-[var(--color-border)]
                  hover:bg-[var(--color-bg-secondary)] hover:border-[var(--color-border)]
                  active:scale-[0.97] motion-reduce:active:scale-100
                  transition-all cursor-pointer"
              >
                <PencilSimple size={12} weight="bold" />
                修改
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
