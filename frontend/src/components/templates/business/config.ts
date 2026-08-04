import type { TemplateConfig } from "../registry";

/** 商务 — 深色主题色标题，模块间细分隔线（对齐后端 templates/business.html） */
export const businessConfig: TemplateConfig = {
  id: "business",
  name: "商务",
  description: "商务稳重，主题色标题 + 细分隔线",
  colorScheme: {
    primary: "#1e3a8a",
    secondary: "#475569",
    background: "#ffffff",
    text: "#334155",
  },
  spacing: {
    sectionGap: 14,
    itemGap: 10,
    contentPadding: 32,
  },
  basic: {
    layout: "left",
  },
};
