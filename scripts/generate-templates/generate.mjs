#!/usr/bin/env node
/**
 * 简历模板生成器 — 从 tokens.json 生成 18 套前后端模板。
 *
 * 输入：tokens.json（唯一数据源，手工从 Magic-Resume DSL designTokens 抽取）
 * 产物：
 *   - frontend/src/components/templates/{id}/config.ts + index.tsx
 *   - frontend/src/components/templates/generated/registry.ts（聚合注册模块）
 *   - backend/templates/{id}.html（落盘即热加载）
 *
 * 运行时零依赖：产物是自包含纯文本（hex 色 + 8 CSS 变量 + 现有渲染器 class 契约）。
 * 本脚本零第三方依赖（纯字符串拼接），只在开发机跑。
 *
 * 用法：node generate.mjs [--only=a,b,c] [--force]
 *   --only  只生成指定模板（试跑用）
 *   --force 覆盖已存在文件（默认已存在跳过，幂等）
 */
import { readFileSync, writeFileSync, mkdirSync, existsSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = join(__dirname, "..", "..");
const TEMPLATES_DIR = join(ROOT, "frontend", "src", "components", "templates");
const BACKEND_TEMPLATES_DIR = join(ROOT, "backend", "templates");
const GENERATED_REGISTRY = join(TEMPLATES_DIR, "generated", "registry.ts");

const args = process.argv.slice(2);
const onlyIdx = args.findIndex((a) => a === "--only" || a.startsWith("--only="));
let only = null;
if (onlyIdx >= 0) {
  const raw = args[onlyIdx].startsWith("--only=")
    ? args[onlyIdx].slice("--only=".length)
    : args[onlyIdx + 1];
  only = raw.split(",").map((s) => s.trim()).filter(Boolean);
}
const force = args.includes("--force");

// ── 占位符替换 ──────────────────────────────────────────────
function fill(template, map) {
  let out = template;
  for (const [k, v] of Object.entries(map)) out = out.split(`__${k}__`).join(v);
  return out;
}

// ── 前端选择器前缀 ──────────────────────────────────────────
const S = (t) => `.resume-template.${t.id}-template`;

// ── 技能样式（前端/后端共用规则体） ─────────────────────────
function skillCss(t) {
  const fs = "font-size:calc(var(--font-size) * 0.92);";
  switch (t.skin.skillStyle) {
    case "pill":
      return `display:inline-block; background:rgba(15,23,42,0.06); border:none; color:var(--accent-color); border-radius:999px; padding:2px 12px; margin:2px 6px 2px 0; ${fs}`;
    case "outline":
      return `display:inline-block; background:transparent; border:1px solid var(--accent-color); color:var(--accent-color); border-radius:4px; padding:1px 9px; margin:2px 5px 2px 0; ${fs}`;
    case "text":
      return `display:inline-block; background:none; border:none; color:${t.colorScheme.text}; border-radius:0; padding:0; margin:0 8px 0 0; font-size:calc(var(--font-size) * 0.95);`;
    default: // chip
      return `display:inline-block; background:rgba(15,23,42,0.05); border:1px solid rgba(15,23,42,0.12); color:var(--accent-color); border-radius:4px; padding:1px 8px; margin:2px 4px 2px 0; ${fs}`;
  }
}

// ── 章节标题分隔样式 ────────────────────────────────────────
function dividerCss(t, s) {
  switch (t.skin.sectionDivider) {
    case "none":
      return `${s} .module-title::after { display: none; }`;
    case "underline":
      return `${s} .module-title { border-bottom: 2px solid ${t.colorScheme.divider}; padding-bottom: 4px; }\n${s} .module-title::after { display: none; }`;
    case "dot":
      return `${s} .module-title::before { content:""; width:8px; height:8px; border-radius:50%; background:var(--accent-color); flex-shrink:0; }\n${s} .module-title::after { display: none; }`;
    default: // line（基础样式自带 ::after 线）
      return "";
  }
}

// ── 头部强调条（仅单栏/时间轴/卡片） ────────────────────────
// 用 .basic-name 底部 accent 下划线：前端 .basic-header-line（flex 姓名行）与
// 后端 .basic-header（flex 姓名行）结构对齐，两端下划线位置天然一致。
function headerCss(t, s) {
  if (t.layout === "sidebar" || t.layout === "banner") return "";
  if (t.skin.headerStyle === "center") {
    return `${s} .basic-header { text-align: center; }\n${s} .basic-header-line { justify-content: center; }\n${s} .basic-name { border-bottom: 2px solid var(--accent-color); padding-bottom: 6px; }`;
  }
  return `${s} .basic-name { border-bottom: 2px solid var(--accent-color); padding-bottom: 6px; }`;
}

// ── 主栏时间轴（sidebar/banner 且 skin.timeline 时注入） ─────
const TL_MODULES = ["module-education", "module-work_experience", "module-project_experience", "module-club_activities"];
const TL_ITEMS = ["edu-item", "work-item", "proj-item", "club-item"];

function timelineCss(scope, bg) {
  const mSel = TL_MODULES.map((m) => `${scope} .${m} .module-content`).join(", ");
  const mBefore = TL_MODULES.map((m) => `${scope} .${m} .module-content::before`).join(", ");
  const iSel = TL_MODULES.map((m, i) => `${scope} .${m} .${TL_ITEMS[i]}`).join(", ");
  const iBefore = TL_MODULES.map((m, i) => `${scope} .${m} .${TL_ITEMS[i]}::before`).join(", ");
  return [
    `/* 主栏时间轴 */`,
    `${mSel} { position:relative; padding-left:20px; }`,
    `${mBefore} { content:""; position:absolute; left:7px; top:4px; bottom:4px; width:1px; background:var(--accent-color); opacity:0.35; }`,
    `${iSel} { position:relative; }`,
    `${iBefore} { content:""; position:absolute; left:-17px; top:6px; width:9px; height:9px; border-radius:50%; background:${bg}; border:2px solid var(--accent-color); }`,
  ].join("\n");
}

/** 前端版本时间轴（作用域带 .resume-template.{id}-template 前缀） */
function frontendBodyTimelineCss(t) {
  if (!t.skin.timeline) return "";
  if (t.layout === "sidebar") return timelineCss(`${S(t)} .${t.id}-main`, t.colorScheme.background);
  if (t.layout === "banner") return timelineCss(`${S(t)} .${t.id}-body`, t.colorScheme.background);
  return "";
}

/** 后端版本时间轴（作用于 .main / .body，无前缀） */
function backendBodyTimelineCss(t) {
  if (!t.skin.timeline) return "";
  if (t.layout === "sidebar") return timelineCss(".main", t.colorScheme.background);
  if (t.layout === "banner") return timelineCss(".body", t.colorScheme.background);
  return "";
}

// ── 前端共享文字色覆盖（对齐 token textSecondary，覆盖 templateBaseStyles 硬编码） ──
function sharedTextCss(t) {
  const s = S(t);
  const body = [
    `${s} .basic-summary, ${s} .basic-contact, ${s} .basic-links, ${s} .basic-custom-fields`,
    `${s} .work-desc, ${s} .proj-desc, ${s} .edu-desc, ${s} .club-desc`,
    `${s} .work-achievements, ${s} .lang-item, ${s} .cert-item, ${s} .honor-item, ${s} .rec-item`,
    `${s} .interests, ${s} .social-link, ${s} .social-links, ${s} .other-content, ${s} .custom-content`,
    `${s} .pub-authors, ${s} .proj-tech, ${s} .fallback-row { color: ${t.colorScheme.textSecondary}; }`,
  ].join("\n");
  const muted = [
    `${s} .edu-date, ${s} .work-date, ${s} .proj-date, ${s} .club-date`,
    `${s} .honor-date, ${s} .rec-contact, ${s} .pub-info { color: ${t.colorScheme.textSecondary}; opacity: 0.75; }`,
  ].join("\n");
  return `/* 共享文字色 */\n${body}\n${muted}`;
}

// ── 组装前端 index.tsx 的 STYLES ────────────────────────────
function frontendStyles(t) {
  const skinCss = readFileSync(join(__dirname, "skins", `${t.layout}.frontend.css`), "utf-8");
  const parts = [
    fill(skinCss, subs(t)),
    sharedTextCss(t),
    headerCss(t, S(t)),
    dividerCss(t, S(t)),
    `${S(t)} .skill-item { ${skillCss(t)} }`,
    frontendBodyTimelineCss(t),
  ];
  return parts.filter(Boolean).join("\n\n");
}

// ── 组装后端 .html 的条件 CSS ───────────────────────────────
function backendConditional(t) {
  const parts = [
    headerCss(t, ""),
    dividerCss(t, ""),
    `.skill-item { ${skillCss(t)} }`,
    backendBodyTimelineCss(t),
  ];
  return parts.filter(Boolean).join("\n");
}

// ── token → 占位符映射 ──────────────────────────────────────
function subs(t) {
  const c = t.colorScheme;
  return {
    ID: t.id,
    PASCAL: pascal(t.id),
    NAME: t.name,
    DESCRIPTION: t.description,
    BG: c.background,
    TEXT: c.text,
    TEXT_SECONDARY: c.textSecondary,
    BORDER: c.border,
    DIVIDER: c.divider,
    SIDEBAR_BG: c.sidebarBg,
    SIDEBAR_TEXT: c.sidebarText,
    SIDEBAR_WIDTH: t.skin.sidebarWidth || "30%",
    NAME_SIZE: t.typography.nameSize,
    SECTION_TITLE_SIZE: t.typography.sectionTitleSize,
    ACCENT_WEIGHT: t.typography.accentWeight,
  };
}

function pascal(id) {
  return id
    .split("-")
    .map((p) => p.charAt(0).toUpperCase() + p.slice(1))
    .join("");
}

/** camelCase（连字符 id → 合法 JS 标识符）：golden-elegant → goldenElegant */
function camel(id) {
  return id
    .split("-")
    .map((p, i) => (i === 0 ? p : p.charAt(0).toUpperCase() + p.slice(1)))
    .join("");
}

// ── config.ts ───────────────────────────────────────────────
function renderConfig(t) {
  const c = t.colorScheme;
  return `import type { TemplateConfig } from "../registry";

/** ${t.name} — ${t.description} */
export const ${camel(t.id)}Config: TemplateConfig = {
  id: "${t.id}",
  name: "${t.name}",
  description: "${t.description}",
  colorScheme: {
    primary: "${c.primary}",
    secondary: "${c.secondary}",
    background: "${c.background}",
    text: "${c.text}",
  },
  spacing: {
    sectionGap: ${t.spacing.sectionGap},
    itemGap: ${t.spacing.itemGap},
    contentPadding: ${t.spacing.contentPadding},
  },
  basic: {
    layout: "${t.basic.layout || "left"}",
  },
};
`;
}

// ── 生成 registry.ts 聚合模块 ───────────────────────────────
function renderGeneratedRegistry(ts) {
  const multi = ts.filter((t) => t.multiColumn).map((t) => t.id);
  const importLines = [];
  const entries = [];
  for (const t of ts) {
    const cfg = `${camel(t.id)}Config`;
    importLines.push(`import { ${cfg} } from "../${t.id}/config";`);
    importLines.push(`import ${pascal(t.id)}Template from "../${t.id}/index";`);
    entries.push(`  { config: ${cfg}, Component: ${pascal(t.id)}Template },`);
  }
  const multiArr = JSON.stringify(multi);
  const defaultComp = pascal(ts.find((t) => t.id === "default").id) + "Template";
  return `/**
 * 自动生成的模板注册模块 — 由 scripts/generate-templates/generate.mjs 生成，请勿手改。
 */
import type { ComponentType } from "react";
import type { TemplateComponentProps, TemplateRegistryEntry } from "../registry";

${importLines.join("\n")}

export const GENERATED_TEMPLATES: TemplateRegistryEntry[] = [
${entries.join("\n")}
];

/** 双栏（侧栏/双栏）模板 id —— 分页时按单页渲染 */
export const GENERATED_MULTI_COLUMN_IDS: string[] = ${multiArr};

/** 默认模板组件（未知 template_id 兜底） */
export const GENERATED_DEFAULT_COMPONENT: ComponentType<TemplateComponentProps> = ${defaultComp};
`;
}

// ── 生成模板选择器元信息（templates.ts 引用） ────────────────
function renderGeneratedOptions(ts) {
  const lines = ts.map(
    (t) => `  { id: "${t.id}", name: "${t.name}", description: "${t.description}" },`,
  );
  return `/**
 * 自动生成的模板选择器元信息 — 由 scripts/generate-templates/generate.mjs 生成，请勿手改。
 */
export interface GeneratedTemplateOption {
  id: string;
  name: string;
  description: string;
}

export const GENERATED_TEMPLATE_OPTIONS: GeneratedTemplateOption[] = [
${lines.join("\n")}
];
`;
}

// ── 主流程 ──────────────────────────────────────────────────
const tokens = JSON.parse(readFileSync(join(__dirname, "tokens.json"), "utf-8")).templates;
const targets = only ? tokens.filter((t) => only.includes(t.id)) : tokens;
const missing = only ? only.filter((id) => !tokens.some((t) => t.id === id)) : [];
if (missing.length) {
  console.error(`[warn] --only 中存在未知模板 id: ${missing.join(", ")}`);
}

const indexSkeleton = {};
for (const name of ["single", "sidebar", "banner"]) {
  indexSkeleton[name] = readFileSync(join(__dirname, "skeletons", `index-${name}.tsx.tmpl`), "utf-8");
}
const layoutToSkeleton = (layout) =>
  layout === "sidebar" ? "sidebar" : layout === "banner" ? "banner" : "single";

let generated = [];
for (const t of targets) {
  const id = t.id;
  const dir = join(TEMPLATES_DIR, id);
  const configPath = join(dir, "config.ts");
  const indexPath = join(dir, "index.tsx");
  const htmlPath = join(BACKEND_TEMPLATES_DIR, `${id}.html`);

  const indexTmpl = indexSkeleton[layoutToSkeleton(t.layout)];
  const htmlTmpl = readFileSync(join(__dirname, "skeletons", `template-${t.layout}.html.tmpl`), "utf-8");

  const files = {
    [configPath]: renderConfig(t),
    [indexPath]: fill(indexTmpl, { ...subs(t), SKIN_CSS: frontendStyles(t) }),
    [htmlPath]: fill(htmlTmpl, { ...subs(t), SKILL_CSS: skillCss(t), CONDITIONAL_CSS: backendConditional(t) }),
  };

  for (const [path, content] of Object.entries(files)) {
    if (existsSync(path) && !force) {
      console.log(`[skip] ${path}`);
      continue;
    }
    mkdirSync(dirname(path), { recursive: true });
    writeFileSync(path, content, "utf-8");
    console.log(`[write] ${path}`);
  }
  generated.push(t);
}

// 聚合注册表 + 选择器元信息：只有全量生成时才写（避免试跑覆盖 18 套注册表）
if (!only) {
  mkdirSync(dirname(GENERATED_REGISTRY), { recursive: true });
  writeFileSync(GENERATED_REGISTRY, renderGeneratedRegistry(tokens), "utf-8");
  console.log(`[write] ${GENERATED_REGISTRY}`);

  const optionsPath = join(ROOT, "frontend", "src", "api", "generatedTemplateOptions.ts");
  writeFileSync(optionsPath, renderGeneratedOptions(tokens), "utf-8");
  console.log(`[write] ${optionsPath}`);
}

console.log(`\n完成：生成 ${generated.length} 套模板（${generated.map((t) => t.id).join(", ")}）`);
if (only) console.log(`提示：试跑模式未写聚合注册表，全量运行（不带 --only）时写入。`);
