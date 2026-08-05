/**
 * T31: 简历模板列表 — 前端静态配置。
 *
 * 与后端 templates/*.html 对齐（18 套）。模板由 scripts/generate-templates/generate.mjs
 * 从 tokens.json 生成，元信息集中在 generatedTemplateOptions.ts，此处只做透传。
 * 渲染由后端 TemplateRegistry 完成，此处仅提供模板选择器的展示元信息。
 */

import { GENERATED_TEMPLATE_OPTIONS } from "./generatedTemplateOptions";

export interface TemplateOption {
  id: string;
  name: string;
  description: string;
}

/** 18 套模板（与后端 templates/*.html 对齐，由生成器产出） */
export const TEMPLATE_OPTIONS: TemplateOption[] = [...GENERATED_TEMPLATE_OPTIONS];

/** 字体选项 */
export const FONT_OPTIONS = [
  { value: "Noto Sans CJK SC", label: "思源黑体" },
  { value: "Noto Serif CJK SC", label: "思源宋体" },
  { value: "Microsoft YaHei", label: "微软雅黑" },
  { value: "SimSun", label: "宋体" },
  { value: "sans-serif", label: "无衬线（系统默认）" },
];

/** 字号选项（更细档位，供 StylePanel 排版精细调参） */
export const FONT_SIZE_OPTIONS = [
  { value: "12px", label: "小 (12px)" },
  { value: "13px", label: "13px" },
  { value: "14px", label: "中 (14px)" },
  { value: "15px", label: "15px" },
  { value: "16px", label: "大 (16px)" },
  { value: "18px", label: "特大 (18px)" },
];

/** 行高选项 */
export const LINE_HEIGHT_OPTIONS = [
  { value: 1.4, label: "紧凑" },
  { value: 1.6, label: "标准" },
  { value: 1.8, label: "宽松" },
  { value: 2.0, label: "舒适" },
];

/** 间距选项 */
export const SPACING_OPTIONS = [
  { value: "4px", label: "紧凑" },
  { value: "8px", label: "标准" },
  { value: "12px", label: "宽松" },
  { value: "16px", label: "大间距" },
];

/**
 * 预设主题色（12 色）。
 *
 * 借鉴 Magic Resume THEME_COLORS：黑白灰梯度（#000~#999）+ 经典色
 * （宝蓝 #0047AB / 深红 #8B0000 / 橙红 #FF4500 / 靛紫 #4B0082 / 海绿 #2E8B57），
 * 并保留原有 6 色中的高频品牌色。自定义 hex 输入仍可用。
 */
export const ACCENT_COLOR_OPTIONS = [
  { value: "#000000", label: "黑色" },
  { value: "#333333", label: "深灰" },
  { value: "#666666", label: "中灰" },
  { value: "#999999", label: "浅灰" },
  { value: "#0047AB", label: "宝蓝" },
  { value: "#2563eb", label: "蓝色" },
  { value: "#2E8B57", label: "海绿" },
  { value: "#059669", label: "绿色" },
  { value: "#8B0000", label: "深红" },
  { value: "#dc2626", label: "红色" },
  { value: "#FF4500", label: "橙红" },
  { value: "#4B0082", label: "靛紫" },
];

/** 页面大小选项 */
export const PAGE_SIZE_OPTIONS = [
  { value: "A4", label: "A4 (210×297mm)" },
  { value: "Letter", label: "Letter (216×279mm)" },
];
