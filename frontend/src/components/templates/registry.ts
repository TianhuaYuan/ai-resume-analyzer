/**
 * 模板注册表 — 借鉴 Magic Resume TEMPLATE_REGISTRY。
 *
 * 映射 template_id → React 模板组件。模板统一由
 * scripts/generate-templates/generate.mjs 从 tokens.json 生成，
 * 聚合注册在 ./generated/registry.ts。新增/修改模板 = 改 tokens.json 重新生成。
 *
 * 模板组件统一签名 TemplateComponentProps（modules + style，数据驱动，与后端渲染同源）。
 */

import type { ComponentType } from "react";
import type { ModuleType, ResumeModule, ResumeStyle } from "../../api/builder";

import {
  GENERATED_TEMPLATES,
  GENERATED_MULTI_COLUMN_IDS,
  GENERATED_DEFAULT_COMPONENT,
} from "./generated/registry";

export interface TemplateConfig {
  id: string;
  name: string;
  description: string;
  colorScheme: {
    primary: string;
    secondary: string;
    background: string;
    text: string;
  };
  spacing: {
    sectionGap: number;
    itemGap: number;
    contentPadding: number;
  };
  basic: {
    layout?: "left" | "center" | "right";
  };
}

/**
 * 双栏模板 id 集合。
 *
 * 双栏模板的 section 分布在左右两栏，垂直累加装箱（PaginatedResumePreview）
 * 对它无效 —— 累加高度会把左右两栏当成一列串起来，页数算成实际的两倍。
 * 分页改为「按栏分别装箱」：侧栏流与主栏流各自装箱后取最大页数逐页配对
 * （见 PaginatedResumePreview），这样每页都渲染完整的双栏结构且内容不被裁。
 */
export const MULTI_COLUMN_TEMPLATES = new Set(GENERATED_MULTI_COLUMN_IDS);

/** 该模板是否为双栏布局（分页策略需区别对待） */
export function isMultiColumnTemplate(templateId: string | null | undefined): boolean {
  return MULTI_COLUMN_TEMPLATES.has(templateId ?? "");
}

/**
 * 双栏模板侧栏模块类型（对齐后端 render_resume 的 sidebar_types）。
 * 7 套双栏模板（azurill/teal/gengar/slate/orange/chikorita/golden-elegant）侧栏集合一致，
 * 抽成共享常量供分页按栏装箱复用。
 */
export const SIDEBAR_TYPES = new Set<string>([
  "basic_info",
  "skills",
  "language",
  "social_links",
  "interests",
]);

export interface TemplateComponentProps {
  modules: ResumeModule[];
  style: ResumeStyle;
  interactive?: boolean;
  onSelectSection?: (moduleType: ModuleType) => void;
}

export interface TemplateRegistryEntry {
  config: TemplateConfig;
  Component: ComponentType<TemplateComponentProps>;
}

export const TEMPLATE_REGISTRY: TemplateRegistryEntry[] = GENERATED_TEMPLATES;

/** 按 template_id 解析模板组件，未知 id 兜底 default */
export function getTemplateComponent(
  templateId: string | null | undefined,
): ComponentType<TemplateComponentProps> {
  return (
    TEMPLATE_REGISTRY.find((entry) => entry.config.id === templateId)?.Component ??
    GENERATED_DEFAULT_COMPONENT
  );
}

/** 是否有对应 template_id 的前端 React 模板组件（没有则用后端 preview_html iframe 兜底） */
export function hasTemplateComponent(templateId: string | null | undefined): boolean {
  return TEMPLATE_REGISTRY.some((entry) => entry.config.id === templateId);
}

/** 全部前端模板 config 列表（供模板切换器/画廊使用） */
export function getTemplateConfigs() {
  return TEMPLATE_REGISTRY.map((entry) => entry.config);
}
