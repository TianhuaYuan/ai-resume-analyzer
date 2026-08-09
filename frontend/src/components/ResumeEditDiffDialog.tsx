import { useEffect, useRef, useMemo, useState, useCallback } from "react";
import {
  X,
  GitDiff,
  ArrowRight,
  Plus,
  Minus,
  PencilSimple,
  ArrowCounterClockwise,
  ArrowClockwise,
  CheckCircle,
  SpinnerGap,
  CaretDown,
  CaretRight,
} from "@phosphor-icons/react";
import { saveDraft } from "../api/builder";
import type { ResumeModule, ModuleType, ResumeModuleInput, ModuleContent } from "../api/builder";
import { useToast } from "./Toast";
import { MODULE_LABELS } from "./builder/ModuleList";

// ── 工具名 → 中文标签 + 默认审阅理由（E2：逐条审阅 rationale） ──
const TOOL_LABELS: Record<string, string> = {
  rewrite_star: "STAR 法则改写",
  translate: "简历翻译",
  modify_module: "模块修改",
  generate_module: "模块生成",
  rewrite_resume: "整份重写",
};

const TOOL_RATIONALE: Record<string, string> = {
  rewrite_star: "STAR 法则改写经历描述，使其更专业有力",
  translate: "翻译为目标语言，保持专业术语准确",
  rewrite_resume: "按目标岗位优化整份简历措辞",
};

// ── 字段中文标签 ──
const FIELD_LABELS: Record<string, string> = {
  name: "名称",
  title: "标题",
  summary: "个人总结",
  company: "公司",
  position: "职位",
  school: "学校",
  degree: "学历",
  major: "专业",
  description: "描述",
  achievements: "主要成就",
  start_date: "开始时间",
  end_date: "结束时间",
  gpa: "GPA",
  url: "链接",
  tech_stack: "技术栈",
  role: "角色",
  level: "熟练度",
  category: "分类",
  platform: "平台",
  proficiency: "熟练度",
  score: "成绩",
  date: "时间",
  issuer: "颁发机构",
  content: "内容",
  venue: "发表载体",
  authors: "作者",
  organization: "组织",
  contact: "联系方式",
  location: "所在城市",
  phone: "电话",
  email: "邮箱",
};

interface ResumeEditDiffDialogProps {
  open: boolean;
  onClose: () => void;
  /** 保存"按用户选择调整后的模块列表"用（PUT /resumes/{id}?mode=draft） */
  resumeId: number;
  beforeModules: ResumeModule[] | null;
  afterModules: ResumeModule[] | null;
  toolName: string;
  loading?: boolean;
  /** 保存成功后回调（调用方用它刷新预览模块），参数为落库后的最新模块列表 */
  onModulesSaved?: (modules: ResumeModule[]) => void;
}

// ── diff 工具函数 ──

interface FieldDiff {
  /** 点号路径：items.<id>.<field> / 平铺 field / metadata.title / items.<id> */
  path: string;
  label: string;
  status: "added" | "removed" | "modified";
  before: unknown;
  after: unknown;
}

