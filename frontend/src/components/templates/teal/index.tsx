/**
 * 青绿侧栏 模板 — 青绿侧栏 + 清爽主栏，技术岗清新风（Magic teal-professional × RR chikorita）
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
.resume-template.teal-template {
  background: #ffffff;
  color: #1f2937;
}
.resume-template.teal-template .teal-layout {
  display: flex;
  min-height: 100%;
}
.resume-template.teal-template .teal-sidebar {
  width: 30%;
  flex-shrink: 0;
  background: #0d9488;
  color: #f0fdfa;
  padding: calc(var(--margin) * 0.75) calc(var(--margin) * 0.5);
}
.resume-template.teal-template .teal-main {
  flex: 1;
  min-width: 0;
  padding: var(--margin);
}

/* ── 侧栏内部 ── */
.resume-template.teal-template .teal-sidebar .module { margin-bottom: 20px; }
.resume-template.teal-template .teal-sidebar .module-title {
  color: #f0fdfa;
  font-size: calc(var(--font-size) * 1.02);
  font-weight: 700;
  letter-spacing: 1px;
  margin-bottom: 8px;
  padding-bottom: 5px;
  border-bottom: 2px solid rgba(255, 255, 255, 0.25);
}
.resume-template.teal-template .teal-sidebar .module-title::after { display: none; }
.resume-template.teal-template .teal-sidebar .module-content { padding-left: 0; }
.resume-template.teal-template .teal-sidebar .basic-name {
  color: #f0fdfa;
  font-size: calc(var(--font-size) * 1.7);
  letter-spacing: 2px;
  margin-bottom: 4px;
}
.resume-template.teal-template .teal-sidebar .basic-job-title {
  color: var(--accent-color);
  font-weight: 600;
  margin-bottom: 8px;
}
.resume-template.teal-template .teal-sidebar .basic-contact,
.resume-template.teal-template .teal-sidebar .basic-summary,
.resume-template.teal-template .teal-sidebar .basic-links,
.resume-template.teal-template .teal-sidebar .interests,
.resume-template.teal-template .teal-sidebar .social-links,
.resume-template.teal-template .teal-sidebar .lang-item,
.resume-template.teal-template .teal-sidebar .cert-item,
.resume-template.teal-template .teal-sidebar .honor-item,
.resume-template.teal-template .teal-sidebar .rec-item,
.resume-template.teal-template .teal-sidebar .fallback-row {
  color: #f0fdfa;
  opacity: 0.92;
  font-size: calc(var(--font-size) * 0.92);
  line-height: 1.8;
}
.resume-template.teal-template .teal-sidebar .basic-contact span { display: block; }
.resume-template.teal-template .teal-sidebar .basic-header { margin-bottom: 6px; padding-bottom: 6px; }
.resume-template.teal-template .teal-sidebar .basic-links a { color: var(--accent-color); }
.resume-template.teal-template .teal-sidebar .skill-cat { display: block; margin-bottom: 9px; }
.resume-template.teal-template .teal-sidebar .skill-name {
  color: #f0fdfa;
  font-weight: 600;
  display: block;
  margin-bottom: 4px;
  opacity: 0.85;
  min-width: 0;
}
.resume-template.teal-template .teal-sidebar .skill-item {
  display: inline-block;
  color: #f0fdfa;
  background: rgba(255, 255, 255, 0.14);
  border: none;
  border-radius: 999px;
  padding: 1px 9px;
  margin: 2px 4px 2px 0;
  font-size: calc(var(--font-size) * 0.85);
}

/* ── 主栏 ── */
.resume-template.teal-template .teal-main .module { margin-bottom: var(--section-spacing); }
.resume-template.teal-template .teal-main .module-title {
  font-size: calc(var(--font-size) * 1.08);
  color: #1f2937;
}
.resume-template.teal-template .teal-main .edu-school,
.resume-template.teal-template .teal-main .work-company,
.resume-template.teal-template .teal-main .proj-name,
.resume-template.teal-template .teal-main .club-name,
.resume-template.teal-template .teal-main .skill-name,
.resume-template.teal-template .teal-main .fallback-key,
.resume-template.teal-template .teal-main .other-title,
.resume-template.teal-template .teal-main .custom-title,
.resume-template.teal-template .teal-main .pub-title { color: #1f2937; }


/* 共享文字色 */
.resume-template.teal-template .basic-summary, .resume-template.teal-template .basic-contact, .resume-template.teal-template .basic-links, .resume-template.teal-template .basic-custom-fields
.resume-template.teal-template .work-desc, .resume-template.teal-template .proj-desc, .resume-template.teal-template .edu-desc, .resume-template.teal-template .club-desc
.resume-template.teal-template .work-achievements, .resume-template.teal-template .lang-item, .resume-template.teal-template .cert-item, .resume-template.teal-template .honor-item, .resume-template.teal-template .rec-item
.resume-template.teal-template .interests, .resume-template.teal-template .social-link, .resume-template.teal-template .social-links, .resume-template.teal-template .other-content, .resume-template.teal-template .custom-content
.resume-template.teal-template .pub-authors, .resume-template.teal-template .proj-tech, .resume-template.teal-template .fallback-row { color: #6b7280; }
.resume-template.teal-template .edu-date, .resume-template.teal-template .work-date, .resume-template.teal-template .proj-date, .resume-template.teal-template .club-date
.resume-template.teal-template .honor-date, .resume-template.teal-template .rec-contact, .resume-template.teal-template .pub-info { color: #6b7280; opacity: 0.75; }

.resume-template.teal-template .skill-item { display:inline-block; background:rgba(15,23,42,0.06); border:none; color:var(--accent-color); border-radius:999px; padding:2px 12px; margin:2px 6px 2px 0; font-size:calc(var(--font-size) * 0.92); }
`;

export default function TealTemplate({
  modules,
  interactive,
  onSelectSection,
}: TemplateComponentProps) {
  const sidebar = modules.filter((m) => SIDEBAR_TYPES.has(m.module_type));
  const main = modules.filter((m) => !SIDEBAR_TYPES.has(m.module_type));
  const opts = { interactive, onSelectSection };

  return (
    <div className="resume-template teal-template">
      <style>{TEMPLATE_BASE_STYLES + STYLES}</style>
      <div className="teal-layout">
        {sidebar.length > 0 && (
          <div className="teal-sidebar" style={main.length === 0 ? { width: "100%" } : undefined}>
            {sidebar.map((mod) => renderSection(mod, opts))}
          </div>
        )}
        {main.length > 0 && (
          <div className="teal-main">
            {main.map((mod) => renderSection(mod, opts))}
          </div>
        )}
      </div>
    </div>
  );
}
