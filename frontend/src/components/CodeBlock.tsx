import { useState, isValidElement, type ReactNode, type ReactElement } from "react";
import { Check, Copy, ChevronDown, ChevronRight } from "lucide-react";

/** 递归提取 ReactNode 的纯文本（用于复制代码 / 行数统计，剥离 hljs span） */
function extractText(node: ReactNode): string {
  if (node == null) return "";
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(extractText).join("");
  if (isValidElement(node)) return extractText((node as ReactElement<{ children?: ReactNode }>).props.children);
  return "";
}

/**
 * CodeBlock — 代码块（Open WebUI 风格：圆角容器 + 顶部工具条）。
 *
 * 顶部工具条：语言名（从 language-xxx 提取）+ 复制 + 折叠（收起时显示 "N 行已折叠"）。
 * 深浅主题统一使用深色代码底色（github-dark 高亮），对齐 Open WebUI。
 */
export default function CodeBlock({ children }: { children: ReactNode }) {
  const [copied, setCopied] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const codeElement = isValidElement(children)
    ? (children as ReactElement<{ className?: string; children?: ReactNode }>)
    : null;
  const className = (codeElement?.props.className as string | undefined) ?? "";
  const language = className.startsWith("language-") ? className.slice("language-".length) : "text";
  const text = extractText(children);
  const lineCount = text.split("\n").length;

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch { /* 忽略复制失败 */ }
  };

  return (
    <div className="my-3 rounded-2xl border border-[var(--color-border)] bg-[#0d1117] overflow-hidden">
      {/* 顶部工具条 */}
      <div className="flex items-center justify-between px-3 py-1.5 bg-white/5 border-b border-white/10">
        <span className="text-[11px] font-mono text-gray-400">{language}</span>
        <div className="flex items-center gap-0.5">
          <button
            onClick={handleCopy}
            aria-label={copied ? "已复制" : "复制代码"}
            title={copied ? "已复制" : "复制代码"}
            className="p-1 rounded text-gray-400 hover:text-white hover:bg-white/10 transition-colors cursor-pointer"
          >
            {copied ? <Check size={12} strokeWidth={2.25} aria-hidden="true" /> : <Copy size={12} aria-hidden="true" />}
          </button>
          <button
            onClick={() => setCollapsed((v) => !v)}
            aria-label={collapsed ? "展开代码" : "折叠代码"}
            title={collapsed ? "展开代码" : "折叠代码"}
            className="p-1 rounded text-gray-400 hover:text-white hover:bg-white/10 transition-colors cursor-pointer"
          >
            {collapsed ? <ChevronRight size={12} aria-hidden="true" /> : <ChevronDown size={12} aria-hidden="true" />}
          </button>
        </div>
      </div>
      {/* 代码正文 */}
      {collapsed ? (
        <div className="px-3 py-2 text-[11px] text-gray-500">{lineCount} 行代码已折叠</div>
      ) : (
        <pre className="markdown-pre overflow-x-auto text-xs leading-relaxed">
          <code className={className}>{codeElement?.props.children}</code>
        </pre>
      )}
    </div>
  );
}
