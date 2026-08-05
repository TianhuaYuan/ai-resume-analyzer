import type { TemplateConfig } from "../registry";

/** 青绿时间轴 — 单栏时间轴 + 节点圆点，突出职业轨迹（Magic timeline-pro × RR azurill） */
export const timelineProConfig: TemplateConfig = {
  id: "timeline-pro",
  name: "青绿时间轴",
  description: "单栏时间轴 + 节点圆点，突出职业轨迹（Magic timeline-pro × RR azurill）",
  colorScheme: {
    primary: "#0d9488",
    secondary: "#0f766e",
    background: "#ffffff",
    text: "#0f172a",
  },
  spacing: {
    sectionGap: 15,
    itemGap: 8,
    contentPadding: 36,
  },
  basic: {
    layout: "left",
  },
};
