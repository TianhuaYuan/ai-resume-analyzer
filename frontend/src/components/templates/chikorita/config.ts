import type { TemplateConfig } from "../registry";

/** 清新绿侧栏 — 清新绿侧栏 + 白底主栏，自然亲和（Magic chikorita） */
export const chikoritaConfig: TemplateConfig = {
  id: "chikorita",
  name: "清新绿侧栏",
  description: "清新绿侧栏 + 白底主栏，自然亲和（Magic chikorita）",
  colorScheme: {
    primary: "#22c55e",
    secondary: "#16a34a",
    background: "#ffffff",
    text: "#111827",
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
