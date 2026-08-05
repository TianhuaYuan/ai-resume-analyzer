#!/usr/bin/env node
/**
 * 模板产物不变量校验 — 由 scripts/generate-templates/generate.mjs 生成后运行。
 *
 * 检查：
 *  1. 后端 .html：含 {{modules}}、无残留 {{、var(--xxx) ⊆ 8 已知、无 grid、无 __ 占位符残留
 *  2. 前端 index.tsx：含 .resume-template.{id}-template、单栏类含 padding:var(--margin)、无 __ 占位符残留
 *  3. 前端 config.ts：含 TemplateConfig 必需字段
 *  4. 聚合注册表：18 套 + 双栏 id 集合
 *
 * 用法：node verify.mjs [--only=a,b,c]
 */
import { readFileSync, existsSync, readdirSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = join(__dirname, "..", "..");
const TEMPLATES_DIR = join(ROOT, "frontend", "src", "components", "templates");
const BACKEND_TEMPLATES_DIR = join(ROOT, "backend", "templates");

const KNOWN_VARS = [
  "--font-family", "--font-size", "--line-height", "--spacing",
  "--accent-color", "--margin", "--page-size", "--section-spacing",
];
// 允许在 var() 内出现 calc 表达式（如 var(--margin) * 0.75），正则只抓 var(--name)
const VAR_RE = /var\((--[\w-]+)/g;
const PLACEHOLDER_RE = /__[A-Z_]+__/;
const GRID_RE = /display\s*:\s*grid\b/i;

const args = process.argv.slice(2);
const onlyIdx = args.indexOf("--only");
const only = onlyIdx >= 0 ? args[onlyIdx + 1].split(",").map((s) => s.trim()).filter(Boolean) : null;

const tokens = JSON.parse(readFileSync(join(__dirname, "tokens.json"), "utf-8")).templates;
const targets = only ? tokens.filter((t) => only.includes(t.id)) : tokens;

let errors = [];
let ok = 0;

function err(msg) {
  errors.push(msg);
  console.error(`  ✗ ${msg}`);
}
function good(msg) {
  ok++;
  console.log(`  ✓ ${msg}`);
}

const SKIN_SINGLE_COL = new Set(["single", "cards", "timeline"]);

for (const t of targets) {
  console.log(`\n▶ ${t.id}（${t.layout}）`);
  const id = t.id;

  // ── 后端 .html ──
  const htmlPath = join(BACKEND_TEMPLATES_DIR, `${id}.html`);
  if (!existsSync(htmlPath)) { err(`缺少后端 ${htmlPath}`); }
  else {
    const html = readFileSync(htmlPath, "utf-8");
    if (!html.includes("{{modules}}")) err("后端缺少 {{modules}} 占位符");
    const leftover = html.match(/{{(?![a-z_]+}})/);
    if (leftover) err(`后端含未知 {{ 占位符残留: ${leftover[0]}`);
    const vars = new Set([...html.matchAll(VAR_RE)].map((m) => m[1]));
    const unknown = [...vars].filter((v) => !KNOWN_VARS.includes(v));
    if (unknown.length) err(`后端 var() 超白名单: ${unknown.join(", ")}`);
    if (GRID_RE.test(html)) err("后端含 display:grid");
    if (PLACEHOLDER_RE.test(html)) err("后端含 __X__ 占位符残留");
    if (!/[#0-9a-fA-F]{6}|#[0-9a-fA-F]{3}/.test(html)) err("后端疑似无 hex 色");
    if (vars.size === 0) err("后端无 var() 使用");
    if (!errors.some((e) => e.includes(id) && e.includes("后端"))) good("后端 .html 通过");
  }

  // ── 前端 index.tsx ──
  const indexPath = join(TEMPLATES_DIR, id, "index.tsx");
  if (!existsSync(indexPath)) { err(`缺少前端 ${indexPath}`); }
  else {
    const tsx = readFileSync(indexPath, "utf-8");
    if (!tsx.includes(`resume-template ${id}-template`)) err("前端缺 .resume-template.{id}-template 根类");
    if (!tsx.includes("TEMPLATE_BASE_STYLES")) err("前端缺 TEMPLATE_BASE_STYLES");
    if (PLACEHOLDER_RE.test(tsx)) err("前端含 __X__ 占位符残留");
    if (SKIN_SINGLE_COL.has(t.layout) && !/padding:\s*var\(--margin\)/.test(tsx)) {
      err("单栏类模板缺根 padding:var(--margin)");
    }
    if (t.layout === "sidebar") {
      if (!tsx.includes("SIDEBAR_TYPES")) err("侧栏模板缺 SIDEBAR_TYPES 分流");
      if (!tsx.includes(`${id}-layout`)) err("侧栏模板缺 {id}-layout 容器");
    }
    if (t.layout === "banner" && !tsx.includes("SectionContent")) err("头带模板缺 SectionContent 渲染 basic_info");
    if (!errors.some((e) => e.includes(id) && e.includes("前端"))) good("前端 index.tsx 通过");
  }

  // ── 前端 config.ts ──
  const configPath = join(TEMPLATES_DIR, id, "config.ts");
  if (!existsSync(configPath)) { err(`缺少前端 ${configPath}`); }
  else {
    const cfg = readFileSync(configPath, "utf-8");
    const needs = ["id:", "name:", "description:", "colorScheme:", "primary:", "secondary:", "background:", "text:", "spacing:", "sectionGap:", "itemGap:", "contentPadding:", "basic:", "layout:"];
    for (const n of needs) if (!cfg.includes(n)) err(`config.ts 缺字段 ${n}`);
    if (!errors.some((e) => e.includes(id) && e.includes("config"))) good("前端 config.ts 通过");
  }
}

// ── 聚合注册表（全量时） ──
if (!only) {
  const regPath = join(TEMPLATES_DIR, "generated", "registry.ts");
  console.log(`\n▶ 聚合注册表`);
  if (!existsSync(regPath)) err("缺 generated/registry.ts");
  else {
    const reg = readFileSync(regPath, "utf-8");
    const camel = (id) => id.split("-").map((p, i) => (i === 0 ? p : p.charAt(0).toUpperCase() + p.slice(1))).join("");
    for (const t of tokens) {
      if (!reg.includes(`../${t.id}/config`)) err(`注册表缺 ${t.id} config import`);
      if (!reg.includes(`${camel(t.id)}Config`)) err(`注册表缺 ${camel(t.id)}Config`);
    }
    const multi = tokens.filter((t) => t.multiColumn).map((t) => t.id);
    for (const m of multi) if (!reg.includes(`"${m}"`)) err(`注册表缺双栏 id ${m}`);
    if (!reg.includes("GENERATED_DEFAULT_COMPONENT")) err("注册表缺默认组件导出");
    if (!errors.some((e) => e.includes("注册表"))) good("聚合注册表通过");
  }
}

console.log(`\n${errors.length === 0 ? "✅ 全部通过" : `❌ ${errors.length} 个问题`}`);
process.exit(errors.length === 0 ? 0 : 1);
