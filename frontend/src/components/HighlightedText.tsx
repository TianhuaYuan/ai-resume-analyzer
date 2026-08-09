import { useMemo } from "react";

/**
 * HighlightedText — 搜索词高亮（借鉴 Hermes HighlightedText）。
 *
 * 对文本中的匹配词用 <mark> 高亮显示。用于问答历史搜索、来源高亮等场景。
 * 输入 terms 会被转义后构建正则，避免特殊字符注入。
 */
interface HighlightedTextProps {
  text: string;
  /** 要高亮的词（可多个）。空数组/全空时不高亮，原样返回。 */
  terms?: string[];
  /** 高亮样式类（默认品牌底色） */
  className?: string;
  /** 是否大小写不敏感（默认 true，中文无影响） */
  caseInsensitive?: boolean;
}

/** 转义正则特殊字符 */
function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

export default function HighlightedText({
  text,
  terms,
  className = "bg-warning/70 text-warning rounded-[2px] px-0.5 font-medium",
  caseInsensitive = true,
}: HighlightedTextProps) {
  const parts = useMemo(() => {
    const cleanTerms = (terms ?? [])
      .map((t) => t.trim())
      .filter((t) => t.length > 0)
      .sort((a, b) => b.length - a.length); // 长词优先，避免短词先匹配
    if (cleanTerms.length === 0) return [text];

    const pattern = cleanTerms.map(escapeRegExp).join("|");
    const regex = new RegExp(`(${pattern})`, caseInsensitive ? "gi" : "g");
    return text.split(regex).filter(Boolean);
  }, [text, terms, caseInsensitive]);

  // 计算每个部分是否命中（用同一个正则判断，与 split 结果一一对应）
  const hitSet = useMemo(() => {
    const cleanTerms = (terms ?? [])
      .map((t) => t.trim())
      .filter((t) => t.length > 0);
    if (cleanTerms.length === 0) return new Set<string>();
    const set = new Set<string>();
    for (const part of parts) {
      for (const t of cleanTerms) {
        if (
          caseInsensitive
            ? part.toLowerCase() === t.toLowerCase()
            : part === t
        ) {
          set.add(part);
          break;
        }
      }
    }
    return set;
  }, [parts, terms, caseInsensitive]);

  return (
    <>
      {parts.map((part, i) =>
        hitSet.has(part) ? (
          <mark key={i} className={className}>
            {part}
          </mark>
        ) : (
          <span key={i}>{part}</span>
        ),
      )}
    </>
  );
}
