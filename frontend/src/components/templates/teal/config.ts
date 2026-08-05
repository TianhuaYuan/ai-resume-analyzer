import type { TemplateConfig } from "../registry";

/** 青绿侧栏 — 青绿侧栏 + 清爽主栏，技术岗清新风（Magic teal-professional × RR chikorita） */
export const tealConfig: TemplateConfig = {
  id: "teal",
  name: "青绿侧栏",
  description: "青绿侧栏 + 清爽主栏，技术岗清新风（Magic teal-professional × RR chikorita）",
  colorScheme: {
    primary: "#0d9488",
    secondary: "#14b8a6",
    background: "#ffffff",
    text: "#1f2937",
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
