import { useEffect, useRef, useMemo } from "react";
import { X, Sparkle, ArrowRight, Plus, Minus, PencilSimple } from "@phosphor-icons/react";
import type { ResumeModule, ModuleType } from "../api/builder";
import { MODULE_LABELS } from "./builder/ModuleList";

// ── 工具名 → 中文标签 ──
const TOOL_LABELS: Record<string, string> = {
  rewrite_star: "STAR 法则改写",
  translate: "简历翻译",
  modify_module: "模块修改",
  generate_module: "模块生成",
  rewrite_resume: "整份重写",
};

interface ResumeEditDiffDialogProps {
  open: boolean;
  onClose: () => void;
  beforeModules: ResumeModule[] | null;
  afterModules: ResumeModule[] | null;
  toolName: string;
  loading?: boolean;
}

// ── diff 工具函数 ──

interface DiffEntry {
  moduleType: ModuleType;
  label: string;
  status: "added" | "removed" | "modified";
  beforeContent: string | null;
  afterContent: string | null;
}

/** 将模块列表转为 module_type → content JSON 字符串 的映射 */
function modulesToMap(modules: ResumeModule[] | null): Map<string, string> {
  const map = new Map<string, string>();
  if (!modules) return map;
  for (const mod of modules) {
    map.set(
      mod.module_type,
      JSON.stringify(mod.content, null, 2),
    );
  }
  return map;
}

/** 计算前后差异，返回有变化的模块列表 */
function computeDiff(
  before: ResumeModule[] | null,
  after: ResumeModule[] | null,
): DiffEntry[] {
  const beforeMap = modulesToMap(before);
  const afterMap = modulesToMap(after);
  const allTypes = new Set([...beforeMap.keys(), ...afterMap.keys()]);
  const diffs: DiffEntry[] = [];

  for (const type of allTypes) {
    const beforeContent = beforeMap.get(type) ?? null;
    const afterContent = afterMap.get(type) ?? null;

    if (beforeContent === null && afterContent !== null) {
      diffs.push({
        moduleType: type as ModuleType,
        label: MODULE_LABELS[type as ModuleType] ?? type,
        status: "added",
        beforeContent: null,
        afterContent,
      });
    } else if (beforeContent !== null && afterContent === null) {
      diffs.push({
        moduleType: type as ModuleType,
        label: MODULE_LABELS[type as ModuleType] ?? type,
        status: "removed",
        beforeContent,
        afterContent: null,
      });
    } else if (beforeContent !== afterContent) {
      diffs.push({
        moduleType: type as ModuleType,
        label: MODULE_LABELS[type as ModuleType] ?? type,
        status: "modified",
        beforeContent,
        afterContent,
      });
    }
  }

  // 按模块类型名排序
  return diffs.sort((a, b) => a.moduleType.localeCompare(b.moduleType));
}

// ── 单个 diff 卡片 ──

