import type { TemplateConfig } from "../registry";

/** 经典蓝 — 单栏百搭：左侧强调头 + 蓝色分割，通用性强（默认模板 + 兜底） */
export const defaultConfig: TemplateConfig = {
  id: "default",
  name: "经典蓝",
  description: "单栏百搭：左侧强调头 + 蓝色分割，通用性强（默认模板 + 兜底）",
  colorScheme: {
    primary: "#2563eb",
    secondary: "#64748b",
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
