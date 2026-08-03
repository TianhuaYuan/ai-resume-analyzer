import type { TemplateConfig } from "../../registry";

/** 极简 — 无装饰线，紧凑留白（对齐后端 templates/minimal.html） */
export const minimalConfig: TemplateConfig = {
  id: "minimal",
  name: "极简",
  description: "极简风，去除多余装饰线，紧凑留白",
  colorScheme: {
    primary: "#334155",
    secondary: "#94a3b8",
    background: "#ffffff",
    text: "#1e293b",
  },
  spacing: {
    sectionGap: 10,
    itemGap: 8,
    contentPadding: 24,
  },
  basic: {
    layout: "left",
  },
};
