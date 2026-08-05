import type { TemplateConfig } from "../registry";

/** 中文紧凑 — 中文紧凑单栏，一页纸信息密度高（Magic compact-cn-photo） */
export const compactCnConfig: TemplateConfig = {
  id: "compact-cn",
  name: "中文紧凑",
  description: "中文紧凑单栏，一页纸信息密度高（Magic compact-cn-photo）",
  colorScheme: {
    primary: "#000000",
    secondary: "#000000",
    background: "#ffffff",
    text: "#000000",
  },
  spacing: {
    sectionGap: 8,
    itemGap: 4,
    contentPadding: 18,
  },
  basic: {
    layout: "left",
  },
};
