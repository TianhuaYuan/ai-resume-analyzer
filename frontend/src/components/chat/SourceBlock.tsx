import { useState } from "react";
import { ChevronRight, ChevronDown, Paperclip } from "lucide-react";
import type { DiagnosisSource } from "./DiagnosisCard";

interface SourceBlockProps {
  sources: DiagnosisSource[];
  /** 折叠头部标题（默认"来源原文"） */
  title?: string;
  /** 编号模式：每条显示 [n]（Open WebUI Citations 风格） */
  numbered?: boolean;
}

/**
 * SourceBlock — 可溯源「来源原文」折叠区（从 DiagnosisCard 私有实现泛化）。
 *
 * 每条：section 标签（或"片段 i"）+ 相关度 + 字符区间 + 文本片段（line-clamp-3 可展开）。
 * numbered 模式下每条带 [n] 序号，供普通问答的 Citations 展示复用。
 */
export default function SourceBlock({ sources, title = "来源原文", numbered = false }: SourceBlockProps) {
  const [open, setOpen] = useState(false);
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null);
  const items = sources.filter((s) => s && typeof s.text === "string" && s.text.length > 0);
  if (items.length === 0) return null;

  return (
    <div className="rounded-list border border-[var(--color-border)] bg-[var(--color-bg-secondary)]/40 overflow-hidden">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between gap-2 px-3.5 py-2.5 text-xs font-medium
          text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-secondary)] transition-colors cursor-pointer"
      >
        <span className="inline-flex items-center gap-1.5 min-w-0">
          <Paperclip size={13} className="text-brand shrink-0" aria-hidden="true" />
          <span className="truncate">{title}</span>
          <span className="text-[10px] text-[var(--color-text-muted)] shrink-0">
            {items.length} 条
          </span>
        </span>
        {open ? (
          <ChevronDown size={13} className="shrink-0" aria-hidden="true" />
        ) : (
          <ChevronRight size={13} className="shrink-0" aria-hidden="true" />
        )}
      </button>
      {open && (
        <div className="px-3.5 pb-3 space-y-2">
          {items.map((s, i) => {
            const expanded = expandedIdx === i;
            return (
              <button
                key={i}
                onClick={() => setExpandedIdx(expanded ? null : i)}
                className="w-full text-left rounded-action border border-[var(--color-border)]
                  bg-white/60 p-2.5 transition-colors cursor-pointer hover:border-brand/30"
              >
                <div className="flex items-center gap-1.5 flex-wrap">
                  {numbered && (
                    <span className="shrink-0 inline-flex items-center justify-center w-4 h-4 rounded text-[9px] font-mono text-brand bg-brand/10">
                      {i + 1}
                    </span>
                  )}
                  {s.section ? (
                    <span className="px-1.5 py-0.5 rounded-md text-[10px] font-medium text-brand
                      bg-brand/10 border border-brand/15">
                      {s.section}
                    </span>
                  ) : (
                    <span className="px-1.5 py-0.5 rounded-md text-[10px] font-medium
                      text-[var(--color-text-muted)] bg-[var(--color-bg-secondary)] border border-[var(--color-border)]">
                      片段 {i + 1}
                    </span>
                  )}
                  {typeof s.score === "number" &&
                    (s.score_kind === "dense_similarity" ||
                    s.score_kind === "rerank_relevance") &&
                    s.score >= 0 &&
                    s.score <= 1 ? (
                    <span className="text-[10px] text-[var(--color-text-muted)]">
                      相关度 {Math.round(s.score * 100)}%
                    </span>
                    ) : typeof s.score === "number" ? (
                    <span className="text-[10px] text-[var(--color-text-muted)]">
                      评分 {s.score.toFixed(2)}
                    </span>
                    ) : null}
                  {s.start_char != null && s.end_char != null && (
                    <span className="text-[10px] font-mono text-[var(--color-text-muted)]">
                      字符 {s.start_char}–{s.end_char}
                    </span>
                  )}
                  <span className="ml-auto shrink-0 text-[var(--color-text-muted)]">
                    {expanded ? (
                      <ChevronDown size={12} aria-hidden="true" />
                    ) : (
                      <ChevronRight size={12} aria-hidden="true" />
                    )}
                  </span>
                </div>
                <p
                  className={`mt-1.5 text-xs text-[var(--color-text-secondary)] leading-relaxed whitespace-pre-wrap break-words ${
                    expanded ? "" : "line-clamp-3"
                  }`}
                >
                  {s.text}
                </p>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
