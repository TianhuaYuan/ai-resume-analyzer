/**
 * PasteResumeDialog — 粘贴简历文本弹窗。
 *
 * 用户输入标题（可选）+ 粘贴简历纯文本，调用后端 parse-to-modules 解析后返回模块列表。
 * 父组件拿到模块后可选择替换当前内容。
 */

import { useState, useEffect, useRef } from "react";
import { X, ClipboardList, LoaderCircle, TriangleAlert } from "lucide-react";
import { parseToModules } from "../../api/builder";
import type { ResumeModuleInput } from "../../api/builder";

interface PasteResumeDialogProps {
  open: boolean;
  onClose: () => void;
  onParsed: (modules: ResumeModuleInput[], filename?: string) => void;
}

export default function PasteResumeDialog({ open, onClose, onParsed }: PasteResumeDialogProps) {
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [parsing, setParsing] = useState(false);
  const [error, setError] = useState("");
  const dialogRef = useRef<HTMLDialogElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open) {
      try { dialog.showModal(); } catch { dialog.open = true; }
      // 自动聚焦文本框
      setTimeout(() => textareaRef.current?.focus(), 100);
    } else {
      try { dialog.close(); } catch { dialog.open = false; }
    }
  }, [open]);

  const handleParse = async () => {
    const text = content.trim();
    if (!text) {
      setError("请粘贴简历内容");
      return;
    }
    if (text.length < 10) {
      setError("简历内容过短（至少 10 个字符）");
      return;
    }
    setParsing(true);
    setError("");
    try {
      const filename = title.trim() || undefined;
      const result = await parseToModules(text, filename);
      const modules: ResumeModuleInput[] = result.modules.map((m: ResumeModuleInput, i: number) => ({
        ...m,
        sort_order: i,
      }));
      // 标题仍是文件名；后端仅在正文确实缺失姓名、且文件名以 2-4 个中文姓名开头时
      // 将该显式元数据用于补齐姓名，不会把整个标题写进姓名字段。
      onParsed(modules, filename);
      setTitle("");
      setContent("");
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "解析失败，请稍后重试");
    } finally {
      setParsing(false);
    }
  };

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
      aria-label="粘贴简历文本"
    >
      <div
        className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2
          glass-card shadow-2xl
          max-w-2xl w-full mx-4
          animate-fade-in-up motion-reduce:animate-none"
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--color-border)]">
          <div className="flex items-center gap-2">
            <ClipboardList size={18} fill="currentColor" className="text-brand" />
            <h3 className="text-base font-semibold text-[var(--color-text)]">粘贴简历文本</h3>
          </div>
          <button
            onClick={onClose}
            aria-label="关闭"
            className="p-1.5 rounded-action text-[var(--color-text-secondary)]
              hover:text-[var(--color-text)] hover:bg-[var(--color-bg-secondary)] transition-all cursor-pointer"
          >
            <X size={18} strokeWidth={2.25} />
          </button>
        </div>

        {/* Body */}
        <div className="px-6 py-5 space-y-4">
          {/* 标题 */}
          <div>
            <label className="block text-xs font-medium text-[var(--color-text-muted)] mb-1.5">
              简历文件名（可选，如：张三-Java开发工程师）
            </label>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="张三-Java开发工程师"
              className="w-full px-3 py-2 rounded-list bg-[#F2F2F7] border border-transparent
                text-sm text-[var(--color-text)] placeholder:text-[var(--color-text-muted)]
                focus:outline-none focus:bg-white focus:border-brand/40
                focus:ring-4 focus:ring-brand/15 transition-all duration-150"
            />
          </div>

          {/* 简历内容 */}
          <div>
            <label className="block text-xs font-medium text-[var(--color-text-muted)] mb-1.5">
              请将简历内容粘贴到这里...
            </label>
            <textarea
              ref={textareaRef}
              value={content}
              onChange={(e) => setContent(e.target.value)}
              placeholder={`请将简历内容粘贴到这里...\n支持直接从PDF、Word或其他地方复制的文本\n系统会自动格式化并解析`}
              rows={12}
              maxLength={50000}
              className="w-full px-3 py-2 rounded-list bg-[#F2F2F7] border border-transparent
                text-sm text-[var(--color-text)] placeholder:text-[var(--color-text-muted)]
                focus:outline-none focus:bg-white focus:border-brand/40
                focus:ring-4 focus:ring-brand/15 transition-all duration-150 resize-none"
            />
            <p className="text-[10px] text-[var(--color-text-muted)] mt-1 text-right">
              {content.length}/50000
            </p>
          </div>

          {/* 提示 */}
          <div className="flex gap-3 p-3 rounded-action bg-brand/5 border border-brand/10">
            <TriangleAlert size={16} fill="currentColor" className="text-brand shrink-0 mt-0.5" />
            <div className="text-xs text-[var(--color-text-secondary)] space-y-1">
              <p className="font-medium text-[var(--color-text)]">粘贴提示</p>
              <ul className="list-disc list-inside space-y-0.5 text-[var(--color-text-muted)]">
                <li>如果PDF解析效果不佳，可以尝试直接复制PDF中的文本粘贴到这里</li>
                <li>支持中英文混排、技术术语、项目符号等各种格式</li>
                <li>粘贴后系统会自动清理格式并优化排版</li>
              </ul>
            </div>
          </div>

          {error && (
            <div className="p-3 rounded-action bg-danger/10 border border-danger/20 text-xs text-danger">
              {error}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 px-6 py-4 border-t border-[var(--color-border)]">
          <button
            onClick={onClose}
            className="px-4 py-2 rounded-action bg-[var(--color-bg-secondary)]
              text-xs text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-secondary)] transition-colors cursor-pointer"
          >
            取消
          </button>
          <button
            onClick={handleParse}
            disabled={parsing || !content.trim()}
            className="px-4 py-2 rounded-full bg-brand text-white text-xs font-medium
              hover:bg-brand-hover hover:scale-[1.02] transition-all duration-300 cursor-pointer
              disabled:opacity-40 disabled:cursor-not-allowed
              inline-flex items-center gap-2"
          >
            {parsing && <LoaderCircle size={12} className="animate-spin" strokeWidth={2.25} />}
            {parsing ? "解析中..." : "导入简历"}
          </button>
        </div>
      </div>
    </dialog>
  );
}
