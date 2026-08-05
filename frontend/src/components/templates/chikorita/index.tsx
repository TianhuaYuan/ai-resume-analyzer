/**
 * 清新绿侧栏 模板 — 清新绿侧栏 + 白底主栏，自然亲和（Magic chikorita）
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
.resume-template.chikorita-template {
  background: #ffffff;
  color: #111827;
}
.resume-template.chikorita-template .chikorita-layout {
  display: flex;
  min-height: 100%;
}
.resume-template.chikorita-template .chikorita-sidebar {
  width: 30%;
  flex-shrink: 0;
  background: #16a34a;
  color: #f0fdf4;
  padding: calc(var(--margin) * 0.75) calc(var(--margin) * 0.5);
}
.resume-template.chikorita-template .chikorita-main {
  flex: 1;
  min-width: 0;
  padding: var(--margin);
}

/* ── 侧栏内部 ── */
.resume-template.chikorita-template .chikorita-sidebar .module { margin-bottom: 20px; }
.resume-template.chikorita-template .chikorita-sidebar .module-title {
  color: #f0fdf4;
  font-size: calc(var(--font-size) * 1.02);
  font-weight: 700;
  letter-spacing: 1px;
  margin-bottom: 8px;
  padding-bottom: 5px;
  border-bottom: 2px solid rgba(255, 255, 255, 0.25);
}
.resume-template.chikorita-template .chikorita-sidebar .module-title::after { display: none; }
.resume-template.chikorita-template .chikorita-sidebar .module-content { padding-left: 0; }
.resume-template.chikorita-template .chikorita-sidebar .basic-name {
  color: #f0fdf4;
  font-size: calc(var(--font-size) * 1.7);
  letter-spacing: 2px;
  margin-bottom: 4px;
}
.resume-template.chikorita-template .chikorita-sidebar .basic-job-title {
  color: var(--accent-color);
  font-weight: 600;
  margin-bottom: 8px;
}
.resume-template.chikorita-template .chikorita-sidebar .basic-contact,
.resume-template.chikorita-template .chikorita-sidebar .basic-summary,
.resume-template.chikorita-template .chikorita-sidebar .basic-links,
.resume-template.chikorita-template .chikorita-sidebar .interests,
.resume-template.chikorita-template .chikorita-sidebar .social-links,
.resume-template.chikorita-template .chikorita-sidebar .lang-item,
.resume-template.chikorita-template .chikorita-sidebar .cert-item,
.resume-template.chikorita-template .chikorita-sidebar .honor-item,
.resume-template.chikorita-template .chikorita-sidebar .rec-item,
.resume-template.chikorita-template .chikorita-sidebar .fallback-row {
  color: #f0fdf4;
  opacity: 0.92;
  font-size: calc(var(--font-size) * 0.92);
  line-height: 1.8;
}
.resume-template.chikorita-template .chikorita-sidebar .basic-contact span { display: block; }
.resume-template.chikorita-template .chikorita-sidebar .basic-header { margin-bottom: 6px; padding-bottom: 6px; }
.resume-template.chikorita-template .chikorita-sidebar .basic-links a { color: var(--accent-color); }
.resume-template.chikorita-template .chikorita-sidebar .skill-cat { display: block; margin-bottom: 9px; }
.resume-template.chikorita-template .chikorita-sidebar .skill-name {
  color: #f0fdf4;
  font-weight: 600;
  display: block;
  margin-bottom: 4px;
  opacity: 0.85;
  min-width: 0;
}
.resume-template.chikorita-template .chikorita-sidebar .skill-item {
  display: inline-block;
  color: #f0fdf4;
  background: rgba(255, 255, 255, 0.14);
  border: none;
  border-radius: 999px;
  padding: 1px 9px;
  margin: 2px 4px 2px 0;
  font-size: calc(var(--font-size) * 0.85);
}

/* ── 主栏 ── */
.resume-template.chikorita-template .chikorita-main .module { margin-bottom: var(--section-spacing); }
.resume-template.chikorita-template .chikorita-main .module-title {
  font-size: calc(var(--font-size) * 1.08);
  color: #111827;
}
.resume-template.chikorita-template .chikorita-main .edu-school,
.resume-template.chikorita-template .chikorita-main .work-company,
.resume-template.chikorita-template .chikorita-main .proj-name,
.resume-template.chikorita-template .chikorita-main .club-name,
.resume-template.chikorita-template .chikorita-main .skill-name,
.resume-template.chikorita-template .chikorita-main .fallback-key,
.resume-template.chikorita-template .chikorita-main .other-title,
.resume-template.chikorita-template .chikorita-main .custom-title,
.resume-template.chikorita-template .chikorita-main .pub-title { color: #111827; }


/* 共享文字色 */
.resume-template.chikorita-template .basic-summary, .resume-template.chikorita-template .basic-contact, .resume-template.chikorita-template .basic-links, .resume-template.chikorita-template .basic-custom-fields
.resume-template.chikorita-template .work-desc, .resume-template.chikorita-template .proj-desc, .resume-template.chikorita-template .edu-desc, .resume-template.chikorita-template .club-desc
.resume-template.chikorita-template .work-achievements, .resume-template.chikorita-template .lang-item, .resume-template.chikorita-template .cert-item, .resume-template.chikorita-template .honor-item, .resume-template.chikorita-template .rec-item
.resume-template.chikorita-template .interests, .resume-template.chikorita-template .social-link, .resume-template.chikorita-template .social-links, .resume-template.chikorita-template .other-content, .resume-template.chikorita-template .custom-content
.resume-template.chikorita-template .pub-authors, .resume-template.chikorita-template .proj-tech, .resume-template.chikorita-template .fallback-row { color: #6b7280; }
.resume-template.chikorita-template .edu-date, .resume-template.chikorita-template .work-date, .resume-template.chikorita-template .proj-date, .resume-template.chikorita-template .club-date
.resume-template.chikorita-template .honor-date, .resume-template.chikorita-template .rec-contact, .resume-template.chikorita-template .pub-info { color: #6b7280; opacity: 0.75; }

.resume-template.chikorita-template .module-title::after { display: none; }

.resume-template.chikorita-template .skill-item { display:inline-block; background:rgba(15,23,42,0.05); border:1px solid rgba(15,23,42,0.12); color:var(--accent-color); border-radius:4px; padding:1px 8px; margin:2px 4px 2px 0; font-size:calc(var(--font-size) * 0.92); }
`;

export default function ChikoritaTemplate({
  modules,
  interactive,
  onSelectSection,
}: TemplateComponentProps) {
  const sidebar = modules.filter((m) => SIDEBAR_TYPES.has(m.module_type));
  const main = modules.filter((m) => !SIDEBAR_TYPES.has(m.module_type));
  const opts = { interactive, onSelectSection };

  return (
    <div className="resume-template chikorita-template">
      <style>{TEMPLATE_BASE_STYLES + STYLES}</style>
      <div className="chikorita-layout">
        <div className="chikorita-sidebar">
          {sidebar.map((mod) => renderSection(mod, opts))}
        </div>
        <div className="chikorita-main">
          {main.map((mod) => renderSection(mod, opts))}
        </div>
      </div>
    </div>
  );
}
