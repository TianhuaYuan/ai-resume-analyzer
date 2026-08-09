/**
 * 角色样式设计（借鉴 Hermes ROLE_STYLES）。
 *
 * 集中定义消息气泡/步骤的角色样式（bg/text/label），避免各组件内联重复。
 * 角色：user（用户）/ assistant（AI）/ system（系统提示）/ tool（工具）/ compaction（上下文摘要）
 */

export interface RoleStyle {
  /** 气泡/标签背景 */
  bg: string;
  /** 文本色 */
  text: string;
  /** 显示名 */
  label: string;
  /** 对齐方向 */
  align: "left" | "right";
}

export const ROLE_STYLES: Record<string, RoleStyle> = {
  user: {
    bg: "bg-brand",
    text: "text-white",
    label: "你",
    align: "right",
  },
  assistant: {
    bg: "bg-[var(--color-bg-secondary)] border border-[var(--color-border)]",
    text: "text-[var(--color-text)]",
    label: "AI",
    align: "left",
  },
  system: {
    bg: "bg-[var(--color-bg-secondary)] border border-[var(--color-border)]/60",
    text: "text-[var(--color-text-muted)] italic",
    label: "System",
    align: "left",
  },
  tool: {
    bg: "bg-[var(--color-bg-secondary)] border-l-2 border-brand/40",
    text: "text-[var(--color-text-secondary)] font-mono text-xs",
    label: "工具",
    align: "left",
  },
  compaction: {
    bg: "bg-[var(--color-bg-secondary)]/50 border border-dashed border-[var(--color-border)]",
    text: "text-[var(--color-text-muted)] italic",
    label: "上下文摘要",
    align: "left",
  },
};

/** 按角色名取样式（未知角色回退 assistant） */
export function getRoleStyle(role: string): RoleStyle {
  return ROLE_STYLES[role] ?? ROLE_STYLES.assistant;
}
