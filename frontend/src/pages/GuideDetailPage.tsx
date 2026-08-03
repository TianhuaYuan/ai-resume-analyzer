/**
 * GuideDetailPage — 求职攻略详情页（站内阅读）。
 *
 * 数据来自市场数据接口：/api/v1/market/guides/{id}
 * - 标题 + 日期 + 正文
 * - 全文模式：纯文本智能解析（标题 / 小节标题 / 段落）
 * - 摘要模式：MarkdownRenderer 渲染
 * - 返回按钮回到攻略列表
 */

import { useMemo } from "react";
import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  BookOpen,
  CalendarBlank,
  Spinner,
  CaretLeft,
} from "@phosphor-icons/react";
import { getGuide, type MarketGuideDetail } from "../api/market";
import MarkdownRenderer from "../components/MarkdownRenderer";

function formatDate(dateStr?: string | null): string {
  if (!dateStr) return "-";
  const normalized = /[Z+]/.test(dateStr) ? dateStr : dateStr + "Z";
  const d = new Date(normalized);
  if (isNaN(d.getTime())) return dateStr.slice(0, 10);
  return d.toLocaleDateString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit" });
}

// ── 纯文本智能解析渲染 ──

const HEADER_MAX_LEN = 20;

/**
 * 将纯文本逐行解析为结构化块。
 *
 * 规则：
 * - 第一行 → title
 * - 空行 → 分段间隔（gap 块）
 * - ≤20 字的独立行 → 小节标题（h2）
 * - 其余 → 段落（p）
 */
function parseTextBlocks(text: string) {
  const lines = text.split("\n");
  const title = lines[0]?.trim() || "";

  interface ParsedBlock {
    type: "header" | "paragraph";
    text: string;
  }

  const blocks: ParsedBlock[] = [];
  let i = 1;
  while (i < lines.length) {
    const trimmed = lines[i].trim();
    if (trimmed === "") {
      i++;
      continue;
    }
    // 小节标题：短行（≤20字）
    if (trimmed.length <= HEADER_MAX_LEN) {
      blocks.push({ type: "header", text: trimmed });
      i++;
    } else {
      // 段落：收集连续非空、非标题行
      const para: string[] = [];
      while (i < lines.length && lines[i].trim() !== "" && lines[i].trim().length > HEADER_MAX_LEN) {
        para.push(lines[i].trim());
        i++;
      }
      blocks.push({ type: "paragraph", text: para.join(" ") });
    }
  }
  return { title, blocks };
}

export default function GuideDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

  const [guide, setGuide] = useState<MarketGuideDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!id) return;
    setLoading(true);
    setError("");
    getGuide(id)
      .then(setGuide)
      .catch((err) => setError(err instanceof Error ? err.message : "加载失败，请稍后再试"))
      .finally(() => setLoading(false));
  }, [id]);

  // 全文模式：解析纯文本为结构化块
  const parsed = useMemo(() => {
    if (guide?.has_fulltext && guide.content) {
      return parseTextBlocks(guide.content);
    }
    return null;
  }, [guide]);

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-3xl mx-auto px-6 py-6">
        {/* 返回 */}
        <button onClick={() => navigate(-1)}
          className="inline-flex items-center gap-1 text-xs text-[var(--color-text-muted)] hover:text-brand transition-colors cursor-pointer mb-4">
          <CaretLeft size={13} weight="bold" /> 返回攻略列表
        </button>

        {loading ? (
          <div className="flex items-center justify-center py-24">
            <Spinner size={20} className="animate-spin text-[var(--color-text-muted)]" />
          </div>
        ) : error || !guide ? (
          <div className="glass-card flex flex-col items-center justify-center py-24">
            <BookOpen size={32} className="text-[var(--color-text-muted)] mb-3" />
            <p className="text-sm text-[var(--color-text-secondary)]">{error || "攻略不存在或已下架"}</p>
          </div>
        ) : (
          <article className="glass-card px-6 py-6 animate-fade-in-up">
            {/* 头部 */}
            <div className="mb-5">
              <h1 className="text-xl font-bold text-[var(--color-text)] display-tight leading-snug mb-2">
                {parsed?.title || guide.title}
              </h1>
              <div className="flex items-center gap-3 text-[10px] text-[var(--color-text-muted)]">
                <span className="inline-flex items-center gap-1">
                  <CalendarBlank size={11} weight="duotone" /> {formatDate(guide.date)}
                </span>
                <span>来源：公开渠道求职攻略</span>
              </div>
            </div>

            {/* 正文 */}
            <div className="border-t border-[var(--color-border)] pt-5">
              {guide.content ? (
                guide.has_fulltext && parsed ? (
                  /* 全文模式：逐行智能解析渲染 */
                  <div>
                    {parsed.blocks.map((block, i) =>
                      block.type === "header" ? (
                        <h2 key={i} className="text-[15px] font-semibold text-[var(--color-text)] mt-7 mb-2 leading-snug first:mt-0">
                          {block.text}
                        </h2>
                      ) : (
                        <p key={i} className="text-[14px] text-[var(--color-text-secondary)] leading-[2] mb-4 last:mb-0">
                          {block.text}
                        </p>
                      )
                    )}
                  </div>
                ) : (
                  /* 摘要模式：MarkdownRenderer 渲染 */
                  <MarkdownRenderer>{guide.content}</MarkdownRenderer>
                )
              ) : (
                <p className="text-xs text-[var(--color-text-secondary)]">暂无内容</p>
              )}
            </div>
          </article>
        )}
      </div>
    </div>
  );
}
