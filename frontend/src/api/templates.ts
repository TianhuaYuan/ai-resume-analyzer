/**
 * T31: 简历模板列表 — 前端静态配置。
 *
 * 后端 templates/ 目录有 3 套 HTML 模板（default/minimal/business），
 * 前端样式面板展示模板选择器时用此配置。无需后端 API（3 套固定模板不变）。
 */

export interface TemplateOption {
  id: string;
  name: string;
  description: string;
}

/** 3 套模板（与后端 templates/*.html 对齐） */
export const TEMPLATE_OPTIONS: TemplateOption[] = [
  {
    id: "default",
    name: "经典",
    description: "适合大多数场景，布局清晰，配色专业",
  },
  {
    id: "minimal",
    name: "极简",
    description: "极简风格，留白多，适合设计/创意类岗位",
  },
  {
    id: "business",
    name: "商务",
    description: "商务风格，强调结构感，适合金融/管理类岗位",
  },
];

/** 字体选项 */
export const FONT_OPTIONS = [
  { value: "Noto Sans CJK SC", label: "思源黑体" },
  { value: "Noto Serif CJK SC", label: "思源宋体" },
  { value: "Microsoft YaHei", label: "微软雅黑" },
  { value: "SimSun", label: "宋体" },
  { value: "sans-serif", label: "无衬线（系统默认）" },
];

/** 字号选项 */
export const FONT_SIZE_OPTIONS = [
  { value: "12px", label: "小" },
  { value: "14px", label: "中" },
  { value: "16px", label: "大" },
  { value: "18px", label: "特大" },
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

/** 预设主题色 */
export const ACCENT_COLOR_OPTIONS = [
  { value: "#2563eb", label: "蓝色" },
  { value: "#059669", label: "绿色" },
  { value: "#7c3aed", label: "紫色" },
  { value: "#dc2626", label: "红色" },
  { value: "#ea580c", label: "橙色" },
  { value: "#475569", label: "灰色" },
];

/** 页面大小选项 */
export const PAGE_SIZE_OPTIONS = [
  { value: "A4", label: "A4 (210×297mm)" },
  { value: "Letter", label: "Letter (216×279mm)" },
];
