import { ArrowRightLeft, Search, Trash2, X } from "lucide-react";
import type { ResumeItem } from "../../api/resumes";
import type { QuotaResponse } from "../../api/qa";

interface ChatNavbarProps {
  /** 是否已滚动离开顶部（控制渐变背景） */
  scrolled: boolean;
  resumeId: number;
  resumeOptions: ResumeItem[];
  resume: ResumeItem | null;
  onSwitchResume: (id: number) => void;
  /** 当前对话名（顶栏标题下方小字） */
  conversationTitle?: string;
  compareCount: number;
  onCompareClick: () => void;
  quota: QuotaResponse | null;
  keyword: string;
  onKeywordChange: (v: string) => void;
  onClearKeyword: () => void;
  searchDisabled: boolean;
  chatCount: number;
  clearing: boolean;
  asking: boolean;
  onClearHistory: () => void;
  /** 是否有简历模块可预览（控制预览 toggle 显示） */
  canPreview: boolean;
  showPreview: boolean;
  onTogglePreview: () => void;
}

/**
 * ChatNavbar — QA 页顶栏（Open WebUI Navbar 风格）。
 *
 * sticky top-0 + 滚动渐变背景（scrolled 时毛玻璃 border-b，未滚动透明），
 * 左侧简历切换（标题主体）+ 对话名小字；右侧操作栏（对比/额度/搜索/清除/预览）。
 */
export default function ChatNavbar({
  scrolled,
  resumeId,
  resumeOptions,
  resume,
  onSwitchResume,
  conversationTitle,
  compareCount,
  onCompareClick,
  quota,
  keyword,
  onKeywordChange,
  onClearKeyword,
  searchDisabled,
  chatCount,
  clearing,
  asking,
  onClearHistory,
  canPreview,
  showPreview,
  onTogglePreview,
}: ChatNavbarProps) {
  return (
    <div
      className={`shrink-0 z-30 sticky top-0 px-4 sm:px-6 py-3 border-b transition-colors duration-200 ${
        scrolled
          ? "bg-[var(--color-bg)]/90 backdrop-blur-xl border-[var(--color-border)]"
          : "bg-transparent border-transparent"
      }`}
    >
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="min-w-0 flex-1">
          {/* 简历切换下拉（多简历时切换会话/对话；对话按简历隔离） */}
          <select
            value={resumeId || ""}
            onChange={(e) => onSwitchResume(Number(e.target.value))}
            className="max-w-[280px] text-base font-semibold text-[var(--color-text)] truncate
              bg-transparent border border-transparent rounded-md px-1 py-0.5
              hover:border-[var(--color-border)] focus:border-brand/40 focus:outline-none
              cursor-pointer"
            aria-label="切换简历"
            title="切换简历（对话按简历隔离）"
          >
            {resumeOptions.length === 0 && (
              <option value="">{resume?.filename ?? "加载中..."}</option>
            )}
            {resumeOptions.map((r) => (
              <option key={r.id} value={r.id}>
                {r.filename}
              </option>
            ))}
          </select>

          {conversationTitle && (
            <div className="mt-0.5">
              <span className="text-[11px] text-[var(--color-text-muted)]">{conversationTitle}</span>
            </div>
          )}
        </div>

        {/* 对比已选指示器 */}
        {compareCount > 0 && (
          <button
            onClick={onCompareClick}
            className="shrink-0 inline-flex items-center gap-1 px-2 py-1 rounded-md
              text-[10px] bg-brand/10 text-brand border border-brand/20 hover:bg-brand/15 cursor-pointer"
            title="重新打开对比选择"
          >
            <ArrowRightLeft size={10} strokeWidth={2.25} aria-hidden="true" />
            已选 {compareCount} 份对比
          </button>
        )}

        {/* Token 限额显示 */}
        {quota?.enabled && (
          <div className="shrink-0 px-3 py-1.5 rounded-action text-xs
            bg-[var(--color-bg-secondary)] border border-[var(--color-border)]
            flex items-center gap-2">
            <span className="text-[var(--color-text-muted)]">今日额度</span>
            <span className={`font-mono tabular-nums ${
              quota.remaining < quota.limit * 0.1
                ? "text-danger"
                : quota.remaining < quota.limit * 0.3
                ? "text-warning"
                : "text-brand"
            }`}>
              {quota.used}/{quota.limit}
            </span>
            {quota.remaining < quota.limit * 0.1 && (
              <span className="text-danger text-[10px]">额度不足</span>
            )}
          </div>
        )}

        {/* 搜索框 */}
        <div className="relative shrink-0">
          <Search
            size={14}
            strokeWidth={2.25}
            aria-hidden="true"
            className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--color-text-muted)] pointer-events-none"
          />
          <input
            type="text"
            value={keyword}
            onChange={(e) => onKeywordChange(e.target.value)}
            placeholder="搜索问答"
            disabled={searchDisabled}
            className="w-40 sm:w-56 pl-8 pr-8 py-1.5 rounded-list text-xs text-[var(--color-text)]
              bg-[var(--color-bg-secondary)] border border-transparent
              placeholder:text-[var(--color-text-muted)]
              focus:outline-none focus:ring-2 focus:ring-brand/40
              focus:border-brand/50 focus:bg-white
              disabled:opacity-50 transition-all duration-200"
          />
          {keyword && (
            <button
              onClick={onClearKeyword}
              aria-label="清除搜索"
              className="absolute right-2 top-1/2 -translate-y-1/2 p-0.5 rounded
                text-[var(--color-text-muted)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-secondary)]
                active:scale-[0.95] motion-reduce:active:scale-100
                transition-all cursor-pointer"
            >
              <X size={12} strokeWidth={2.25} aria-hidden="true" />
            </button>
          )}
        </div>

        {/* 清除历史 */}
        <button
          onClick={onClearHistory}
          disabled={chatCount === 0 || clearing || asking}
          className="shrink-0 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full
            text-xs font-medium border border-[var(--color-border)] text-[var(--color-text-secondary)]
            hover:text-danger hover:border-danger/30 hover:bg-danger/10
            active:scale-[0.98] motion-reduce:active:scale-100
            transition-all duration-300 cursor-pointer
            disabled:opacity-40 disabled:cursor-not-allowed"
        >
          <Trash2 size={14} aria-hidden="true" />
          清除历史
        </button>

        {/* 预览 toggle（抽屉入口） */}
        {canPreview && (
          <button
            onClick={onTogglePreview}
            className={`shrink-0 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full
              text-xs font-medium border transition-all duration-300 cursor-pointer ${
              showPreview
                ? "border-brand/30 bg-brand/10 text-brand"
                : "border-[var(--color-border)] text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-secondary)]"
            }`}
            title={showPreview ? "关闭预览" : "打开简历预览"}
          >
            📄 {showPreview ? "关闭预览" : "预览简历"}
          </button>
        )}
      </div>
    </div>
  );
}