interface DiffEntry {
  moduleType: ModuleType;
  label: string;
  status: "added" | "removed" | "modified";
  beforeContent: string | null;
  afterContent: string | null;
  /** G 可信度控制：after 模块的 source（fact/inferred/mixed） */
  source: string;
  /** 字段级 diff（仅 modified 模块计算；整模块新增/删除为空） */
  fieldDiffs: FieldDiff[];
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

/** module_type → source 映射（AI 改写内容来源标注） */
function modulesToSourceMap(modules: ResumeModule[] | null): Map<string, string> {
  const map = new Map<string, string>();
  if (!modules) return map;
  for (const mod of modules) map.set(mod.module_type, mod.source ?? "fact");
  return map;
}

/** 解析 diff 中 stringified 的 content 回对象（解析失败兜底空对象） */
function parseContent(json: string | null): ModuleContent {
  if (!json) return {};
  try {
    return JSON.parse(json) as ModuleContent;
  } catch {
    return {};
  }
}

/** 条目主名称（用于「第 N 条」人话标签） */
function itemName(item: Record<string, unknown> | undefined): string {
  if (!item) return "";
  const n = item.name ?? item.company ?? item.school ?? item.title ?? item.position ?? item.platform;
  return typeof n === "string" && n.trim() ? n : "";
}

/** 标量比较（JSON 序列化判等，忽略 undefined） */
function sameValue(a: unknown, b: unknown): boolean {
  if (a === undefined && b === undefined) return true;
  if (a === undefined || b === undefined) return false;
  return JSON.stringify(a) === JSON.stringify(b);
}

/**
 * 计算单模块 content 的字段级 diff（E2 增强，Magic-Resume diffResume 思路）：
 * - metadata.title 变化
 * - 平铺标量字段变化（排除 items/metadata/结构字段）
 * - items 按 id 匹配：整条新增/删除 + 条目字段变化
 */
function computeFieldDiffs(beforeContent: object, afterContent: object): FieldDiff[] {
  const diffs: FieldDiff[] = [];
  const toObj = (c: object) => c as Record<string, unknown>;

  const b = toObj(beforeContent);
  const a = toObj(afterContent);

  // metadata.title
  const bMeta = (b.metadata ?? {}) as Record<string, unknown>;
  const aMeta = (a.metadata ?? {}) as Record<string, unknown>;
  if (bMeta.title !== aMeta.title && (bMeta.title || aMeta.title)) {
    diffs.push({
      path: "metadata.title",
      label: "模块标题",
      status: "modified",
      before: bMeta.title,
      after: aMeta.title,
    });
  }

  // 平铺标量字段
  const skip = new Set(["items", "metadata", "entries", "categories"]);
  const allKeys = new Set([...Object.keys(b), ...Object.keys(a)]);
  for (const key of allKeys) {
    if (skip.has(key)) continue;
    const bv = b[key];
    const av = a[key];
    if (sameValue(bv, av)) continue;
    diffs.push({
      path: key,
      label: FIELD_LABELS[key] ?? key,
      status: bv === undefined ? "added" : av === undefined ? "removed" : "modified",
      before: bv,
      after: av,
    });
  }

  // items 按 id 匹配
  const bItems = Array.isArray(b.items) ? (b.items as Record<string, unknown>[]) : [];
  const aItems = Array.isArray(a.items) ? (a.items as Record<string, unknown>[]) : [];
  const bMap = new Map(bItems.filter((i) => i && i.id).map((i) => [String(i.id), i]));
  const aMap = new Map(aItems.filter((i) => i && i.id).map((i) => [String(i.id), i]));
  const allIds = new Set([...bMap.keys(), ...aMap.keys()]);

  for (const id of allIds) {
    const bi = bMap.get(id);
    const ai = aMap.get(id);
    if (!bi) {
      diffs.push({
        path: `items.${id}`,
        label: `新增条目${itemName(ai) ? `（${itemName(ai)}）` : ""}`,
        status: "added",
        before: undefined,
        after: ai,
      });
      continue;
    }
    if (!ai) {
      diffs.push({
        path: `items.${id}`,
        label: `删除条目${itemName(bi) ? `（${itemName(bi)}）` : ""}`,
        status: "removed",
        before: bi,
        after: undefined,
      });
      continue;
    }
    const label = itemName(ai) || itemName(bi) || "条目";
    for (const key of new Set([...Object.keys(bi), ...Object.keys(ai)])) {
      if (key === "id" || key === "hidden") continue;
      const bv = bi[key];
      const av = ai[key];
      if (sameValue(bv, av)) continue;
      diffs.push({
        path: `items.${id}.${key}`,
        label: `${label} · ${FIELD_LABELS[key] ?? key}`,
        status: bv === undefined ? "added" : av === undefined ? "removed" : "modified",
        before: bv,
        after: av,
      });
    }
  }

  return diffs;
}

/** 计算前后差异，返回有变化的模块列表（modified 附带字段级 diff） */
function computeDiff(
  before: ResumeModule[] | null,
  after: ResumeModule[] | null,
): DiffEntry[] {
  const beforeMap = modulesToMap(before);
  const afterMap = modulesToMap(after);
  const afterSourceMap = modulesToSourceMap(after);
  const allTypes = new Set([...beforeMap.keys(), ...afterMap.keys()]);
  const diffs: DiffEntry[] = [];

  for (const type of allTypes) {
    const beforeContent = beforeMap.get(type) ?? null;
    const afterContent = afterMap.get(type) ?? null;
    const source = afterSourceMap.get(type) ?? "fact";

    if (beforeContent === null && afterContent !== null) {
      diffs.push({
        moduleType: type as ModuleType,
        label: MODULE_LABELS[type as ModuleType] ?? type,
        status: "added",
        beforeContent: null,
        afterContent,
        source,
        fieldDiffs: [],
      });
    } else if (beforeContent !== null && afterContent === null) {
      diffs.push({
        moduleType: type as ModuleType,
        label: MODULE_LABELS[type as ModuleType] ?? type,
        status: "removed",
        beforeContent,
        afterContent: null,
        source,
        fieldDiffs: [],
      });
    } else if (beforeContent !== afterContent) {
      diffs.push({
        moduleType: type as ModuleType,
        label: MODULE_LABELS[type as ModuleType] ?? type,
        status: "modified",
        beforeContent,
        afterContent,
        source,
        fieldDiffs: computeFieldDiffs(parseContent(beforeContent), parseContent(afterContent)),
      });
    }
  }

  // 按模块类型名排序
  return diffs.sort((a, b) => a.moduleType.localeCompare(b.moduleType));
}

/** 生成模块级还原键（整模块还原） */
function moduleRevertKey(moduleType: ModuleType): string {
  return `${moduleType}:*`;
}

/** 生成字段级还原键 */
function fieldRevertKey(moduleType: ModuleType, path: string): string {
  return `${moduleType}:${path}`;
}

/** 按点号路径在 content 中还原字段值（before=undefined → 删除） */
function revertFieldInContent(
  content: ModuleContent,
  path: string,
  value: unknown,
): void {
  const segs = path.split(".");
  if (segs[0] === "items" && segs.length >= 2) {
    const id = segs[1];
    const items = Array.isArray(content.items) ? (content.items as Record<string, unknown>[]) : [];
    const item = items.find((i) => String(i.id) === id);
    if (!item) return;
    if (segs.length === 2) return; // 整条 add/remove 在 buildSavePayload 单独处理
    const field = segs[2];
    if (value === undefined) delete item[field];
    else item[field] = value;
    return;
  }
  if (segs[0] === "metadata" && segs.length === 2) {
    const meta = (content.metadata ?? {}) as Record<string, unknown>;
    if (value === undefined) delete meta[segs[1]];
    else meta[segs[1]] = value;
    return;
  }
  if (segs.length === 1) {
    if (value === undefined) delete content[segs[0]];
    else content[segs[0]] = value;
  }
}

/**
 * 构建提交的模块列表：以 afterModules（AI 已落库）为基础，
 * 对 revertedFields 中的字段/模块按 diff 语义还原为原文：
 * - 模块级（`{type}:*`）：
 *   - added    → 移除该模块
 *   - removed  → 加回该模块（原文）
 *   - modified → content 整体用 beforeContent
 * - 字段级（`{type}:{path}`）：在 after content 上逐字段还原 before 值
 */
function buildSavePayload(
  beforeModules: ResumeModule[] | null,
  afterModules: ResumeModule[] | null,
  diffs: DiffEntry[],
  revertedFields: Set<string>,
): ResumeModuleInput[] {
  const inputs: ResumeModuleInput[] = (afterModules ?? []).map((m) => ({
    module_type: m.module_type,
    content: m.content,
    sort_order: m.sort_order,
  }));

  for (const diff of diffs) {
    const moduleReverted = revertedFields.has(moduleRevertKey(diff.moduleType));

    if (diff.status === "added") {
      if (moduleReverted) {
        const idx = inputs.findIndex((m) => m.module_type === diff.moduleType);
        if (idx >= 0) inputs.splice(idx, 1);
      } else {
        // 字段级还原新增模块的部分字段（罕见：整模块新增 + 仅还原个别字段）
        const target = inputs.find((m) => m.module_type === diff.moduleType);
        if (target) {
          for (const fd of diff.fieldDiffs) {
            if (revertedFields.has(fieldRevertKey(diff.moduleType, fd.path))) {
              if (fd.status === "added") {
                // 新增字段无 before，字段级还原即移除
                revertFieldInContent(target.content as ModuleContent, fd.path, undefined);
              }
            }
          }
        }
      }
      continue;
    }

    if (diff.status === "removed") {
      if (moduleReverted) {
        const beforeMod = beforeModules?.find((m) => m.module_type === diff.moduleType);
        inputs.push({
          module_type: diff.moduleType,
          content: parseContent(diff.beforeContent),
          sort_order: beforeMod?.sort_order ?? inputs.length + 1,
        });
      }
      continue;
    }

    // modified：定位 after 中的模块
    const target = inputs.find((m) => m.module_type === diff.moduleType);
    if (!target) continue;

    if (moduleReverted) {
      target.content = parseContent(diff.beforeContent);
      continue;
    }

    // 字段级还原
    const content = target.content as ModuleContent;
    for (const fd of diff.fieldDiffs) {
      if (!revertedFields.has(fieldRevertKey(diff.moduleType, fd.path))) continue;

      if (fd.path.startsWith("items.") && fd.path.split(".").length === 2) {
        // 整条 add/remove
        const id = fd.path.split(".")[1];
        const items = Array.isArray(content.items) ? (content.items as Record<string, unknown>[]) : [];
        const idx = items.findIndex((i) => String(i.id) === id);
        if (fd.status === "added") {
          if (idx >= 0) items.splice(idx, 1);
        } else if (fd.status === "removed") {
          if (idx < 0) items.push(fd.before as Record<string, unknown>);
        }
        continue;
      }

      // 字段级还原 before 值
      const beforeVal = fd.before;
      if (beforeVal === undefined) {
        revertFieldInContent(content, fd.path, undefined);
      } else {
        revertFieldInContent(content, fd.path, beforeVal);
      }
    }
  }

  return inputs;
}

// ── 值展示（截断 + 展开） ──

function DiffValue({
  value,
  muted,
}: {
  value: unknown;
  muted?: boolean;
}) {
  const [open, setOpen] = useState(false);
  if (value === undefined || value === null || value === "") {
    return <span className="text-xs text-[var(--color-text-muted)] italic">（无）</span>;
  }
  const text = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  const short = text.length > 120;
  return (
    <div className="w-full">
      <pre
        className={`text-xs whitespace-pre-wrap break-words leading-relaxed font-mono ${
          muted ? "text-[var(--color-text-secondary)]" : "text-[var(--color-text-secondary)]"
        } ${open ? "" : "max-h-24 overflow-hidden"}`}
      >
        {text}
      </pre>
      {short && (
        <button
          onClick={() => setOpen(!open)}
          className="mt-1 inline-flex items-center gap-1 text-[10px] text-brand hover:underline cursor-pointer"
        >
          {open ? <CaretUpIcon /> : <CaretDown size={10} weight="bold" aria-hidden="true" />}
          {open ? "收起" : `展开（${text.length} 字符）`}
        </button>
      )}
    </div>
  );
}

function CaretUpIcon() {
  return <CaretDown size={10} weight="bold" className="rotate-180" aria-hidden="true" />;
}

// ── 单条字段 diff 行 ──

function FieldDiffRow({
  fd,
  rationale,
  reverted,
  onToggleRevert,
}: {
  fd: FieldDiff;
  rationale: string;
  reverted: boolean;
  onToggleRevert: () => void;
}) {
  const statusConfig = {
    added: { color: "text-success", label: "新增" },
    removed: { color: "text-danger", label: "删除" },
    modified: { color: "text-warning", label: "修改" },
  };
  const cfg = statusConfig[fd.status];

  return (
    <div className="border-b border-[var(--color-border)] last:border-b-0">
      <div className="flex items-center justify-between gap-2 px-4 py-2">
        <div className="min-w-0 flex items-center gap-2">
          <span className="text-xs font-medium text-[var(--color-text)] truncate">{fd.label}</span>
          <span className={`text-[10px] px-1.5 py-0.5 rounded-full bg-[var(--color-bg-tertiary)] ${cfg.color} font-medium shrink-0`}>
            {cfg.label}
          </span>
          <span
            className="hidden md:inline text-[10px] text-[var(--color-text-muted)] truncate"
            title={rationale}
          >
            {rationale}
          </span>
        </div>
        <button
          onClick={onToggleRevert}
          className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-action text-[10px] font-medium shrink-0 cursor-pointer transition-all active:scale-[0.97] ${
            reverted
              ? "text-success bg-success/10"
              : "text-[var(--color-text-secondary)] hover:text-brand hover:bg-brand/5"
          }`}
        >
          {reverted ? (
            <>
              <CheckCircle size={11} weight="fill" aria-hidden="true" />
              已还原
            </>
          ) : (
            <>
              <ArrowCounterClockwise size={11} weight="bold" aria-hidden="true" />
              还原
            </>
          )}
        </button>
      </div>
      <div className="grid grid-cols-2 gap-2 px-4 pb-2">
        <div className="min-w-0">
          <div className="text-[10px] font-medium text-danger/70 mb-1">修改前</div>
          <DiffValue value={fd.before} muted />
        </div>
        <div className="min-w-0">
          <div className="text-[10px] font-medium text-success/70 mb-1">修改后</div>
          <DiffValue value={fd.after} />
        </div>
      </div>
    </div>
  );
}

// ── 单个模块 diff 卡片 ──

function DiffCard({
  entry,
  rationale,
  revertedFields,
  onToggleField,
  onToggleModuleRevert,
}: {
  entry: DiffEntry;
  rationale: string;
  revertedFields: Set<string>;
  onToggleField: (path: string) => void;
  onToggleModuleRevert: () => void;
}) {
  const [showFull, setShowFull] = useState(false);
  const statusConfig = {
    added: {
      icon: Plus,
      color: "text-success",
      bg: "bg-success/10",
      border: "border-success/20",
      label: "新增模块",
    },
    removed: {
      icon: Minus,
      color: "text-danger",
      bg: "bg-danger/10",
      border: "border-danger/20",
      label: "删除模块",
    },
    modified: {
      icon: PencilSimple,
      color: "text-warning",
      bg: "bg-warning/10",
      border: "border-warning/20",
      label: "修改",
    },
  };

  const config = statusConfig[entry.status];
  const StatusIcon = config.icon;
  const moduleReverted = revertedFields.has(moduleRevertKey(entry.moduleType));
  const fieldCount = entry.fieldDiffs.length;
  const revertedFieldCount = entry.fieldDiffs.filter((fd) =>
    revertedFields.has(fieldRevertKey(entry.moduleType, fd.path)),
  ).length;

  const revertActionLabel =
    entry.status === "added" ? "移除该模块"
    : entry.status === "removed" ? "恢复该模块"
    : "整模块还原为原文";
  const revertedLabel =
    entry.status === "added" ? "已移除"
    : entry.status === "removed" ? "已恢复"
    : "已整模块还原";

  return (
    <div className={`rounded-list border ${config.border} overflow-hidden`}>
      {/* 模块标题栏 */}
      <div className={`flex items-center gap-2 px-4 py-2.5 ${config.bg}`}>
        <StatusIcon size={14} weight="bold" className={config.color} aria-hidden="true" />
        <span className="text-sm font-medium text-[var(--color-text)]">{entry.label}</span>
        <span className={`text-[10px] px-1.5 py-0.5 rounded-full ${config.bg} ${config.color} font-medium`}>
          {config.label}
        </span>
        {entry.status === "modified" && fieldCount > 0 && (
          <span className="text-[10px] text-[var(--color-text-muted)]">
            {fieldCount} 处字段变更
            {revertedFieldCount > 0 && ` · ${revertedFieldCount} 已还原`}
          </span>
        )}
        {/* 可信度联动：AI 推断/补充内容（source≠fact）才显示徽标 */}
        {entry.source !== "fact" && !moduleReverted && (
          <span
            className="text-[10px] px-1.5 py-0.5 rounded-full bg-warning/10 border border-warning/30 text-warning font-medium"
            title="该模块含 AI 推断/补充内容，请核对是否属实后再使用"
          >
            AI 推断内容
          </span>
        )}
      </div>

      {/* 内容对比区 */}
      {entry.status === "modified" ? (
        <>
          {fieldCount > 0 ? (
            <div>
              {entry.fieldDiffs.map((fd) => (
                <FieldDiffRow
                  key={fd.path}
                  fd={fd}
                  rationale={rationale}
                  reverted={revertedFields.has(fieldRevertKey(entry.moduleType, fd.path))}
                  onToggleRevert={() => onToggleField(fd.path)}
                />
              ))}
            </div>
          ) : (
            <div className="grid grid-cols-2 divide-x divide-[var(--color-border)]">
              <div className="p-3">
                <div className="text-[10px] font-medium text-danger/70 mb-1">修改前</div>
                <pre className="text-xs text-[var(--color-text-secondary)] whitespace-pre-wrap break-words leading-relaxed max-h-64 overflow-y-auto font-mono">
                  {entry.beforeContent}
                </pre>
              </div>
              <div className="p-3 bg-success/10">
                <div className="text-[10px] font-medium text-success/70 mb-1">修改后</div>
                <pre className="text-xs text-[var(--color-text-secondary)] whitespace-pre-wrap break-words leading-relaxed max-h-64 overflow-y-auto font-mono">
                  {entry.afterContent}
                </pre>
              </div>
            </div>
          )}
          {fieldCount > 0 && (
            <button
              onClick={() => setShowFull(!showFull)}
              className="w-full flex items-center justify-center gap-1 px-4 py-1.5 text-[10px] text-[var(--color-text-muted)] hover:text-brand border-t border-[var(--color-border)] cursor-pointer"
            >
              {showFull ? <CaretDown size={11} weight="bold" /> : <CaretRight size={11} weight="bold" />}
              {showFull ? "收起完整对比" : "查看完整模块对比"}
            </button>
          )}
          {showFull && (
            <div className="grid grid-cols-2 divide-x divide-[var(--color-border)] border-t border-[var(--color-border)]">
              <div className="p-3">
                <pre className="text-xs text-[var(--color-text-secondary)] whitespace-pre-wrap break-words leading-relaxed max-h-64 overflow-y-auto font-mono">
                  {entry.beforeContent}
                </pre>
              </div>
              <div className="p-3 bg-success/10">
                <pre className="text-xs text-[var(--color-text-secondary)] whitespace-pre-wrap break-words leading-relaxed max-h-64 overflow-y-auto font-mono">
                  {entry.afterContent}
                </pre>
              </div>
            </div>
          )}
        </>
      ) : entry.status === "added" ? (
        <div className="p-3 bg-success/10">
          <pre className="text-xs text-[var(--color-text-secondary)] whitespace-pre-wrap break-words leading-relaxed max-h-64 overflow-y-auto font-mono">
            {entry.afterContent}
          </pre>
        </div>
      ) : (
        <div className="p-3 bg-danger/10">
          <pre className="text-xs text-[var(--color-text-secondary)] whitespace-pre-wrap break-words leading-relaxed max-h-64 overflow-y-auto font-mono line-through opacity-60">
            {entry.beforeContent}
          </pre>
        </div>
      )}

      {/* 操作区 */}
      <div className="flex items-center justify-between gap-2 px-4 py-2 border-t border-[var(--color-border)] bg-[var(--color-bg-secondary)]">
        {moduleReverted ? (
          <span className="inline-flex items-center gap-1.5 text-xs font-medium text-success">
            <CheckCircle size={13} weight="fill" aria-hidden="true" />
            {revertedLabel}
          </span>
        ) : (
          <span className="text-xs text-[var(--color-text-muted)]">
            {entry.status === "modified"
              ? revertedFieldCount > 0
                ? `${revertedFieldCount} 处已还原，其余保留 AI 修改`
                : "保留 AI 修改"
              : "保留 AI 修改"}
          </span>
        )}
        <button
          onClick={onToggleModuleRevert}
          className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-action text-xs font-medium
            text-[var(--color-text-secondary)] hover:text-brand hover:bg-brand/5
            active:scale-[0.97] motion-reduce:active:scale-100 transition-all cursor-pointer"
        >
          {moduleReverted ? (
            <>
              <ArrowClockwise size={13} weight="bold" aria-hidden="true" />
              撤销整模块还原
            </>
          ) : (
            <>
              <ArrowCounterClockwise size={13} weight="bold" aria-hidden="true" />
              {revertActionLabel}
            </>
          )}
        </button>
      </div>
    </div>
  );
}

// ── 底部保存区 ──
// 独立子组件：仅弹窗打开（open=true）时才挂载，避免测试环境无 ToastProvider 时渲染报错。
function SaveFooter({
  resumeId,
  beforeModules,
  afterModules,
  diffs,
  revertedFields,
  onClose,
  onSaved,
}: {
  resumeId: number;
  beforeModules: ResumeModule[] | null;
  afterModules: ResumeModule[] | null;
  diffs: DiffEntry[];
  revertedFields: Set<string>;
  onClose: () => void;
  onSaved: (modules: ResumeModule[]) => void;
}) {
  const toast = useToast();
  const [saving, setSaving] = useState(false);
  const revertedCount = revertedFields.size;

  const handleSave = async () => {
    if (saving || !resumeId) return;
    setSaving(true);
    try {
      const payload = buildSavePayload(beforeModules, afterModules, diffs, revertedFields);
      const result = await saveDraft(resumeId, { modules: payload });
      toast.success(revertedCount === 1 ? "已保存 1 处还原" : `已保存 ${revertedCount} 处还原`);
      onSaved(result.modules ?? []);
      onClose();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "保存失败，请重试", { title: "保存失败" });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="flex items-center justify-between gap-2 px-6 py-3 border-t border-[var(--color-border)] shrink-0">
      <p className="text-xs text-[var(--color-text-muted)]">
        {revertedCount > 0
          ? `已选择 ${revertedCount} 处还原，保存后生效`
          : "AI 修改已应用；不认可的改动可在卡片上逐条还原"}
      </p>
      <div className="flex items-center gap-2 shrink-0">
        <button
          onClick={onClose}
          className="px-4 py-1.5 text-sm font-medium rounded-full
            bg-[#E5E5EA] text-[var(--color-text)] hover:bg-[var(--color-bg-secondary)]
            active:scale-[0.98] motion-reduce:active:scale-100
            transition-all duration-300 cursor-pointer"
        >
          {revertedCount > 0 ? "取消" : "知道了"}
        </button>
        {revertedCount > 0 && (
          <button
            onClick={handleSave}
            disabled={saving || !resumeId}
            className="inline-flex items-center gap-1.5 px-4 py-1.5 text-sm font-medium rounded-full
              bg-brand text-white hover:bg-brand-hover hover:scale-[1.02] active:scale-[0.98]
              motion-reduce:active:scale-100 transition-all duration-300 cursor-pointer
              disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {saving ? (
              <>
                <SpinnerGap size={14} weight="bold" className="animate-spin" aria-hidden="true" />
                保存中...
              </>
            ) : (
              <>
                <ArrowCounterClockwise size={14} weight="bold" aria-hidden="true" />
                保存并应用
              </>
            )}
          </button>
        )}
      </div>
    </div>
  );
}

/**
 * ResumeEditDiffDialog — AI 修改简历时实时弹窗显示前后对比。
 *
 * E2 增强：模块级 diff 之上增加字段级逐条审阅——modified 模块内按
 * metadata/平铺字段/条目字段（items 按 id 匹配）拆分，每条可单独「还原」，
 * 并有 rationale 说明；保留整模块「还原为原文」快捷操作。
 *
 * 触发场景：Agent 聊天中调用了 rewrite_star / translate 等改写类工具后，
 * tool_result 事件到达时弹出此对话框。数据来源：
 * - beforeModules: Agent 开始前快照的模块列表
 * - afterModules:  tool_result 后重新拉取的模块列表
 * - toolName:      触发修改的工具名（标题 + 审阅理由展示）
 */
export default function ResumeEditDiffDialog({
  open,
  onClose,
  resumeId,
  beforeModules,
  afterModules,
  toolName,
  loading = false,
  onModulesSaved,
}: ResumeEditDiffDialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [revertedFields, setRevertedFields] = useState<Set<string>>(new Set());

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

  // 每次打开时重置还原选择
  useEffect(() => {
    if (open) setRevertedFields(new Set());
  }, [open]);

  const diffs = useMemo(
    () => computeDiff(beforeModules, afterModules),
    [beforeModules, afterModules],
  );

  const toolLabel = TOOL_LABELS[toolName] ?? toolName;
  const rationale = TOOL_RATIONALE[toolName] ?? "AI 改写简历内容";

  const stats = useMemo(() => {
    const added = diffs.filter((d) => d.status === "added").length;
    const removed = diffs.filter((d) => d.status === "removed").length;
    const modified = diffs.filter((d) => d.status === "modified").length;
    const fields = diffs.reduce((n, d) => n + d.fieldDiffs.length, 0);
    // 可信度联动：已整模块还原的模块不再计入「含 AI 推断」
    const inferred = diffs.filter(
      (d) => d.source !== "fact" && !revertedFields.has(moduleRevertKey(d.moduleType)),
    ).length;
    return { added, removed, modified, fields, inferred, total: diffs.length };
  }, [diffs, revertedFields]);

  const handleToggleField = useCallback((moduleType: ModuleType) => (path: string) => {
    setRevertedFields((prev) => {
      const next = new Set(prev);
      const key = fieldRevertKey(moduleType, path);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }, []);

  const handleToggleModuleRevert = useCallback((entry: DiffEntry) => {
    setRevertedFields((prev) => {
      const next = new Set(prev);
      const modKey = moduleRevertKey(entry.moduleType);
      if (next.has(modKey)) {
        // 撤销整模块还原
        next.delete(modKey);
        return next;
      }
      // 整模块还原：清除该模块已有字段级还原，改为模块级标记
      for (const fd of entry.fieldDiffs) {
        next.delete(fieldRevertKey(entry.moduleType, fd.path));
      }
      next.add(modKey);
      return next;
    });
  }, []);

  const handleModulesSaved = useCallback(
    (modules: ResumeModule[]) => {
      setRevertedFields(new Set());
      onModulesSaved?.(modules);
    },
    [onModulesSaved],
  );

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
          <div className="shrink-0 p-2 rounded-action bg-brand/10 text-brand">
            <GitDiff size={18} weight="fill" aria-hidden="true" />
          </div>
          <div className="flex-1 min-w-0">
            <h3 className="text-base font-semibold text-[var(--color-text)]">
              AI 已修改简历
            </h3>
            <p className="text-xs text-[var(--color-text-muted)] mt-0.5">
              触发工具：<span className="text-brand font-medium">{toolLabel}</span>
              {!loading && stats.total > 0 && (
                <span className="ml-2">
                  · 共 {stats.total} 处模块变更
                  {stats.modified > 0 && <span className="text-warning">（{stats.modified} 修改</span>}
                  {stats.added > 0 && <span className="text-success"> {stats.added} 新增</span>}
                  {stats.removed > 0 && <span className="text-danger"> {stats.removed} 删除</span>}
                  {stats.fields > 0 && <span className="text-[var(--color-text-muted)]"> · {stats.fields} 处字段</span>}
                  {stats.inferred > 0 && <span className="text-warning"> · {stats.inferred} 含 AI 推断</span>}
                  {stats.modified > 0 && <span>）</span>}
                </span>
              )}
            </p>
          </div>
          <button
            onClick={onClose}
            aria-label="关闭"
            className="p-1.5 rounded-action text-[var(--color-text-secondary)]
              hover:text-[var(--color-text)] hover:bg-[var(--color-bg-secondary)]
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
              <div className="w-12 h-12 rounded-list bg-[var(--color-bg-tertiary)] flex items-center justify-center text-[var(--color-text-muted)] mb-3">
                <ArrowRight size={20} weight="duotone" aria-hidden="true" />
              </div>
              <p className="text-sm text-[var(--color-text-muted)]">未检测到模块内容变化</p>
              <p className="text-xs text-[var(--color-text-muted)] mt-1">可能修改了非模块数据或内容未发生实质变化</p>
            </div>
          ) : (
            diffs.map((entry) => (
              <DiffCard
                key={entry.moduleType}
                entry={entry}
                rationale={rationale}
                revertedFields={revertedFields}
                onToggleField={handleToggleField(entry.moduleType)}
                onToggleModuleRevert={() => handleToggleModuleRevert(entry)}
              />
            ))
          )}
        </div>

        {/* 底部 */}
        <SaveFooter
          resumeId={resumeId}
          beforeModules={beforeModules}
          afterModules={afterModules}
          diffs={diffs}
          revertedFields={revertedFields}
          onClose={onClose}
          onSaved={handleModulesSaved}
        />
      </div>
    </dialog>
  );
}
