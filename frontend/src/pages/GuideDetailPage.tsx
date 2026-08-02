/**
 * GuideDetailPage — 求职攻略详情页（站内阅读）。
 *
 * 数据来自市场数据接口：/api/v1/market/guides/{id}
 * - 标题 + 日期 + 正文（content 用 MarkdownRenderer 渲染）
 * - 正文未抓取时 content 即摘要（has_fulltext=false），展示摘要 + "阅读原文"外链按钮
 * - 返回按钮回到攻略列表
 */

import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  BookOpen,
  CalendarBlank,
  ArrowSquareOut,
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
            <div className="mb-4">
              <div className="flex items-center gap-2">
                {guide.has_fulltext ? (
                  <span className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-medium border border-emerald-500/20 bg-emerald-500/10 text-emerald-600">
                    站内全文
                  </span>
                ) : (
                  <span className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-medium border border-amber-500/20 bg-amber-500/10 text-amber-600">
                    原文待收录
                  </span>
                )}
              </div>
              <h1 className="text-lg font-bold text-[var(--color-text)] display-tight leading-snug mt-2 mb-2">
                {guide.title}
              </h1>
              <div className="flex items-center gap-3 text-[10px] text-[var(--color-text-muted)]">
                <span className="inline-flex items-center gap-1">
                  <CalendarBlank size={11} weight="duotone" /> {formatDate(guide.date)}
                </span>
                <span>来源：公开渠道求职攻略</span>
              </div>
            </div>

            {/* 正文 */}
            <div className="border-t border-[var(--color-border)] pt-4">
              {guide.content ? (
                <MarkdownRenderer>{guide.content}</MarkdownRenderer>
              ) : (
                <p className="text-xs text-[var(--color-text-secondary)]">暂无内容</p>
              )}
            </div>

            {/* 原文外链 */}
            {guide.url && (
              <div className="flex items-center justify-between gap-3 border-t border-[var(--color-border)] pt-4 mt-6">
                <p className="text-[10px] text-[var(--color-text-muted)]">
                  {guide.has_fulltext
                    ? "全文由系统收录，如需查看原始出处可点击右侧按钮"
                    : "正文暂未收录，以下为摘要，可前往原文链接阅读完整攻略"}
                </p>
                <a href={guide.url} target="_blank" rel="noopener noreferrer"
                  className="inline-flex items-center gap-1.5 px-4 py-1.5 rounded-full bg-brand text-white text-xs font-medium hover:bg-[#0077ed] hover:scale-[1.02] active:scale-[0.98] transition-all duration-300 cursor-pointer shrink-0">
                  <ArrowSquareOut size={13} weight="bold" /> 阅读原文
                </a>
              </div>
            )}
          </article>
        )}
      </div>
    </div>
  );
}
