import type { TemplateConfig } from "../registry";

/** 活力橙双栏 — 橙色侧栏双栏，活泼自信（Magic orange-modern × RR pikachu） */
export const orangeConfig: TemplateConfig = {
  id: "orange",
  name: "活力橙双栏",
  description: "橙色侧栏双栏，活泼自信（Magic orange-modern × RR pikachu）",
  colorScheme: {
    primary: "#f97316",
    secondary: "#ea580c",
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
