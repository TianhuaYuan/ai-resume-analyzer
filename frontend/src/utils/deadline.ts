/**
 * 截止日期分级着色（复制自 Job tools/recruit.py deadlineInfo，L523-530）。
 *
 * 原始逻辑：diff<=3 红 / <=7 黄 / <0 深红"已过期" / 否则绿。
 * 本项目同时消费后端 is_expired 字段（更可靠），本地 diff 作兜底。
 */

export type DeadlineTone = "expired" | "urgent" | "soon" | "normal" | "none";

export interface DeadlineInfo {
  tone: DeadlineTone;
  text: string;
  className: string;
}

/** 日期字符串 → 距离今天的天数差（deadline - today，负数为已过期） */
export function daysUntil(deadline: string): number {
  const d = new Date(deadline);
  if (Number.isNaN(d.getTime())) return Number.NaN;
  const now = new Date();
  // 按自然日对齐：以本地零点计算
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const target = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  return Math.round((target.getTime() - today.getTime()) / 86_400_000);
}

export function deadlineInfo(
  deadline: string | null | undefined,
  isExpired?: boolean
): DeadlineInfo {
  if (!deadline) {
    return { tone: "none", text: "—", className: "text-[var(--color-text-muted)]" };
  }
  const diff = daysUntil(deadline);
  // 后端 is_expired 标记或本地负天数 → 已过期
  if (isExpired || (Number.isFinite(diff) && diff < 0)) {
    return {
      tone: "expired",
      text: `已过期 ${deadline.slice(0, 10)}`,
      className: "text-red-500 font-medium",
    };
  }
  if (Number.isFinite(diff) && diff <= 3) {
    return { tone: "urgent", text: `还剩 ${diff} 天`, className: "text-red-400 font-medium" };
  }
  if (Number.isFinite(diff) && diff <= 7) {
    return { tone: "soon", text: `还剩 ${diff} 天`, className: "text-amber-400 font-medium" };
  }
  return { tone: "normal", text: deadline.slice(0, 10), className: "text-emerald-500" };
}
