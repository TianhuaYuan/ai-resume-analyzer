import type { TemplateConfig } from "../registry";

/** 琥珀深侧栏 — 琥珀强调 + 深灰侧栏，优雅高端（Magic golden-elegant） */
export const goldenElegantConfig: TemplateConfig = {
  id: "golden-elegant",
  name: "琥珀深侧栏",
  description: "琥珀强调 + 深灰侧栏，优雅高端（Magic golden-elegant）",
  colorScheme: {
    primary: "#d97706",
    secondary: "#f59e0b",
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
