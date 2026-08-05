import type { TemplateConfig } from "../registry";

/** 深板岩侧栏 — 深灰侧栏 + 蓝色强调 + 主栏时间轴，沉稳技术风（Magic slate-sidebar × RR gengar） */
export const slateConfig: TemplateConfig = {
  id: "slate",
  name: "深板岩侧栏",
  description: "深灰侧栏 + 蓝色强调 + 主栏时间轴，沉稳技术风（Magic slate-sidebar × RR gengar）",
  colorScheme: {
    primary: "#0ea5e9",
    secondary: "#0284c7",
    background: "#ffffff",
    text: "#0f172a",
  },
  spacing: {
    sectionGap: 18,
    itemGap: 8,
    contentPadding: 28,
  },
  basic: {
    layout: "left",
  },
};
