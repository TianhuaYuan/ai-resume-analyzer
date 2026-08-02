/**
 * Task 5: RichTextEditor — 轻量级 Markdown 富文本编辑器。
 *
 * 方案：textarea + 工具栏（非 WYSIWYG）
 *
 * 功能：
 * - 工具栏按钮：加粗、斜体、H1/H2、无序/有序列表、链接、行内代码
 * - 键盘快捷键：Ctrl+B（加粗）、Ctrl+I（斜体）、Ctrl+K（链接）
 * - 选区操作：包裹选中文本或在当前行插入标记
 * - 预览切换：用 MarkdownRenderer 渲染实时预览
 * - 自适应高度：min-height + auto-resize
 */

import { useRef, useCallback, useState, useEffect } from "react";
import {
  TextB,
  TextItalic,
  TextHOne,
  TextHTwo,
  ListBullets,
  ListNumbers,
  LinkSimple,
  Code,
  Eye,
  PencilSimple,
} from "@phosphor-icons/react";
import MarkdownRenderer from "../MarkdownRenderer";

// ── Props ──────────────────────────────────────────────────────

interface RichTextEditorProps {
  /** 当前 Markdown 内容 */
  value: string;
  /** 内容变更回调 */
  onChange: (value: string) => void;
  /** 占位提示文本 */
  placeholder?: string;
  /** textarea 最小行数 */
  rows?: number;
  /** 最小高度（CSS 值，如 "120px"） */
  minHeight?: string;
  /** 是否显示预览切换按钮 */
  showPreviewToggle?: boolean;
}

// ── 选区操作辅助函数 ──────────────────────────────────────────

interface SelectionInfo {
  start: number;
  end: number;
  selected: string;
  before: string;
  after: string;
}

/** 获取 textarea 当前选区信息 */
function getSelection(textarea: HTMLTextAreaElement): SelectionInfo {
  const { selectionStart: start, selectionEnd: end, value } = textarea;
  return {
    start,
    end,
    selected: value.slice(start, end),
    before: value.slice(0, start),
    after: value.slice(end),
  };
}

/** 设置 textarea 选区范围 */
function setSelection(textarea: HTMLTextAreaElement, start: number, end: number) {
  textarea.focus();
  textarea.setSelectionRange(start, end);
}

// ── 编辑操作 ──────────────────────────────────────────────────

/** 行内包裹操作（加粗、斜体、代码） */
function wrapSelection(
  textarea: HTMLTextAreaElement,
  _value: string,
  onChange: (v: string) => void,
  prefix: string,
  suffix: string = prefix,
) {
  const sel = getSelection(textarea);
  const text = sel.selected || "文本";
  const newValue = sel.before + prefix + text + suffix + sel.after;
  onChange(newValue);

  // 选中新包裹的文本（不含标记符号）
  const newStart = sel.start + prefix.length;
  const newEnd = newStart + text.length;
  requestAnimationFrame(() => setSelection(textarea, newStart, newEnd));
}

/** 行首插入操作（标题、列表） */
function prependLine(
  textarea: HTMLTextAreaElement,
  value: string,
  onChange: (v: string) => void,
  marker: string,
) {
  const sel = getSelection(textarea);
  // 找到当前行起点
  const lineStart = sel.before.lastIndexOf("\n") + 1;
  const lineContent = value.slice(lineStart, sel.end);
  const newValue = value.slice(0, lineStart) + marker + lineContent + sel.after;
  onChange(newValue);

  // 光标移到行尾
  const newCursor = sel.end + marker.length;
  requestAnimationFrame(() => setSelection(textarea, newCursor, newCursor));
}

/** 插入链接 */
function insertLink(
  textarea: HTMLTextAreaElement,
  _value: string,
  onChange: (v: string) => void,
) {
  const sel = getSelection(textarea);
  const text = sel.selected || "链接文本";
  const link = `[${text}](url)`;
  const newValue = sel.before + link + sel.after;
  onChange(newValue);

  // 选中 url 部分方便输入
  const urlStart = sel.start + text.length + 3; // [text](
  const urlEnd = urlStart + 3; // url
  requestAnimationFrame(() => setSelection(textarea, urlStart, urlEnd));
}

// ── 工具栏按钮配置 ────────────────────────────────────────────

interface ToolbarButton {
  icon: React.ReactNode;
  label: string;
  shortcut?: string;
  action: (textarea: HTMLTextAreaElement, value: string, onChange: (v: string) => void) => void;
}

const TOOLBAR_BUTTONS: ToolbarButton[] = [
  {
    icon: <TextB size={14} weight="bold" />,
    label: "加粗",
    shortcut: "Ctrl+B",
    action: (ta, val, cb) => wrapSelection(ta, val, cb, "**"),
  },
  {
    icon: <TextItalic size={14} weight="bold" />,
    label: "斜体",
    shortcut: "Ctrl+I",
    action: (ta, val, cb) => wrapSelection(ta, val, cb, "*"),
  },
  {
    icon: <TextHOne size={14} weight="bold" />,
    label: "一级标题",
    action: (ta, val, cb) => prependLine(ta, val, cb, "# "),
  },
  {
    icon: <TextHTwo size={14} weight="bold" />,
    label: "二级标题",
    action: (ta, val, cb) => prependLine(ta, val, cb, "## "),
  },
  {
    icon: <ListBullets size={14} weight="bold" />,
    label: "无序列表",
    action: (ta, val, cb) => prependLine(ta, val, cb, "- "),
  },
  {
    icon: <ListNumbers size={14} weight="bold" />,
    label: "有序列表",
    action: (ta, val, cb) => prependLine(ta, val, cb, "1. "),
  },
  {
    icon: <LinkSimple size={14} weight="bold" />,
    label: "链接",
    shortcut: "Ctrl+K",
    action: (ta, val, cb) => insertLink(ta, val, cb),
  },
  {
    icon: <Code size={14} weight="bold" />,
    label: "行内代码",
    action: (ta, val, cb) => wrapSelection(ta, val, cb, "`"),
  },
];

