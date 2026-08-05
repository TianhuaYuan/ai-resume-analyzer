import type { TemplateConfig } from "../registry";

/** 技能聚焦 — 勃艮第强调 + 技能胶囊，成果导向（Magic skills-first） */
export const skillsFirstConfig: TemplateConfig = {
  id: "skills-first",
  name: "技能聚焦",
  description: "勃艮第强调 + 技能胶囊，成果导向（Magic skills-first）",
  colorScheme: {
    primary: "#9f1239",
    secondary: "#881337",
    background: "#ffffff",
    text: "#1f2937",
  },
  spacing: {
    sectionGap: 16,
    itemGap: 8,
    contentPadding: 38,
  },
  basic: {
    layout: "left",
  },
};
