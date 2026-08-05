import type { TemplateConfig } from "../registry";

/** 衬线留白 — 衬线字体 + 大留白，Premium 质感，ATS 友好（Magic serif-minimal × RR scizor） */
export const serifConfig: TemplateConfig = {
  id: "serif",
  name: "衬线留白",
  description: "衬线字体 + 大留白，Premium 质感，ATS 友好（Magic serif-minimal × RR scizor）",
  colorScheme: {
    primary: "#1f2937",
    secondary: "#374151",
    background: "#ffffff",
    text: "#111827",
  },
  spacing: {
    sectionGap: 22,
    itemGap: 8,
    contentPadding: 52,
  },
  basic: {
    layout: "left",
  },
};
