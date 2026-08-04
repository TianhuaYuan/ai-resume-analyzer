import type { TemplateConfig } from "../registry";

/** 优雅单栏 — 细线分隔，宽松字距（对齐后端 templates/elegant.html） */
export const elegantConfig: TemplateConfig = {
  id: "elegant",
  name: "优雅",
  description: "优雅单栏，细线分隔，留白充足",
  colorScheme: {
    primary: "#7c3aed",
    secondary: "#a78bfa",
    background: "#ffffff",
    text: "#1e293b",
  },
  spacing: {
    sectionGap: 18,
    itemGap: 12,
    contentPadding: 36,
  },
  basic: {
    layout: "center",
  },
};
