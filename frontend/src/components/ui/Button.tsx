import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import { twMerge } from "tailwind-merge";
import Spinner from "./Spinner";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
export type ButtonSize = "xs" | "sm" | "md" | "lg";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  /** 视觉变体（默认 primary） */
  variant?: ButtonVariant;
  /** 尺寸（默认 md） */
  size?: ButtonSize;
  /** 是否显示加载态（禁用交互 + 内置 spinner） */
  loading?: boolean;
  /** 前置图标 */
  icon?: ReactNode;
  /** 后置图标 */
  iconRight?: ReactNode;
  /** 是否胶囊圆角（默认 true，false 时用 Squircle 圆角） */
  pill?: boolean;
}

const VARIANT_CLASSES: Record<ButtonVariant, string> = {
  // 品牌蓝实心：用 CSS 变量适配浅/深主题，hover 用 brightness 保持色相
  // shadow-brand/25：brand 是 @theme token，双主题下与 --color-primary 同值
  primary: "bg-[var(--color-primary)] text-white hover:brightness-110 hover:shadow-lg hover:shadow-brand/25",
  // 浅灰实心（禁止透明底）：CSS 变量自动适配双主题
  secondary:
    "bg-[var(--color-bg-secondary)] text-[var(--color-text)] hover:bg-[var(--color-bg-tertiary)] border border-transparent",
  // 无底幽灵：hover 出浅灰底
  ghost:
    "text-[var(--color-text-secondary)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-secondary)]",
  // 危险：浅红底 + 红字（语义 token）
  danger: "bg-danger-soft text-danger hover:bg-danger/25 border border-danger/30",
};

const SIZE_CLASSES: Record<ButtonSize, string> = {
  xs: "px-2 py-1 text-xs rounded-action gap-1",
  sm: "px-3 py-1.5 text-sm rounded-list gap-1.5",
  md: "px-4 py-2 text-sm rounded-full gap-1.5",
  lg: "px-8 py-3.5 text-base rounded-full gap-2",
};

/**
 * Button — 全站统一按钮组件。
 *
 * 吸收 mono-btn-* 工具类经验 + Open WebUI 的变体系统：
 * - 变体用 CSS 变量驱动，自动适配 [data-theme="dark"]
 * - 统一物理动效（hover 微放大 / active 微缩），motion-reduce 时禁用
 * - 内置 loading 态（spinner + 禁用），icon 插槽支持图标按钮
 */
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  {
    variant = "primary",
    size = "md",
    loading = false,
    disabled,
    icon,
    iconRight,
    pill = true,
    className,
    type = "button",
    children,
    ...rest
  },
  ref,
) {
  const isDisabled = disabled || loading;

  return (
    <button
      ref={ref}
      type={type}
      disabled={isDisabled}
      aria-busy={loading || undefined}
      className={twMerge(
        "inline-flex items-center justify-center font-medium whitespace-nowrap",
        "cursor-pointer select-none transition-all duration-300",
        "hover:scale-[1.02] active:scale-[0.98]",
        "motion-reduce:hover:scale-100 motion-reduce:active:scale-100",
        "disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:scale-100 disabled:active:scale-100",
        "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand/40",
        pill ? "" : "rounded-input",
        VARIANT_CLASSES[variant],
        SIZE_CLASSES[size],
        className,
      )}
      {...rest}
    >
      {loading && <Spinner size={14} className="text-current" />}
      {!loading && icon}
      {children}
      {iconRight}
    </button>
  );
});

export default Button;
