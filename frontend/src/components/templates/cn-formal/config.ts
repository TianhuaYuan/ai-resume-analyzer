import type { TemplateConfig } from "../registry";

/** 中文正装 — 中文正式单栏，蓝色沉稳，适合国企/事业单位（Magic cn-formal-photo） */
export const cnFormalConfig: TemplateConfig = {
  id: "cn-formal",
  name: "中文正装",
  description: "中文正式单栏，蓝色沉稳，适合国企/事业单位（Magic cn-formal-photo）",
  colorScheme: {
    primary: "#1d4ed8",
    secondary: "#1e3a8a",
    background: "#ffffff",
    text: "#111827",
  },
  spacing: {
    sectionGap: 12,
    itemGap: 6,
    contentPadding: 30,
  },
  basic: {
    layout: "left",
  },
};
