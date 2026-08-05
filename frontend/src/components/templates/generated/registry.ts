/**
 * 自动生成的模板注册模块 — 由 scripts/generate-templates/generate.mjs 生成，请勿手改。
 */
import type { ComponentType } from "react";
import type { TemplateComponentProps, TemplateRegistryEntry } from "../registry";

import { defaultConfig } from "../default/config";
import DefaultTemplate from "../default/index";
import { azurillConfig } from "../azurill/config";
import AzurillTemplate from "../azurill/index";
import { tealConfig } from "../teal/config";
import TealTemplate from "../teal/index";
import { gengarConfig } from "../gengar/config";
import GengarTemplate from "../gengar/index";
import { slateConfig } from "../slate/config";
import SlateTemplate from "../slate/index";
import { orangeConfig } from "../orange/config";
import OrangeTemplate from "../orange/index";
import { chikoritaConfig } from "../chikorita/config";
import ChikoritaTemplate from "../chikorita/index";
import { goldenElegantConfig } from "../golden-elegant/config";
import GoldenElegantTemplate from "../golden-elegant/index";
import { executiveConfig } from "../executive/config";
import ExecutiveTemplate from "../executive/index";
import { dittoConfig } from "../ditto/config";
import DittoTemplate from "../ditto/index";
import { timelineProConfig } from "../timeline-pro/config";
import TimelineProTemplate from "../timeline-pro/index";
import { serifConfig } from "../serif/config";
import SerifTemplate from "../serif/index";
import { skillsFirstConfig } from "../skills-first/config";
import SkillsFirstTemplate from "../skills-first/index";
import { classicConfig } from "../classic/config";
import ClassicTemplate from "../classic/index";
import { redAccentConfig } from "../red-accent/config";
import RedAccentTemplate from "../red-accent/index";
import { productOpsConfig } from "../product-ops/config";
import ProductOpsTemplate from "../product-ops/index";
import { cnFormalConfig } from "../cn-formal/config";
import CnFormalTemplate from "../cn-formal/index";
import { compactCnConfig } from "../compact-cn/config";
import CompactCnTemplate from "../compact-cn/index";

export const GENERATED_TEMPLATES: TemplateRegistryEntry[] = [
  { config: defaultConfig, Component: DefaultTemplate },
  { config: azurillConfig, Component: AzurillTemplate },
  { config: tealConfig, Component: TealTemplate },
  { config: gengarConfig, Component: GengarTemplate },
  { config: slateConfig, Component: SlateTemplate },
  { config: orangeConfig, Component: OrangeTemplate },
  { config: chikoritaConfig, Component: ChikoritaTemplate },
  { config: goldenElegantConfig, Component: GoldenElegantTemplate },
  { config: executiveConfig, Component: ExecutiveTemplate },
  { config: dittoConfig, Component: DittoTemplate },
  { config: timelineProConfig, Component: TimelineProTemplate },
  { config: serifConfig, Component: SerifTemplate },
  { config: skillsFirstConfig, Component: SkillsFirstTemplate },
  { config: classicConfig, Component: ClassicTemplate },
  { config: redAccentConfig, Component: RedAccentTemplate },
  { config: productOpsConfig, Component: ProductOpsTemplate },
  { config: cnFormalConfig, Component: CnFormalTemplate },
  { config: compactCnConfig, Component: CompactCnTemplate },
];

/** 双栏（侧栏/双栏）模板 id —— 分页时按单页渲染 */
export const GENERATED_MULTI_COLUMN_IDS: string[] = ["azurill","teal","gengar","slate","orange","chikorita","golden-elegant"];

/** 默认模板组件（未知 template_id 兜底） */
export const GENERATED_DEFAULT_COMPONENT: ComponentType<TemplateComponentProps> = DefaultTemplate;
