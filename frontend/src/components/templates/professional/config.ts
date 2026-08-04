import type { TemplateConfig } from "../registry";

/** 专业双栏 — 左栏放基础/技能/语言/社交，右栏主内容（对齐后端 templates/professional.html） */
export const professionalConfig: TemplateConfig = {
  id: "professional",
  name: "专业",
  description: "专业双栏，技术简历首选",
  colorScheme: {
    primary: "#0ea5e9",
    secondary: "#64748b",
    background: "#f8fafc",
    text: "#1e293b",
  },
  spacing: {
    sectionGap: 14,
    itemGap: 10,
    contentPadding: 28,
  },
  basic: {
    layout: "left",
  },
};
