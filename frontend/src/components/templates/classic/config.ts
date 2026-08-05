import type { TemplateConfig } from "../registry";

/** 经典衬线 — 衬线经典排版，学术/正式岗位首选（Magic classic） */
export const classicConfig: TemplateConfig = {
  id: "classic",
  name: "经典衬线",
  description: "衬线经典排版，学术/正式岗位首选（Magic classic）",
  colorScheme: {
    primary: "#3b82f6",
    secondary: "#333333",
    background: "#ffffff",
    text: "#000000",
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