// ── 主组件 ──────────────────────────────────────────────────────

export function RichTextEditor({
  value,
  onChange,
  placeholder = "输入内容...（支持 Markdown）",
  rows = 4,
  minHeight = "100px",
  showPreviewToggle = true,
}: RichTextEditorProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [previewMode, setPreviewMode] = useState(false);

  // 自适应高度：内容变化时调整 textarea 高度
  useEffect(() => {
    const ta = textareaRef.current;
    if (!ta || previewMode) return;
    ta.style.height = "auto";
    ta.style.height = `${Math.max(ta.scrollHeight, parseInt(minHeight))}px`;
  }, [value, minHeight, previewMode]);

  // 键盘快捷键
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (!(e.ctrlKey || e.metaKey)) return;
      const ta = e.currentTarget;

      switch (e.key.toLowerCase()) {
        case "b":
          e.preventDefault();
          wrapSelection(ta, value, onChange, "**");
          break;
        case "i":
          e.preventDefault();
          wrapSelection(ta, value, onChange, "*");
          break;
        case "k":
          e.preventDefault();
          insertLink(ta, value, onChange);
          break;
      }
    },
    [value, onChange],
  );

  // 工具栏按钮点击
  const handleToolbarAction = useCallback(
    (action: ToolbarButton["action"]) => {
      const ta = textareaRef.current;
      if (!ta) return;
      action(ta, value, onChange);
    },
    [value, onChange],
  );

  // 预览模式渲染
  if (previewMode) {
    return (
      <div className="flex flex-col">
        {/* 工具栏（仅预览切换） */}
        <div className="flex items-center justify-between px-2 py-1.5 rounded-t-lg
          bg-[var(--color-bg-secondary)] border border-[var(--color-border)] border-b-0">
          <span className="text-[10px] text-[var(--color-text-muted)] uppercase tracking-wider">
            预览
          </span>
          <button
            onClick={() => setPreviewMode(false)}
            className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px]
              text-[var(--color-text-muted)]
              hover:text-brand hover:bg-brand/10
              transition-all cursor-pointer"
            aria-label="切换到编辑模式"
          >
            <PencilSimple size={11} weight="bold" aria-hidden="true" />
            编辑
          </button>
        </div>
        {/* Markdown 渲染区 */}
        <div
          className="px-3 py-2 rounded-b-lg overflow-y-auto
            bg-[var(--color-bg-secondary)] border border-[var(--color-border)]
            text-sm text-[var(--color-text)]"
          style={{ minHeight }}
        >
          {value ? (
            <MarkdownRenderer>{value}</MarkdownRenderer>
          ) : (
            <span className="text-[var(--color-text-muted)] italic">{placeholder}</span>
          )}
        </div>
      </div>
    );
  }

  // 编辑模式渲染
  return (
    <div className="flex flex-col">
      {/* 工具栏 */}
      <div className="flex items-center gap-0.5 px-1.5 py-1 rounded-t-lg
        bg-[var(--color-bg-secondary)] border border-[var(--color-border)] border-b-0">
        {TOOLBAR_BUTTONS.map((btn) => (
          <button
            key={btn.label}
            onClick={() => handleToolbarAction(btn.action)}
            className="p-1 rounded text-[var(--color-text-muted)]
              hover:text-brand hover:bg-brand/10
              active:scale-90 motion-reduce:active:scale-100
              transition-all cursor-pointer"
            aria-label={btn.label}
            title={btn.shortcut ? `${btn.label} (${btn.shortcut})` : btn.label}
          >
            {btn.icon}
          </button>
        ))}

        {/* 分隔线 */}
        <div className="w-px h-4 bg-[var(--color-border)] mx-0.5" />

        {/* 预览切换 */}
        {showPreviewToggle && (
          <button
            onClick={() => setPreviewMode(true)}
            className="p-1 rounded text-[var(--color-text-muted)]
              hover:text-brand hover:bg-brand/10
              active:scale-90 motion-reduce:active:scale-100
              transition-all cursor-pointer"
            aria-label="预览"
            title="预览"
          >
            <Eye size={14} weight="bold" aria-hidden="true" />
          </button>
        )}
      </div>

      {/* textarea */}
      <textarea
        ref={textareaRef}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={placeholder}
        rows={rows}
        className="w-full px-3 py-2 rounded-b-lg resize-none
          text-sm text-[var(--color-text)]
          bg-[#F2F2F7] border border-transparent
          placeholder:text-[var(--color-text-muted)]
          focus:outline-none focus:bg-white focus:ring-2 focus:ring-brand/40
          focus:border-brand/40
          transition-all duration-150
          font-mono leading-relaxed"
        style={{ minHeight }}
        aria-label="Markdown 编辑器"
      />
    </div>
  );
}
