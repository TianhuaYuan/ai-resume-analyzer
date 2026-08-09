import type { ReactNode } from "react";
import { twMerge } from "tailwind-merge";

export type BadgeVariant = "brand" | "success" | "warning" | "danger" | "neutral";

interface BadgeProps {
  variant?: BadgeVariant;
  children: ReactNode;
  className?: string;
  /** 前置小圆点（状态指示灯） */
  dot?: boolean;
}

const VARIANT_CLASSES: Record<BadgeVariant, string> = {
  brand: "bg-brand/10 text-brand",
  success: "bg-success-soft text-success",
  warning: "bg-warning-soft text-warning",
  danger: "bg-danger-soft text-danger",
  neutral: "bg-[var(--color-bg-secondary)] text-[var(--color-text-secondary)]",
};

const DOT_COLORS: Record<BadgeVariant, string> = {
  brand: "bg-brand",
  success: "bg-success",
  warning: "bg-warning",
  danger: "bg-danger",
  neutral: "bg-[var(--color-text-muted)]",
};

/**
 * Badge — 状态/标签胶囊（Apple 风格浅色底 + 语义色文字）。
 *
 * variant 用浅色 alpha 底，深色主题下仍可读；dot 显示前置状态指示灯。
 */
export default function Badge({ variant = "brand", children, className, dot = false }: BadgeProps) {
  return (
    <span
      className={twMerge(
        "inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium whitespace-nowrap",
        VARIANT_CLASSES[variant],
        className,
      )}
    >
      {dot && <span className={twMerge("w-1.5 h-1.5 rounded-full", DOT_COLORS[variant])} aria-hidden="true" />}
      {children}
    </span>
  );
}
