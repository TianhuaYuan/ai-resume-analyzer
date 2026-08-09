import type { HTMLAttributes } from "react";
import { twMerge } from "tailwind-merge";

interface SkeletonProps extends HTMLAttributes<HTMLDivElement> {
  /** 是否圆形（头像/图标占位） */
  circle?: boolean;
}

/**
 * Skeleton — 加载占位块（shimmer 微光扫过）。
 *
 * 复用全局 .animate-skeleton（background 渐变 + 1.5s 扫光）。
 * 尺寸由 className 控制（w-/h- 或 style），circle 用于圆形头像占位。
 */
export default function Skeleton({ className, circle = false, ...rest }: SkeletonProps) {
  return (
    <div
      aria-hidden="true"
      className={twMerge("animate-skeleton", circle ? "rounded-full" : "rounded-lg", className)}
      {...rest}
    />
  );
}
