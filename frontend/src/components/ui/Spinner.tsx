import { twMerge } from "tailwind-merge";

interface SpinnerProps {
  /** 尺寸（px），默认 16 */
  size?: number;
  /** 附加类名（如颜色 text-brand / text-red-500） */
  className?: string;
  /** 无障碍标签 */
  label?: string;
}

/**
 * Spinner — 通用加载指示器（Apple 风格细圆环）。
 *
 * 保留 `.animate-spin` 类，与历史测试护栏（ConfirmDialog.test 查 .animate-spin）兼容。
 * 尺寸用 style 控制（px），颜色继承 currentColor，通过 className 覆盖。
 */
export default function Spinner({ size = 16, className, label = "加载中" }: SpinnerProps) {
  return (
    <span
      role="status"
      aria-label={label}
      className={twMerge("inline-block rounded-full border-2 border-current border-t-transparent animate-spin shrink-0", className)}
      style={{ width: size, height: size }}
    />
  );
}
