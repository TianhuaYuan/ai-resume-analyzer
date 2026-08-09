/**
 * FeedbackPage — 用户反馈页。
 *
 * - 所有登录用户可查看公开反馈列表
 * - 点击"反馈建议"弹出表单，提交后立即刷新列表
 * - 点赞/取消点赞
 */

import { useEffect, useState, useCallback } from "react";
import { Plus, Archive, X, LoaderCircle, ThumbsUp, CalendarDays, User } from "lucide-react";
import { useToast } from "../components/Toast";
import PageHeaderProvider, { usePageHeader } from "../components/PageHeaderProvider";
import {
  submitFeedback,
  listPublicFeedback,
  toggleFeedbackLike,
  FEEDBACK_TYPES,
  type PublicFeedbackItem,
} from "../api/feedback";

// ── 反馈类型标签颜色 ──
const TYPE_STYLES: Record<string, string> = {
  bug: "bg-danger/10 text-danger border-danger/20",
  feature: "bg-brand/10 text-brand border-brand/20",
  ux: "bg-success/10 text-success border-success/20",
  other: "bg-zinc-500/10 text-zinc-600 border-zinc-500/20",
};

// ── 状态标签 ──
const STATUS_STYLES: Record<string, string> = {
  open: "bg-blue-500/10 text-blue-600",
  adopted: "bg-brand/10 text-brand",
  resolved: "bg-success/10 text-success",
  closed: "bg-zinc-500/10 text-zinc-600",
};

const STATUS_LABELS: Record<string, string> = {
  open: "进行中",
  adopted: "已采纳",
  resolved: "已完成",
  closed: "已关闭",
};

function getTypeLabel(value: string): string {
  return FEEDBACK_TYPES.find((t) => t.value === value)?.label ?? value;
}

function formatTimestamp(dateStr?: string): string {
  if (!dateStr) return "-";
  const normalized = /[Z+]/.test(dateStr) ? dateStr : dateStr + "Z";
  const d = new Date(normalized);
  if (isNaN(d.getTime())) return "-";
  return d.toLocaleDateString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit" });
}

// ── 主组件 ──

/**
 * FeedbackPageHeader — 通过 PageHeaderProvider 槽位注入页头内容（P4-34 示范）。
 * - setTitle 可覆盖默认标题
 * - setEnd 注入右侧"反馈建议"按钮
 * 卸载时清空槽位（恢复默认页头），避免页面切换串扰。
 */
function FeedbackPageHeader({ onOpenDialog }: { onOpenDialog: () => void }) {
  const { setEnd } = usePageHeader();

  useEffect(() => {
    setEnd(
      <button
        type="button"
        onClick={onOpenDialog}
        className="inline-flex items-center gap-2 px-4 py-2 rounded-full text-sm font-medium
          bg-brand text-white hover:bg-brand-hover
          hover:scale-[1.02] active:scale-[0.98] motion-reduce:active:scale-100
          transition-all duration-300 cursor-pointer shadow-sm shadow-brand/25"
      >
        <Plus size={16} strokeWidth={2.25} aria-hidden="true" />
        反馈建议
      </button>,
    );
    return () => setEnd(null); // 卸载清空槽位
  }, [setEnd, onOpenDialog]);

  return null;
}

