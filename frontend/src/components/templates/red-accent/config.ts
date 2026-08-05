import type { TemplateConfig } from "../registry";

/** 红色强调 — 红色强调线 + 干净单栏，醒目现代（Magic red-accent） */
export const redAccentConfig: TemplateConfig = {
  id: "red-accent",
  name: "红色强调",
  description: "红色强调线 + 干净单栏，醒目现代（Magic red-accent）",
  colorScheme: {
    primary: "#dc2626",
    secondary: "#374151",
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
