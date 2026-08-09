import { MessagesSquare } from "lucide-react";
import { GUIDE_CARDS, type GuideCard } from "./GuideCards";

interface WelcomeStateProps {
  searching: boolean;
  asking: boolean;
  onGuideClick: (card: GuideCard) => void;
  hasResume: boolean;
}

/**
 * WelcomeState — 聊天空状态/欢迎页。
 *
 * searching 时显示"没有匹配的问答"空搜索分支；
 * 否则显示不对称功能卡片网格（1 大卡跨 2 列 + 4 小卡）。
 * （M5 将在此升级为 Open WebUI 风格欢迎页：标题 + 内嵌输入 + 瀑布动画）
 */
export default function WelcomeState({
  searching,
  asking,
  onGuideClick,
  hasResume,
}: WelcomeStateProps) {
  if (searching) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center py-16">
        <div className="w-16 h-16 rounded-input bg-brand/10 border border-brand/15
          flex items-center justify-center text-brand mb-5">
          <MessagesSquare size={28} fill="currentColor" aria-hidden="true" />
        </div>
        <p className="text-base text-[var(--color-text-secondary)] mb-1.5">没有匹配的问答</p>
        <p className="text-sm text-[var(--color-text-muted)]">换个关键词试试</p>
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col items-center justify-center py-10 px-6">
      {/* 大字标题 + tagline（Open WebUI 欢迎页风格） */}
      <h2 className="welcome-item text-2xl sm:text-3xl font-semibold text-[var(--color-text)] text-center display-tight">
        简历 AI 助手
      </h2>
      <p className="welcome-item text-sm text-[var(--color-text-muted)] text-center mt-2 mb-8 max-w-lg leading-relaxed">
        从简历打磨到面试准备，陪你从简历到 Offer，每一步都不孤单。
      </p>

      {/* 不对称功能卡片网格：大卡跨 2 列 + 4 张小卡（瀑布动画，45ms 递增延迟） */}
      <div className="w-full max-w-3xl grid grid-cols-1 sm:grid-cols-3 gap-4">
        {GUIDE_CARDS.map((card, i) => {
          const Icon = card.icon;
          const isPrimary = !!card.primary;
          // 无简历时禁用需要简历的卡片，但"创建简历"卡片始终可点击
          const isCreateCard = card.label === "创建简历";
          const needsResume = Boolean(card.question) && !card.navigate && !isCreateCard;
          const disabled = asking || Boolean(needsResume && !hasResume);
          return (
            <button
              key={card.label}
              onClick={() => onGuideClick(card)}
              disabled={disabled}
              style={{ animationDelay: `${45 * i}ms` }}
              className={`welcome-item group flex items-center gap-3.5 p-4 rounded-input border text-left
                transition-all duration-300 cursor-pointer
                hover:-translate-y-1 hover:shadow-xl hover:shadow-black/5
                active:scale-[0.98] motion-reduce:active:scale-100
                disabled:opacity-40 disabled:cursor-not-allowed
                ${card.span ? "sm:col-span-2" : ""}
                ${isPrimary
                  ? "bg-brand/10 border-brand/15 hover:border-brand/30"
                  : "bg-white/80 border-[var(--color-border)] hover:border-brand/25"
                }`}
              aria-label={card.label}
            >
              <div className={`shrink-0 flex items-center justify-center
                ${isPrimary
                  ? "w-11 h-11 rounded-list bg-brand text-white shadow-sm shadow-brand/25"
                  : "w-10 h-10 rounded-[10px] bg-[var(--color-bg-secondary)] text-[var(--color-text-secondary)]"
                }`}>
                <Icon size={isPrimary ? 20 : 18} strokeWidth={2.25} aria-hidden="true" />
              </div>
              <div className="min-w-0">
                <p className={`text-sm font-semibold ${isPrimary ? "text-brand" : "text-[var(--color-text)]"}`}>
                  {card.label}
                </p>
                <p className="text-xs text-[var(--color-text-muted)] mt-0.5 truncate">
                  {card.description}
                </p>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}
