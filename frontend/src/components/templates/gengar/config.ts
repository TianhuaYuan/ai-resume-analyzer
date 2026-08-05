import type { TemplateConfig } from "../registry";

/** 暗夜紫 — 深色侧栏 + 暗底主栏，紫强调，先锋视觉（Magic gengar） */
export const gengarConfig: TemplateConfig = {
  id: "gengar",
  name: "暗夜紫",
  description: "深色侧栏 + 暗底主栏，紫强调，先锋视觉（Magic gengar）",
  colorScheme: {
    primary: "#8b5cf6",
    secondary: "#a855f7",
    background: "#111827",
    text: "#f9fafb",
  },
  spacing: {
    sectionGap: 16,
    itemGap: 8,
    contentPadding: 28,
  },
  basic: {
    layout: "left",
  },
};
