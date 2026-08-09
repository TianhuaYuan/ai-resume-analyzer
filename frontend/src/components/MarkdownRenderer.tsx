import { memo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkBreaks from "remark-breaks";
import rehypeSanitize from "rehype-sanitize";

interface MarkdownRendererProps {
  children: string;
  className?: string;
  /**
   * 超过该字符数时折叠展示（截断 + 展开全文按钮）。
   * 用于超长答案：避免一次性解析/构建巨大 markdown DOM（agent_done 后
   * 全量渲染是"最后一次渲染慢"的卡点）。
   */
  maxChars?: number;
}

/**
 * Task 2.4: 通用 Markdown 渲染组件
 *
 * - GFM: 表格、删除线、任务列表（remark-gfm）
 * - 单换行转 <br>: LLM 经常单换行输出列表项（remark-breaks）
 * - 安全过滤: 剥离 <script>、on* 事件、javascript: 协议（rehype-sanitize）
 * - 自定义样式: 通过 components API 映射 className，与深色主题对齐
 */
function MarkdownRendererImpl({ children, className, maxChars }: MarkdownRendererProps) {
  const [expanded, setExpanded] = useState(false);
  const text = children || "";
  const isLong = maxChars != null && text.length > maxChars;
  // 截断到最近的换行，避免从 markdown 语法（表格/代码块）中间切开
  const display =
    isLong && !expanded ? text.slice(0, maxChars).replace(/\n[^\n]*$/, "") : text;
  return (
    <div
      className={`text-sm text-[var(--color-text-secondary)] leading-relaxed ${className ?? ""}`}
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkBreaks]}
        rehypePlugins={[rehypeSanitize]}
        components={{
          h1: ({ node, ...props }) => (
            <h1 className="markdown-h1 text-lg font-semibold mt-4 mb-2 text-[var(--color-text)]" {...props} />
          ),
          h2: ({ node, ...props }) => (
            <h2 className="markdown-h2 text-base font-semibold mt-3 mb-2 text-[var(--color-text)]" {...props} />
          ),
          h3: ({ node, ...props }) => (
            <h3 className="markdown-h3 text-sm font-semibold mt-3 mb-1.5 text-[var(--color-text)]" {...props} />
          ),
          h4: ({ node, ...props }) => (
            <h4 className="markdown-h4 text-sm font-medium mt-2 mb-1 text-[var(--color-text)]" {...props} />
          ),
          p: ({ node, ...props }) => (
            <p className="markdown-p my-2" {...props} />
          ),
          ul: ({ node, ...props }) => (
            <ul className="markdown-ul list-disc pl-5 my-2 space-y-1" {...props} />
          ),
          ol: ({ node, ...props }) => (
            <ol className="markdown-ol list-decimal pl-5 my-2 space-y-1" {...props} />
          ),
          li: ({ node, ...props }) => (
            <li
              className="markdown-li pl-1 leading-relaxed
                marker:text-[var(--color-text-muted)]"
              {...props}
            />
          ),
          strong: ({ node, ...props }) => (
            <strong
              className="markdown-strong markdown-strong-inline
                font-semibold text-[var(--color-text)]"
              {...props}
            />
          ),
          em: ({ node, ...props }) => (
            <em className="markdown-em" {...props} />
          ),
          del: ({ node, ...props }) => (
            <del className="markdown-del text-[var(--color-text-muted)]" {...props} />
          ),
          a: ({ node, ...props }) => (
            <a
              className="markdown-a text-brand hover:text-brand-hover underline-offset-2 hover:underline"
              target="_blank"
              rel="noopener noreferrer"
              {...props}
            />
          ),
          blockquote: ({ node, ...props }) => (
            <blockquote
              className="markdown-blockquote border-l-2 border-brand/40 pl-3 my-2 italic text-[var(--color-text-muted)]"
              {...props}
            />
          ),
          code: ({ node, className: codeClassName, children: codeChildren, ...props }) => {
            const isInline = !codeClassName?.startsWith("language-");
            if (isInline) {
              return (
                <code
                  className="markdown-code px-1 py-0.5 rounded bg-white/8 text-[var(--color-text)] text-xs font-mono"
                  {...props}
                >
                  {codeChildren}
                </code>
              );
            }
            return (
              <code className={codeClassName} {...props}>
                {codeChildren}
              </code>
            );
          },
          pre: ({ node, ...props }) => (
            <pre
              className="markdown-pre my-3 p-3 rounded-action bg-black/40 border border-[var(--color-border)] overflow-x-auto text-xs"
              {...props}
            />
          ),
          table: ({ node, ...props }) => (
            <div className="markdown-table-wrap my-3 overflow-x-auto">
              <table
                className="markdown-table w-full text-xs border-collapse border border-[var(--color-border)]"
                {...props}
              />
            </div>
          ),
          thead: ({ node, ...props }) => (
            <thead className="markdown-thead bg-[var(--color-bg-secondary)]" {...props} />
          ),
          th: ({ node, ...props }) => (
            <th
              className="markdown-th px-2 py-1.5 text-left font-semibold border border-[var(--color-border)] text-[var(--color-text)]"
              {...props}
            />
          ),
          td: ({ node, ...props }) => (
            <td
              className="markdown-td px-2 py-1.5 border border-[var(--color-border)]"
              {...props}
            />
          ),
          hr: ({ node, ...props }) => (
            <hr className="markdown-hr my-3 border-[var(--color-border)]" {...props} />
          ),
        }}
      >
        {display}
      </ReactMarkdown>
      {isLong && (
        <button
          onClick={() => setExpanded((v) => !v)}
          className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-brand hover:underline cursor-pointer"
          aria-expanded={expanded}
        >
          {expanded ? "收起" : `展开全文（共 ${text.length} 字）`}
        </button>
      )}
    </div>
  );
}

const MarkdownRenderer = memo(MarkdownRendererImpl);
export default MarkdownRenderer;
