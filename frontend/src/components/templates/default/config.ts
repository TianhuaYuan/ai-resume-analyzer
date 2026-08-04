import type { TemplateConfig } from "../registry";

/** 经典单栏 — 头部主题色分隔线（对齐后端 templates/default.html） */
export const defaultConfig: TemplateConfig = {
  id: "default",
  name: "经典",
  description: "经典单栏，头部主题色分隔线，通用性强",
  colorScheme: {
    primary: "#2563eb",
    secondary: "#64748b",
    background: "#ffffff",
    text: "#2d3748",
  },
  spacing: {
    sectionGap: 16,
    itemGap: 12,
    contentPadding: 32,
  },
  basic: {
    layout: "left",
  },
};
