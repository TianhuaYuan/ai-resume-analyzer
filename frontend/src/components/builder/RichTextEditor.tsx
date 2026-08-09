/**
 * RichTextEditor — Tiptap v3 WYSIWYG 富文本编辑器。
 *
 * 由 textarea + Markdown 标记升级为所见即所得编辑，对外 props 签名完全不变
 * （value / onChange / placeholder / rows / minHeight / showPreviewToggle），
 * 存储仍为 Markdown 字符串：
 * - 初始 content 与受控回灌 setContent 均按 contentType:"markdown" 解析
 * - onUpdate 用 editor.getMarkdown() 序列化回 Markdown 并发射 onChange
 * - 受控回灌防抖：仅当外部 value 与"上次发射值"不一致时才 setContent，
 *   避免光标跳动与 onChange 循环
 * - 工具栏按钮映射 Tiptap toggle 命令，active 态用 editor.isActive() 驱动
 * - 预览模式已删除（showPreviewToggle 参数保留但忽略，保证调用方零改动）
 */

import { useRef, useCallback, useEffect, useState } from "react";
import type { Editor } from "@tiptap/react";
import { useEditor, EditorContent, useEditorState } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import { Markdown } from "@tiptap/markdown";
import Link from "@tiptap/extension-link";
import Placeholder from "@tiptap/extension-placeholder";
import {
  TextB,
  TextItalic,
  TextHOne,
  TextHTwo,
  ListBullets,
  ListNumbers,
  LinkSimple,
  Code,
  Lightning,
} from "@phosphor-icons/react";
import { aiRewrite } from "../../api/builder";

// ── Props（对外签名与旧实现完全一致）─────────────────────────────

interface RichTextEditorProps {
  /** 当前 Markdown 内容 */
  value: string;
  /** 内容变更回调 */
  onChange: (value: string) => void;
  /** 占位提示文本 */
  placeholder?: string;
  /** 最小行数（WYSIWYG 下保留以兼容调用方，高度由 minHeight 控制） */
  rows?: number;
  /** 最小高度（CSS 值，如 "120px"） */
  minHeight?: string;
  /** 是否显示预览切换（预览模式已删除，参数保留兼容调用方） */
  showPreviewToggle?: boolean;
  /** G3 悬浮改写：提供 resumeId + moduleType 时启用「选中文本 → 悬浮 AI 改写」 */
  ai?: { resumeId: number; moduleType: string };
}

// ── 工具栏按钮配置 ──────────────────────────────────────────────

/** 各按钮的 active 态字段 */
interface ActiveState {
  bold: boolean;
  italic: boolean;
  h1: boolean;
  h2: boolean;
  bullet: boolean;
  ordered: boolean;
  link: boolean;
  code: boolean;
}

interface ToolbarButton {
  icon: React.ReactNode;
  label: string;
  shortcut?: string;
  /** 对应 ActiveState 中的字段，用于 active 态高亮 */
  activeKey: keyof ActiveState;
  /** 触发 Tiptap 命令 */
  run: (editor: Editor) => void;
}

/** 插入链接：选区非空则套用链接，否则插入带链接的占位文本 */
function runLink(editor: Editor) {
  const url = window.prompt("请输入链接地址", "https://");
  if (url === null) return;
  const href = url.trim() || "https://";
  const { empty } = editor.state.selection;
  if (empty) {
    editor
      .chain()
      .focus()
      .insertContent({
        type: "text",
        marks: [{ type: "link", attrs: { href } }],
        text: "链接文本",
      })
      .run();
  } else {
    editor.chain().focus().extendMarkRange("link").setLink({ href }).run();
  }
}