function DiffCard({ entry }: { entry: DiffEntry }) {
  const statusConfig = {
    added: {
      icon: Plus,
      color: "text-emerald-600",
      bg: "bg-emerald-500/10",
      border: "border-emerald-500/20",
      label: "新增",
    },
    removed: {
      icon: Minus,
      color: "text-red-600",
      bg: "bg-red-500/10",
      border: "border-red-500/20",
      label: "删除",
    },
    modified: {
      icon: PencilSimple,
      color: "text-amber-600",
      bg: "bg-amber-500/10",
      border: "border-amber-500/20",
      label: "修改",
    },
  };

  const config = statusConfig[entry.status];
  const StatusIcon = config.icon;

  return (
    <div className={`rounded-xl border ${config.border} overflow-hidden`}>
      {/* 模块标题栏 */}
      <div className={`flex items-center gap-2 px-4 py-2.5 ${config.bg}`}>
        <StatusIcon size={14} weight="bold" className={config.color} aria-hidden="true" />
        <span className="text-sm font-medium text-[var(--color-text)]">{entry.label}</span>
        <span className={`text-[10px] px-1.5 py-0.5 rounded-full ${config.bg} ${config.color} font-medium`}>
          {config.label}
        </span>
      </div>

      {/* 内容对比区 */}
      {entry.status === "modified" ? (
        <div className="grid grid-cols-2 divide-x divide-[var(--color-border)]">
          {/* 修改前 */}
          <div className="p-3">
            <div className="flex items-center gap-1 mb-2 text-[10px] font-medium text-[var(--color-text-muted)] uppercase tracking-wider">
              <span className="w-2 h-2 rounded-full bg-red-500/60" />
              修改前
            </div>
            <pre className="text-xs text-[var(--color-text-secondary)] whitespace-pre-wrap break-words leading-relaxed max-h-64 overflow-y-auto font-mono">
              {entry.beforeContent}
            </pre>
          </div>
          {/* 修改后 */}
          <div className="p-3 bg-emerald-500/10">
            <div className="flex items-center gap-1 mb-2 text-[10px] font-medium text-emerald-600/80 uppercase tracking-wider">
              <span className="w-2 h-2 rounded-full bg-emerald-500/60" />
              修改后
            </div>
            <pre className="text-xs text-[var(--color-text-secondary)] whitespace-pre-wrap break-words leading-relaxed max-h-64 overflow-y-auto font-mono">
              {entry.afterContent}
            </pre>
          </div>
        </div>
      ) : entry.status === "added" ? (
        <div className="p-3 bg-emerald-500/10">
          <div className="flex items-center gap-1 mb-2 text-[10px] font-medium text-emerald-600/80 uppercase tracking-wider">
            <span className="w-2 h-2 rounded-full bg-emerald-500/60" />
            新增内容
          </div>
          <pre className="text-xs text-[var(--color-text-secondary)] whitespace-pre-wrap break-words leading-relaxed max-h-64 overflow-y-auto font-mono">
            {entry.afterContent}
          </pre>
        </div>
      ) : (
        <div className="p-3 bg-red-500/10">
          <div className="flex items-center gap-1 mb-2 text-[10px] font-medium text-red-600/80 uppercase tracking-wider">
            <span className="w-2 h-2 rounded-full bg-red-500/60" />
            已删除
          </div>
          <pre className="text-xs text-[var(--color-text-secondary)] whitespace-pre-wrap break-words leading-relaxed max-h-64 overflow-y-auto font-mono line-through opacity-60">
            {entry.beforeContent}
          </pre>
        </div>
      )}
    </div>
  );
}

/**
 * ResumeEditDiffDialog — AI 修改简历时实时弹窗显示前后对比。
 *
 * 触发场景：Agent 聊天中调用了 rewrite_star / translate 等改写类工具后，
 * tool_result 事件到达时弹出此对话框，展示模块级别的前后 diff。
 *
 * 数据来源：
 * - beforeModules: Agent 开始前快照的模块列表
 * - afterModules:  tool_result 后重新拉取的模块列表
 * - toolName:      触发修改的工具名（用于标题展示）
 */
