import type { ReactNode } from "react";
import { twMerge } from "tailwind-merge";

export type TooltipSide = "top" | "bottom" | "left" | "right";

interface TooltipProps {
  /** 提示文案 */
  label: string;
  /** 触发元素 */
  children: ReactNode;
  side?: TooltipSide;
  className?: string;
}

const SIDE_CLASSES: Record<TooltipSide, string> = {
  top: "bottom-full left-1/2 -translate-x-1/2 mb-2",
  bottom: "top-full left-1/2 -translate-x-1/2 mt-2",
  left: "right-full top-1/2 -translate-y-1/2 mr-2",
  right: "left-full top-1/2 -translate-y-1/2 ml-2",
};

/**
 * Tooltip — 轻量悬浮提示（纯 CSS，无依赖）。
 *
 * group-hover 显隐 + 淡入上移微动效，Apple 风格深色小气泡。
 * 键盘可达性由触发元素自身的 focus 承担。
 */
export default function Tooltip({ label, children, side = "top", className }: TooltipProps) {
  return (
    <span className={twMerge("group relative inline-flex", className)}>
      {children}
      <span
        role="tooltip"
        className={twMerge(
          "pointer-events-none absolute z-50",
          "whitespace-nowrap rounded-lg bg-[#1d1d1f]/90 text-white text-xs px-2.5 py-1.5",
          "opacity-0 scale-95 transition-all duration-150",
          "group-hover:opacity-100 group-hover:scale-100",
          "group-focus-within:opacity-100 group-focus-within:scale-100",
          "motion-reduce:transition-none",
          SIDE_CLASSES[side],
        )}
      >
        {label}
      </span>
    </span>
  );
}