const TOOLBAR_BUTTONS: ToolbarButton[] = [
  {
    icon: <TextB size={14} weight="bold" />,
    label: "加粗",
    shortcut: "Ctrl+B",
    activeKey: "bold",
    run: (e) => e.chain().focus().toggleBold().run(),
  },
  {
    icon: <TextItalic size={14} weight="bold" />,
    label: "斜体",
    shortcut: "Ctrl+I",
    activeKey: "italic",
    run: (e) => e.chain().focus().toggleItalic().run(),
  },
  {
    icon: <TextHOne size={14} weight="bold" />,
    label: "一级标题",
    activeKey: "h1",
    run: (e) => e.chain().focus().toggleHeading({ level: 1 }).run(),
  },
  {
    icon: <TextHTwo size={14} weight="bold" />,
    label: "二级标题",
    activeKey: "h2",
    run: (e) => e.chain().focus().toggleHeading({ level: 2 }).run(),
  },
  {
    icon: <ListBullets size={14} weight="bold" />,
    label: "无序列表",
    activeKey: "bullet",
    run: (e) => e.chain().focus().toggleBulletList().run(),
  },
  {
    icon: <ListNumbers size={14} weight="bold" />,
    label: "有序列表",
    activeKey: "ordered",
    run: (e) => e.chain().focus().toggleOrderedList().run(),
  },
  {
    icon: <LinkSimple size={14} weight="bold" />,
    label: "链接",
    shortcut: "Ctrl+K",
    activeKey: "link",
    run: runLink,
  },
  {
    icon: <Code size={14} weight="bold" />,
    label: "行内代码",
    activeKey: "code",
    run: (e) => e.chain().focus().toggleCode().run(),
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
  ai,
}: RichTextEditorProps) {
  // 用 ref 持有最新 onChange，避免 useEditor 创建时闭包过期
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;

  /** 上次通过 onChange 发射出去的 Markdown，用于受控回灌防抖 */
  const lastEmittedRef = useRef<string | null>(null);

  const editor = useEditor({
    extensions: [
      StarterKit,
      Link.configure({ openOnClick: false }),
      Placeholder.configure({ placeholder }),
      Markdown,
    ],
    content: value ?? "",
    contentType: "markdown",
    onUpdate: ({ editor }) => {
      const md = editor.getMarkdown();
      lastEmittedRef.current = md;
      onChangeRef.current(md);
    },
  });

  // 受控回灌防抖：仅当外部 value 与"上次发射值"不一致时才 setContent，
  // 避免自身发射的 onChange 回流造成光标跳动 / 无限循环。
  useEffect(() => {
    if (!editor) return;
    // 首次挂载：编辑器已用 content 初始化，仅记录基准值
    if (lastEmittedRef.current === null) {
      lastEmittedRef.current = value;
      return;
    }
    if (value !== lastEmittedRef.current) {
      lastEmittedRef.current = value;
      editor.commands.setContent(value ?? "", {
        contentType: "markdown",
        emitUpdate: false,
      });
    }
  }, [editor, value]);

  // 订阅选区/文档变化，驱动工具栏 active 态
  const activeState = useEditorState({
    editor,
    selector: ({ editor }) => ({
      bold: editor.isActive("bold"),
      italic: editor.isActive("italic"),
      h1: editor.isActive("heading", { level: 1 }),
      h2: editor.isActive("heading", { level: 2 }),
      bullet: editor.isActive("bulletList"),
      ordered: editor.isActive("orderedList"),
      link: editor.isActive("link"),
      code: editor.isActive("code"),
    }),
  });

  const handleToolbar = useCallback(
    (btn: ToolbarButton) => {
      if (!editor) return;
      btn.run(editor);
    },
    [editor],
  );

  // Ctrl+K 插入链接（StarterKit 已内置 Ctrl+B / Ctrl+I）
  const handleEditorKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        if (editor) runLink(editor);
      }
    },
    [editor],
  );

  // ── G3 悬浮改写（ai prop 存在时启用）────────────────────────
  // 选中文本 → 悬浮「AI 改写」按钮 → 调 aiRewrite 改写 → 替换选区（可接受/放弃）
  const [hoverSel, setHoverSel] = useState<{ from: number; to: number; text: string } | null>(null);
  const [floatPos, setFloatPos] = useState<{ x: number; y: number } | null>(null);
  const [rewrite, setRewrite] = useState<
    | { original: string; rewritten: string; from: number; to: number; loading: boolean }
    | null
  >(null);

  // 选区变化 → 非空（且编辑器聚焦）时显示悬浮改写按钮
  useEffect(() => {
    if (!editor) return;
    const onSelection = () => {
      const { from, to, empty } = editor.state.selection;
      if (!empty && ai && editor.isFocused) {
        const text = editor.state.doc.textBetween(from, to, " ");
        if (text.trim().length >= 2) {
          const coords = editor.view.coordsAtPos(from);
          setFloatPos({ x: coords.left, y: coords.top - 34 });
          setHoverSel({ from, to, text });
          return;
        }
      }
      setFloatPos(null);
      setHoverSel(null);
    };
    editor.on("selectionUpdate", onSelection);
    return () => {
      editor.off("selectionUpdate", onSelection);
    };
  }, [editor, ai]);

  const handleFloatRewrite = useCallback(async () => {
    if (!hoverSel || !ai || !floatPos) return;
    const { from, to, text } = hoverSel;
    setRewrite({ original: text, rewritten: "", from, to, loading: true });
    try {
      const res = await aiRewrite(
        ai.resumeId,
        text,
        "润色改写，保持原意与专业表述，不新增简历外的事实",
        ai.moduleType,
      );
      setRewrite({ original: text, rewritten: res.rewritten_text, from, to, loading: false });
    } catch {
      // 失败恢复：不替换、关闭气泡
      setRewrite(null);
      setHoverSel(null);
      setFloatPos(null);
    }
  }, [hoverSel, ai, floatPos]);

  const handleRewriteAccept = useCallback(() => {
    if (!editor || !rewrite) return;
    editor
      .chain()
      .focus()
      .deleteRange({ from: rewrite.from, to: rewrite.to })
      .insertContent(rewrite.rewritten)
      .run();
    setRewrite(null);
    setHoverSel(null);
    setFloatPos(null);
  }, [editor, rewrite]);

  const handleRewriteReject = useCallback(() => {
    setRewrite(null);
    setHoverSel(null);
    setFloatPos(null);
  }, []);

  // rows / showPreviewToggle 仅为对外签名兼容而保留（WYSIWYG 下不参与渲染）
  void rows;
  void showPreviewToggle;

  return (
    <div className="flex flex-col">
      {/* 工具栏 */}
      <div className="flex items-center gap-0.5 px-1.5 py-1 rounded-t-lg
        bg-[var(--color-bg-secondary)] border border-[var(--color-border)] border-b-0">
        {TOOLBAR_BUTTONS.map((btn) => {
          const active = activeState?.[btn.activeKey] ?? false;
          return (
            <button
              key={btn.label}
              type="button"
              onClick={() => handleToolbar(btn)}
              className={`p-1 rounded text-[var(--color-text-muted)]
                hover:text-brand hover:bg-brand/10
                active:scale-90 motion-reduce:active:scale-100
                transition-all cursor-pointer
                ${active ? "text-brand bg-brand/10" : ""}`}
              aria-label={btn.label}
              aria-pressed={active}
              title={btn.shortcut ? `${btn.label} (${btn.shortcut})` : btn.label}
            >
              {btn.icon}
            </button>
          );
        })}
      </div>

      {/* WYSIWYG 编辑区（min-height 作用在容器上，.ProseMirror 继承） */}
      <div
        className="w-full rounded-b-lg
          bg-[#F2F2F7] border border-transparent
          focus-within:bg-white focus-within:ring-2 focus-within:ring-brand/40
          focus-within:border-brand/40
          transition-all duration-150"
        style={{ minHeight }}
        onKeyDown={handleEditorKeyDown}
        aria-label="Markdown 编辑器"
      >
        <EditorContent editor={editor} />
      </div>

      {/* G3 悬浮改写：选中文本按钮 / 改写预览气泡 */}
      {ai && floatPos && hoverSel && !rewrite && (
        <button
          type="button"
          style={{ position: "fixed", left: floatPos.x, top: floatPos.y, zIndex: 50 }}
          className="flex items-center gap-1 rounded-full bg-brand px-2.5 py-1 text-xs font-medium text-white shadow-lg transition-all hover:brightness-110 active:scale-95"
          onClick={handleFloatRewrite}
          title="AI 改写选中文本"
        >
          <Lightning size={12} weight="fill" /> AI 改写
        </button>
      )}
      {ai && rewrite && (
        <div
          style={{ position: "fixed", left: floatPos?.x ?? 0, top: (floatPos?.y ?? 0) - 4, zIndex: 50 }}
          className="w-72 rounded-xl border border-[var(--color-border)] bg-white p-3 shadow-xl"
        >
          {rewrite.loading ? (
            <div className="flex items-center gap-2 text-sm text-[var(--color-text-secondary)]">
              <Lightning size={14} className="animate-pulse text-brand" /> AI 改写中…
            </div>
          ) : (
            <>
              <div className="mb-2 max-h-40 overflow-auto rounded-md bg-[#F2F2F7] p-2 text-xs leading-relaxed text-[var(--color-text)]">
                {rewrite.rewritten}
              </div>
              <div className="flex items-center justify-end gap-1.5">
                <button
                  type="button"
                  onClick={handleRewriteReject}
                  className="rounded-md px-2 py-1 text-xs text-[var(--color-text-muted)] hover:bg-[var(--color-bg-secondary)]"
                >
                  放弃
                </button>
                <button
                  type="button"
                  onClick={handleRewriteAccept}
                  className="rounded-md bg-brand px-2.5 py-1 text-xs font-medium text-white hover:brightness-110"
                >
                  接受替换
                </button>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