export default function ResumeEditDiffDialog({
  open,
  onClose,
  beforeModules,
  afterModules,
  toolName,
  loading = false,
}: ResumeEditDiffDialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;

    if (open) {
      try {
        dialog.showModal();
      } catch {
        dialog.open = true;
      }
    } else {
      try {
        dialog.close();
      } catch {
        dialog.open = false;
      }
    }
  }, [open]);

  const diffs = useMemo(
    () => computeDiff(beforeModules, afterModules),
    [beforeModules, afterModules],
  );

  const toolLabel = TOOL_LABELS[toolName] ?? toolName;

  const stats = useMemo(() => {
    const added = diffs.filter((d) => d.status === "added").length;
    const removed = diffs.filter((d) => d.status === "removed").length;
    const modified = diffs.filter((d) => d.status === "modified").length;
    return { added, removed, modified, total: diffs.length };
  }, [diffs]);

  if (!open) return null;

  return (
    <dialog
      ref={dialogRef}
      onCancel={onClose}
      onClose={onClose}
      className="fixed inset-0 z-[60] m-0 w-full h-full p-0
        bg-black/30 backdrop-blur-sm motion-reduce:backdrop-blur-none"
      role="dialog"
      aria-modal="true"
      aria-label="简历修改对比"
    >
      <div
        className="glass-card absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2
          max-w-4xl w-full mx-4 shadow-2xl shadow-black/10
          animate-fade-in-up motion-reduce:animate-none
          flex flex-col max-h-[85vh]"
      >
        {/* 头部 */}
        <div className="flex items-center gap-3 px-6 py-4 border-b border-[var(--color-border)] shrink-0">
          <div className="shrink-0 p-2 rounded-lg bg-brand/10 text-brand">
            <Sparkle size={18} weight="fill" aria-hidden="true" />
          </div>
          <div className="flex-1 min-w-0">
            <h3 className="text-base font-semibold text-[var(--color-text)]">
              AI 已修改简历
            </h3>
            <p className="text-xs text-[var(--color-text-muted)] mt-0.5">
              触发工具：<span className="text-brand font-medium">{toolLabel}</span>
              {!loading && stats.total > 0 && (
                <span className="ml-2">
                  · 共 {stats.total} 处变更
                  {stats.modified > 0 && <span className="text-amber-600">（{stats.modified} 修改</span>}
                  {stats.added > 0 && <span className="text-emerald-600"> {stats.added} 新增</span>}
                  {stats.removed > 0 && <span className="text-red-600"> {stats.removed} 删除</span>}
                  {stats.modified > 0 && <span>）</span>}
                </span>
              )}
            </p>
          </div>
          <button
            onClick={onClose}
            aria-label="关闭"
            className="p-1.5 rounded-lg text-[var(--color-text-secondary)]
              hover:text-[var(--color-text)] hover:bg-black/5
              active:scale-[0.95] motion-reduce:active:scale-100
              transition-all cursor-pointer shrink-0"
          >
            <X size={16} weight="bold" aria-hidden="true" />
          </button>
        </div>

        {/* 内容区 */}
        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-3">
          {loading ? (
            <div className="flex flex-col items-center justify-center py-16">
              <span className="inline-block w-6 h-6 rounded-full border-2 border-brand border-t-transparent animate-spin mb-3" />
              <p className="text-sm text-[var(--color-text-muted)]">正在获取修改结果...</p>
            </div>
          ) : diffs.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 text-center">
              <div className="w-12 h-12 rounded-xl bg-[var(--color-bg-tertiary)] flex items-center justify-center text-[var(--color-text-muted)] mb-3">
                <ArrowRight size={20} weight="duotone" aria-hidden="true" />
              </div>
              <p className="text-sm text-[var(--color-text-muted)]">未检测到模块内容变化</p>
              <p className="text-xs text-[var(--color-text-muted)] mt-1">可能修改了非模块数据或内容未发生实质变化</p>
            </div>
          ) : (
            diffs.map((entry) => (
              <DiffCard key={entry.moduleType} entry={entry} />
            ))
          )}
        </div>

        {/* 底部 */}
        <div className="flex items-center justify-between gap-2 px-6 py-3 border-t border-[var(--color-border)] shrink-0">
          <p className="text-xs text-[var(--color-text-muted)]">
            修改已保存，可在简历编辑页查看完整效果
          </p>
          <button
            onClick={onClose}
            className="px-4 py-1.5 text-sm font-medium rounded-full
              bg-[#E5E5EA] text-[var(--color-text)] hover:bg-[#D9D9DE]
              active:scale-[0.98] motion-reduce:active:scale-100
              transition-all duration-300 cursor-pointer"
          >
            知道了
          </button>
        </div>
      </div>
    </dialog>
  );
}
