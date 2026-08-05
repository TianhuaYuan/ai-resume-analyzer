/**
 * 暗夜紫 模板 — 深色侧栏 + 暗底主栏，紫强调，先锋视觉（Magic gengar）
 *
 * 由 scripts/generate-templates/generate.mjs 生成，请勿手改。
 */

import { TEMPLATE_BASE_STYLES } from "../shared/templateBaseStyles";
import { renderSection } from "../shared/renderSection";
import type { TemplateComponentProps } from "../registry";

// 对齐后端 render_resume 的 sidebar_types
const SIDEBAR_TYPES = new Set([
  "basic_info",
  "skills",
  "language",
  "social_links",
  "interests",
]);

const STYLES = `
/* ── sidebar 布局：彩色侧栏 + 主栏。多栏模板 → 单页渲染(全出血) ── */
.resume-template.gengar-template {
  background: #111827;
  color: #f9fafb;
}
.resume-template.gengar-template .gengar-layout {
  display: flex;
  min-height: 100%;
}
.resume-template.gengar-template .gengar-sidebar {
  width: 30%;
  flex-shrink: 0;
  background: #1f2937;
  color: #f9fafb;
  padding: calc(var(--margin) * 0.75) calc(var(--margin) * 0.5);
}
.resume-template.gengar-template .gengar-main {
  flex: 1;
  min-width: 0;
  padding: var(--margin);
}

/* ── 侧栏内部 ── */
.resume-template.gengar-template .gengar-sidebar .module { margin-bottom: 20px; }
.resume-template.gengar-template .gengar-sidebar .module-title {
  color: #f9fafb;
  font-size: calc(var(--font-size) * 1.02);
  font-weight: 700;
  letter-spacing: 1px;
  margin-bottom: 8px;
  padding-bottom: 5px;
  border-bottom: 2px solid rgba(255, 255, 255, 0.25);
}
.resume-template.gengar-template .gengar-sidebar .module-title::after { display: none; }
.resume-template.gengar-template .gengar-sidebar .module-content { padding-left: 0; }
.resume-template.gengar-template .gengar-sidebar .basic-name {
  color: #f9fafb;
  font-size: calc(var(--font-size) * 1.7);
  letter-spacing: 2px;
  margin-bottom: 4px;
}
.resume-template.gengar-template .gengar-sidebar .basic-job-title {
  color: var(--accent-color);
  font-weight: 600;
  margin-bottom: 8px;
}
.resume-template.gengar-template .gengar-sidebar .basic-contact,
.resume-template.gengar-template .gengar-sidebar .basic-summary,
.resume-template.gengar-template .gengar-sidebar .basic-links,
.resume-template.gengar-template .gengar-sidebar .interests,
.resume-template.gengar-template .gengar-sidebar .social-links,
.resume-template.gengar-template .gengar-sidebar .lang-item,
.resume-template.gengar-template .gengar-sidebar .cert-item,
.resume-template.gengar-template .gengar-sidebar .honor-item,
.resume-template.gengar-template .gengar-sidebar .rec-item,
.resume-template.gengar-template .gengar-sidebar .fallback-row {
  color: #f9fafb;
  opacity: 0.92;
  font-size: calc(var(--font-size) * 0.92);
  line-height: 1.8;
}
.resume-template.gengar-template .gengar-sidebar .basic-contact span { display: block; }
.resume-template.gengar-template .gengar-sidebar .basic-header { margin-bottom: 6px; padding-bottom: 6px; }
.resume-template.gengar-template .gengar-sidebar .basic-links a { color: var(--accent-color); }
.resume-template.gengar-template .gengar-sidebar .skill-cat { display: block; margin-bottom: 9px; }
.resume-template.gengar-template .gengar-sidebar .skill-name {
  color: #f9fafb;
  font-weight: 600;
  display: block;
  margin-bottom: 4px;
  opacity: 0.85;
  min-width: 0;
}
.resume-template.gengar-template .gengar-sidebar .skill-item {
  display: inline-block;
  color: #f9fafb;
  background: rgba(255, 255, 255, 0.14);
  border: none;
  border-radius: 999px;
  padding: 1px 9px;
  margin: 2px 4px 2px 0;
  font-size: calc(var(--font-size) * 0.85);
}

/* ── 主栏 ── */
.resume-template.gengar-template .gengar-main .module { margin-bottom: var(--section-spacing); }
.resume-template.gengar-template .gengar-main .module-title {
  font-size: calc(var(--font-size) * 1.08);
  color: #f9fafb;
}
.resume-template.gengar-template .gengar-main .edu-school,
.resume-template.gengar-template .gengar-main .work-company,
.resume-template.gengar-template .gengar-main .proj-name,
.resume-template.gengar-template .gengar-main .club-name,
.resume-template.gengar-template .gengar-main .skill-name,
.resume-template.gengar-template .gengar-main .fallback-key,
.resume-template.gengar-template .gengar-main .other-title,
.resume-template.gengar-template .gengar-main .custom-title,
.resume-template.gengar-template .gengar-main .pub-title { color: #f9fafb; }


/* 共享文字色 */
.resume-template.gengar-template .basic-summary, .resume-template.gengar-template .basic-contact, .resume-template.gengar-template .basic-links, .resume-template.gengar-template .basic-custom-fields
.resume-template.gengar-template .work-desc, .resume-template.gengar-template .proj-desc, .resume-template.gengar-template .edu-desc, .resume-template.gengar-template .club-desc
.resume-template.gengar-template .work-achievements, .resume-template.gengar-template .lang-item, .resume-template.gengar-template .cert-item, .resume-template.gengar-template .honor-item, .resume-template.gengar-template .rec-item
.resume-template.gengar-template .interests, .resume-template.gengar-template .social-link, .resume-template.gengar-template .social-links, .resume-template.gengar-template .other-content, .resume-template.gengar-template .custom-content
.resume-template.gengar-template .pub-authors, .resume-template.gengar-template .proj-tech, .resume-template.gengar-template .fallback-row { color: #d1d5db; }
.resume-template.gengar-template .edu-date, .resume-template.gengar-template .work-date, .resume-template.gengar-template .proj-date, .resume-template.gengar-template .club-date
.resume-template.gengar-template .honor-date, .resume-template.gengar-template .rec-contact, .resume-template.gengar-template .pub-info { color: #d1d5db; opacity: 0.75; }

.resume-template.gengar-template .skill-item { display:inline-block; background:transparent; border:1px solid var(--accent-color); color:var(--accent-color); border-radius:4px; padding:1px 9px; margin:2px 5px 2px 0; font-size:calc(var(--font-size) * 0.92); }
`;

export default function GengarTemplate({
  modules,
  interactive,
  onSelectSection,
}: TemplateComponentProps) {
  const sidebar = modules.filter((m) => SIDEBAR_TYPES.has(m.module_type));
  const main = modules.filter((m) => !SIDEBAR_TYPES.has(m.module_type));
  const opts = { interactive, onSelectSection };

  return (
    <div className="resume-template gengar-template">
      <style>{TEMPLATE_BASE_STYLES + STYLES}</style>
      <div className="gengar-layout">
        <div className="gengar-sidebar">
          {sidebar.map((mod) => renderSection(mod, opts))}
        </div>
        <div className="gengar-main">
          {main.map((mod) => renderSection(mod, opts))}
        </div>
      </div>
    </div>
  );
}
