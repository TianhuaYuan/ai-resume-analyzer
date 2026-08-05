import type { TemplateConfig } from "../registry";

/** 深蓝侧栏 — 深蓝侧栏 + 主栏时间轴，现代专业（Magic azurill × RR azurill） */
export const azurillConfig: TemplateConfig = {
  id: "azurill",
  name: "深蓝侧栏",
  description: "深蓝侧栏 + 主栏时间轴，现代专业（Magic azurill × RR azurill）",
  colorScheme: {
    primary: "#1e40af",
    secondary: "#3b82f6",
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
