/**
 * 琥珀深侧栏 模板 — 琥珀强调 + 深灰侧栏，优雅高端（Magic golden-elegant）
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
.resume-template.golden-elegant-template {
  background: #ffffff;
  color: #1f2937;
}
.resume-template.golden-elegant-template .golden-elegant-layout {
  display: flex;
  min-height: 100%;
}
.resume-template.golden-elegant-template .golden-elegant-sidebar {
  width: 30%;
  flex-shrink: 0;
  background: #374151;
  color: #fef3c7;
  padding: calc(var(--margin) * 0.75) calc(var(--margin) * 0.5);
}
.resume-template.golden-elegant-template .golden-elegant-main {
  flex: 1;
  min-width: 0;
  padding: var(--margin);
}

/* ── 侧栏内部 ── */
.resume-template.golden-elegant-template .golden-elegant-sidebar .module { margin-bottom: 20px; }
.resume-template.golden-elegant-template .golden-elegant-sidebar .module-title {
  color: #fef3c7;
  font-size: calc(var(--font-size) * 1.02);
  font-weight: 700;
  letter-spacing: 1px;
  margin-bottom: 8px;
  padding-bottom: 5px;
  border-bottom: 2px solid rgba(255, 255, 255, 0.25);
}
.resume-template.golden-elegant-template .golden-elegant-sidebar .module-title::after { display: none; }
.resume-template.golden-elegant-template .golden-elegant-sidebar .module-content { padding-left: 0; }
.resume-template.golden-elegant-template .golden-elegant-sidebar .basic-name {
  color: #fef3c7;
  font-size: calc(var(--font-size) * 1.7);
  letter-spacing: 2px;
  margin-bottom: 4px;
}
.resume-template.golden-elegant-template .golden-elegant-sidebar .basic-job-title {
  color: var(--accent-color);
  font-weight: 600;
  margin-bottom: 8px;
}
.resume-template.golden-elegant-template .golden-elegant-sidebar .basic-contact,
.resume-template.golden-elegant-template .golden-elegant-sidebar .basic-summary,
.resume-template.golden-elegant-template .golden-elegant-sidebar .basic-links,
.resume-template.golden-elegant-template .golden-elegant-sidebar .interests,
.resume-template.golden-elegant-template .golden-elegant-sidebar .social-links,
.resume-template.golden-elegant-template .golden-elegant-sidebar .lang-item,
.resume-template.golden-elegant-template .golden-elegant-sidebar .cert-item,
.resume-template.golden-elegant-template .golden-elegant-sidebar .honor-item,
.resume-template.golden-elegant-template .golden-elegant-sidebar .rec-item,
.resume-template.golden-elegant-template .golden-elegant-sidebar .fallback-row {
  color: #fef3c7;
  opacity: 0.92;
  font-size: calc(var(--font-size) * 0.92);
  line-height: 1.8;
}
.resume-template.golden-elegant-template .golden-elegant-sidebar .basic-contact span { display: block; }
.resume-template.golden-elegant-template .golden-elegant-sidebar .basic-header { margin-bottom: 6px; padding-bottom: 6px; }
.resume-template.golden-elegant-template .golden-elegant-sidebar .basic-links a { color: var(--accent-color); }
.resume-template.golden-elegant-template .golden-elegant-sidebar .skill-cat { display: block; margin-bottom: 9px; }
.resume-template.golden-elegant-template .golden-elegant-sidebar .skill-name {
  color: #fef3c7;
  font-weight: 600;
  display: block;
  margin-bottom: 4px;
  opacity: 0.85;
  min-width: 0;
}
.resume-template.golden-elegant-template .golden-elegant-sidebar .skill-item {
  display: inline-block;
  color: #fef3c7;
  background: rgba(255, 255, 255, 0.14);
  border: none;
  border-radius: 999px;
  padding: 1px 9px;
  margin: 2px 4px 2px 0;
  font-size: calc(var(--font-size) * 0.85);
}

/* ── 主栏 ── */
.resume-template.golden-elegant-template .golden-elegant-main .module { margin-bottom: var(--section-spacing); }
.resume-template.golden-elegant-template .golden-elegant-main .module-title {
  font-size: calc(var(--font-size) * 1.08);
  color: #1f2937;
}
.resume-template.golden-elegant-template .golden-elegant-main .edu-school,
.resume-template.golden-elegant-template .golden-elegant-main .work-company,
.resume-template.golden-elegant-template .golden-elegant-main .proj-name,
.resume-template.golden-elegant-template .golden-elegant-main .club-name,
.resume-template.golden-elegant-template .golden-elegant-main .skill-name,
.resume-template.golden-elegant-template .golden-elegant-main .fallback-key,
.resume-template.golden-elegant-template .golden-elegant-main .other-title,
.resume-template.golden-elegant-template .golden-elegant-main .custom-title,
.resume-template.golden-elegant-template .golden-elegant-main .pub-title { color: #1f2937; }


/* 共享文字色 */
.resume-template.golden-elegant-template .basic-summary, .resume-template.golden-elegant-template .basic-contact, .resume-template.golden-elegant-template .basic-links, .resume-template.golden-elegant-template .basic-custom-fields
.resume-template.golden-elegant-template .work-desc, .resume-template.golden-elegant-template .proj-desc, .resume-template.golden-elegant-template .edu-desc, .resume-template.golden-elegant-template .club-desc
.resume-template.golden-elegant-template .work-achievements, .resume-template.golden-elegant-template .lang-item, .resume-template.golden-elegant-template .cert-item, .resume-template.golden-elegant-template .honor-item, .resume-template.golden-elegant-template .rec-item
.resume-template.golden-elegant-template .interests, .resume-template.golden-elegant-template .social-link, .resume-template.golden-elegant-template .social-links, .resume-template.golden-elegant-template .other-content, .resume-template.golden-elegant-template .custom-content
.resume-template.golden-elegant-template .pub-authors, .resume-template.golden-elegant-template .proj-tech, .resume-template.golden-elegant-template .fallback-row { color: #6b7280; }
.resume-template.golden-elegant-template .edu-date, .resume-template.golden-elegant-template .work-date, .resume-template.golden-elegant-template .proj-date, .resume-template.golden-elegant-template .club-date
.resume-template.golden-elegant-template .honor-date, .resume-template.golden-elegant-template .rec-contact, .resume-template.golden-elegant-template .pub-info { color: #6b7280; opacity: 0.75; }

.resume-template.golden-elegant-template .skill-item { display:inline-block; background:rgba(15,23,42,0.05); border:1px solid rgba(15,23,42,0.12); color:var(--accent-color); border-radius:4px; padding:1px 8px; margin:2px 4px 2px 0; font-size:calc(var(--font-size) * 0.92); }
`;

export default function GoldenElegantTemplate({
  modules,
  interactive,
  onSelectSection,
}: TemplateComponentProps) {
  const sidebar = modules.filter((m) => SIDEBAR_TYPES.has(m.module_type));
  const main = modules.filter((m) => !SIDEBAR_TYPES.has(m.module_type));
  const opts = { interactive, onSelectSection };

  return (
    <div className="resume-template golden-elegant-template">
      <style>{TEMPLATE_BASE_STYLES + STYLES}</style>
      <div className="golden-elegant-layout">
        <div className="golden-elegant-sidebar">
          {sidebar.map((mod) => renderSection(mod, opts))}
        </div>
        <div className="golden-elegant-main">
          {main.map((mod) => renderSection(mod, opts))}
        </div>
      </div>
    </div>
  );
}
