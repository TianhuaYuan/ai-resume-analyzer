/**
 * 模板注册表 — 借鉴 Magic Resume TEMPLATE_REGISTRY。
 *
 * 映射 template_id → React 模板组件。新增模板 = 建目录（config.ts + index.tsx）+ 在此加一行。
 * 模板组件统一签名 TemplateComponentProps（modules + style，数据驱动，与后端渲染同源）。
 */

import type { ComponentType } from "react";
import type { ModuleType, ResumeModule, ResumeStyle } from "../../api/builder";

import DefaultTemplate from "./default";
import MinimalTemplate from "./minimal";
import BusinessTemplate from "./business";
import ProfessionalTemplate from "./professional";
import ElegantTemplate from "./elegant";

import { defaultConfig } from "./default/config";
import { minimalConfig } from "./minimal/config";
import { businessConfig } from "./business/config";
import { professionalConfig } from "./professional/config";
import { elegantConfig } from "./elegant/config";

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
 * 这些模板暂按单页渲染（不分页），后续如需支持需实现按栏分别装箱。
 */
export const MULTI_COLUMN_TEMPLATES = new Set(["professional"]);

/** 该模板是否为双栏布局（分页策略需区别对待） */
export function isMultiColumnTemplate(templateId: string | null | undefined): boolean {
  return MULTI_COLUMN_TEMPLATES.has(templateId ?? "");
}

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

export const TEMPLATE_REGISTRY: TemplateRegistryEntry[] = [
  { config: defaultConfig, Component: DefaultTemplate },
  { config: minimalConfig, Component: MinimalTemplate },
  { config: businessConfig, Component: BusinessTemplate },
  { config: professionalConfig, Component: ProfessionalTemplate },
  { config: elegantConfig, Component: ElegantTemplate },
];

/** 按 template_id 解析模板组件，未知 id 兜底 default */
export function getTemplateComponent(
  templateId: string | null | undefined,
): ComponentType<TemplateComponentProps> {
  return (
    TEMPLATE_REGISTRY.find((entry) => entry.config.id === templateId)?.Component ??
    DefaultTemplate
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