export default function FeedbackPage() {
  const toast = useToast();

  // 弹窗状态
  const [dialogOpen, setDialogOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [feedbackType, setFeedbackType] = useState("feature");
  const [content, setContent] = useState("");
  const [title, setTitle] = useState("");

  // 列表状态
  const [items, setItems] = useState<PublicFeedbackItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);

  // 点赞中的 id（防止重复点击）
  const [likingId, setLikingId] = useState<number | null>(null);

  // 加载反馈列表
  const fetchList = useCallback(() => {
    setLoading(true);
    listPublicFeedback(50, 0)
      .then((data) => {
        setItems(data.items);
        setTotal(data.total);
      })
      .catch(() => {
        setItems([]);
        setTotal(0);
      })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { fetchList(); }, [fetchList]);

  // 提交反馈
  const handleSubmit = async () => {
    const trimmedContent = content.trim();
    if (!trimmedContent) {
      toast.error("请输入反馈内容", { title: "内容为空" });
      return;
    }
    setSubmitting(true);
    try {
      const fullContent = title.trim()
        ? `${title.trim()}\n\n${trimmedContent}`
        : trimmedContent;
      await submitFeedback(fullContent, feedbackType);
      toast.success("反馈已提交，感谢你的建议！", { title: "提交成功" });
      setDialogOpen(false);
      setContent("");
      setTitle("");
      setFeedbackType("feature");
      fetchList();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "提交失败，请稍后重试";
      toast.error(msg, { title: "提交失败" });
    } finally {
      setSubmitting(false);
    }
  };

  // 点赞
  const handleLike = async (fbId: number) => {
    if (likingId) return;
    setLikingId(fbId);
    try {
      const result = await toggleFeedbackLike(fbId);
      setItems((prev) =>
        prev.map((item) =>
          item.id === fbId
            ? { ...item, likes_count: result.likes_count, is_liked: result.is_liked }
            : item
        )
      );
    } catch {
      // 静默失败
    } finally {
      setLikingId(null);
    }
  };

  return (
    <PageHeaderProvider title="用户反馈" subtitle="用的不爽？跟产品负责人一吐为快！">
      <FeedbackPageHeader onOpenDialog={() => setDialogOpen(true)} />
      <div className="flex-1 overflow-y-auto">
        <div className="max-w-6xl mx-auto w-full px-6 py-6 flex flex-col flex-1 min-h-0">

        {/* 反馈列表 */}
        {loading ? (
          <div className="flex-1 flex flex-col items-center justify-center text-center">
            <LoaderCircle size={24} className="animate-spin text-brand mb-3" />
            <p className="text-xs text-[var(--color-text-muted)]">加载中...</p>
          </div>
        ) : items.length === 0 ? (
          <div className="flex-1 flex flex-col items-center justify-center text-center">
            <div className="w-14 h-14 rounded-input bg-[var(--color-bg-secondary)] border border-[var(--color-border)]
              flex items-center justify-center text-[var(--color-text-muted)] mb-4">
              <Archive size={26} fill="currentColor" aria-hidden="true" />
            </div>
            <h2 className="text-base font-semibold text-[var(--color-text)] mb-1.5">暂无反馈</h2>
            <p className="text-sm text-[var(--color-text-muted)] text-center max-w-sm">
              还没有收到反馈，点击右上角「反馈建议」提交你的想法吧。
            </p>
          </div>
        ) : (
          <div className="flex-1 overflow-y-auto">
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {items.map((item) => (
                <div
                  key={item.id}
                  className="glass-card p-5 flex flex-col
                    hover:-translate-y-1 hover:shadow-xl hover:shadow-black/5 transition-all duration-300"
                >
                  {/* 标题行：类型 + 状态 */}
                  <div className="flex items-center justify-between gap-2 mb-2">
                    <span className={`inline-flex px-2 py-0.5 rounded text-[10px] font-medium border ${TYPE_STYLES[item.type] ?? TYPE_STYLES.other}`}>
                      {getTypeLabel(item.type)}
                    </span>
                    {item.status !== "open" && (
                      <span className={`text-[10px] px-2 py-0.5 rounded-full font-medium ${STATUS_STYLES[item.status] ?? STATUS_STYLES.open}`}>
                        {STATUS_LABELS[item.status] ?? item.status}
                      </span>
                    )}
                  </div>

                  {/* 内容 */}
                  <p className="text-sm text-[var(--color-text)] leading-relaxed mb-4 flex-1 line-clamp-4">
                    {item.content}
                  </p>

                  {/* 底部：用户名 + 日期 + 点赞 */}
                  <div className="flex items-center justify-between pt-3 border-t border-[var(--color-border)]">
                    <div className="flex items-center gap-3 text-[10px] text-[var(--color-text-muted)]">
                      <span className="inline-flex items-center gap-1">
                        <CalendarDays size={10} fill="currentColor" />
                        {formatTimestamp(item.created_at)}
                      </span>
                      <span className="inline-flex items-center gap-1">
                        <User size={10} fill="currentColor" />
                        {item.user_display}
                      </span>
                    </div>
                    <button
                      onClick={() => handleLike(item.id)}
                      disabled={likingId === item.id}
                      className={`inline-flex items-center gap-1 text-[10px] px-2 py-1 rounded-full transition-all cursor-pointer
                        ${item.is_liked
                          ? "text-brand bg-brand/10"
                          : "text-[var(--color-text-muted)] hover:text-brand hover:bg-brand/10"
                        }
                        disabled:opacity-40`}
                    >
                      <ThumbsUp size={11} fill={item.is_liked ? "currentColor" : "none"} />
                      <span className="tabular-nums">{item.likes_count}</span>
                    </button>
                  </div>
                </div>
              ))}
            </div>
            {total > items.length && (
              <p className="text-center text-xs text-[var(--color-text-muted)] mt-4">
                显示 {items.length}/{total} 条
              </p>
            )}
          </div>
        )}

        {/* ── 反馈弹窗 ── */}
        {dialogOpen && (
          <div
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm motion-reduce:backdrop-blur-none"
            role="dialog"
            aria-modal="true"
            aria-label="提交反馈"
          >
            <div className="glass-card w-full max-w-lg mx-4 shadow-2xl animate-fade-in-up">
              <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--color-border)]">
                <h3 className="text-base font-semibold text-[var(--color-text)]">反馈建议</h3>
                <button onClick={() => setDialogOpen(false)} aria-label="关闭"
                  className="p-1.5 rounded-action text-[var(--color-text-secondary)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-secondary)] transition-all cursor-pointer">
                  <X size={18} strokeWidth={2.25} />
                </button>
              </div>

              <div className="px-6 py-5 space-y-4">
                <div>
                  <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">反馈类型</label>
                  <div className="flex items-center gap-2 flex-wrap">
                    {FEEDBACK_TYPES.map((t) => (
                      <button key={t.value} type="button" onClick={() => setFeedbackType(t.value)}
                        className={`px-3 py-1.5 rounded-full text-xs font-medium border transition-all cursor-pointer
                          ${feedbackType === t.value
                            ? "bg-brand/10 border-brand/30 text-brand"
                            : "border-[var(--color-border)] text-[var(--color-text-muted)] hover:border-brand/30"
                          }`}>
                        {t.label}
                      </button>
                    ))}
                  </div>
                </div>

                <div>
                  <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">
                    标题（可选）
                  </label>
                  <input type="text" value={title} onChange={(e) => setTitle(e.target.value)}
                    placeholder="一句话概括你的反馈"
                    className="w-full px-3 py-2 rounded-list bg-[#F2F2F7] border border-transparent
                      text-sm text-[var(--color-text)] placeholder:text-[var(--color-text-muted)]
                      focus:outline-none focus:bg-white focus:border-brand/40 focus:ring-4 focus:ring-brand/15 transition-colors" />
                </div>

                <div>
                  <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">
                    详细描述 <span className="text-danger">*</span>
                  </label>
                  <textarea value={content} onChange={(e) => setContent(e.target.value)}
                    placeholder="请详细描述你的问题或建议..." rows={5} maxLength={2000}
                    className="w-full px-3 py-2 rounded-list bg-[#F2F2F7] border border-transparent
                      text-sm text-[var(--color-text)] placeholder:text-[var(--color-text-muted)]
                      focus:outline-none focus:bg-white focus:border-brand/40 focus:ring-4 focus:ring-brand/15 transition-colors resize-none" />
                  <p className="text-[10px] text-[var(--color-text-muted)] mt-1 text-right">{content.length}/2000</p>
                </div>
              </div>

              <div className="flex items-center justify-end gap-2 px-6 py-4 border-t border-[var(--color-border)]">
                <button onClick={() => setDialogOpen(false)}
                  className="px-4 py-2 rounded-full bg-[var(--color-bg-secondary)]
                    text-xs text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-secondary)] transition-all cursor-pointer">
                  取消
                </button>
                <button onClick={handleSubmit} disabled={submitting || !content.trim()}
                  className="px-4 py-2 rounded-full bg-brand text-white text-xs font-medium
                    hover:bg-brand-hover hover:scale-[1.02] active:scale-[0.98] transition-all duration-300 cursor-pointer
                    disabled:opacity-40 disabled:cursor-not-allowed
                    inline-flex items-center gap-2">
                  {submitting && <LoaderCircle size={12} className="animate-spin" strokeWidth={2.25} />}
                  {submitting ? "提交中..." : "提交反馈"}
                </button>
              </div>
            </div>
          </div>
        )}
        </div>
      </div>
    </PageHeaderProvider>
  );
}
