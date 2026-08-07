/**
 * 活力橙双栏 模板 — 橙色侧栏双栏，活泼自信（Magic orange-modern × RR pikachu）
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
.resume-template.orange-template {
  background: #ffffff;
  color: #1f2937;
}
.resume-template.orange-template .orange-layout {
  display: flex;
  min-height: 100%;
}
.resume-template.orange-template .orange-sidebar {
  width: 30%;
  flex-shrink: 0;
  background: #f97316;
  color: #fff7ed;
  padding: calc(var(--margin) * 0.75) calc(var(--margin) * 0.5);
}
.resume-template.orange-template .orange-main {
  flex: 1;
  min-width: 0;
  padding: var(--margin);
}

/* ── 侧栏内部 ── */
.resume-template.orange-template .orange-sidebar .module { margin-bottom: 20px; }
.resume-template.orange-template .orange-sidebar .module-title {
  color: #fff7ed;
  font-size: calc(var(--font-size) * 1.02);
  font-weight: 700;
  letter-spacing: 1px;
  margin-bottom: 8px;
  padding-bottom: 5px;
  border-bottom: 2px solid rgba(255, 255, 255, 0.25);
}
.resume-template.orange-template .orange-sidebar .module-title::after { display: none; }
.resume-template.orange-template .orange-sidebar .module-content { padding-left: 0; }
.resume-template.orange-template .orange-sidebar .basic-name {
  color: #fff7ed;
  font-size: calc(var(--font-size) * 1.7);
  letter-spacing: 2px;
  margin-bottom: 4px;
}
.resume-template.orange-template .orange-sidebar .basic-job-title {
  color: var(--accent-color);
  font-weight: 700;
  margin-bottom: 8px;
}
.resume-template.orange-template .orange-sidebar .basic-contact,
.resume-template.orange-template .orange-sidebar .basic-summary,
.resume-template.orange-template .orange-sidebar .basic-links,
.resume-template.orange-template .orange-sidebar .interests,
.resume-template.orange-template .orange-sidebar .social-links,
.resume-template.orange-template .orange-sidebar .lang-item,
.resume-template.orange-template .orange-sidebar .cert-item,
.resume-template.orange-template .orange-sidebar .honor-item,
.resume-template.orange-template .orange-sidebar .rec-item,
.resume-template.orange-template .orange-sidebar .fallback-row {
  color: #fff7ed;
  opacity: 0.92;
  font-size: calc(var(--font-size) * 0.92);
  line-height: 1.8;
}
.resume-template.orange-template .orange-sidebar .basic-contact span { display: block; }
.resume-template.orange-template .orange-sidebar .basic-header { margin-bottom: 6px; padding-bottom: 6px; }
.resume-template.orange-template .orange-sidebar .basic-links a { color: var(--accent-color); }
.resume-template.orange-template .orange-sidebar .skill-cat { display: block; margin-bottom: 9px; }
.resume-template.orange-template .orange-sidebar .skill-name {
  color: #fff7ed;
  font-weight: 600;
  display: block;
  margin-bottom: 4px;
  opacity: 0.85;
  min-width: 0;
}
.resume-template.orange-template .orange-sidebar .skill-item {
  display: inline-block;
  color: #fff7ed;
  background: rgba(255, 255, 255, 0.14);
  border: none;
  border-radius: 999px;
  padding: 1px 9px;
  margin: 2px 4px 2px 0;
  font-size: calc(var(--font-size) * 0.85);
}

/* ── 主栏 ── */
.resume-template.orange-template .orange-main .module { margin-bottom: var(--section-spacing); }
.resume-template.orange-template .orange-main .module-title {
  font-size: calc(var(--font-size) * 1.08);
  color: #1f2937;
}
.resume-template.orange-template .orange-main .edu-school,
.resume-template.orange-template .orange-main .work-company,
.resume-template.orange-template .orange-main .proj-name,
.resume-template.orange-template .orange-main .club-name,
.resume-template.orange-template .orange-main .skill-name,
.resume-template.orange-template .orange-main .fallback-key,
.resume-template.orange-template .orange-main .other-title,
.resume-template.orange-template .orange-main .custom-title,
.resume-template.orange-template .orange-main .pub-title { color: #1f2937; }


/* 共享文字色 */
.resume-template.orange-template .basic-summary, .resume-template.orange-template .basic-contact, .resume-template.orange-template .basic-links, .resume-template.orange-template .basic-custom-fields
.resume-template.orange-template .work-desc, .resume-template.orange-template .proj-desc, .resume-template.orange-template .edu-desc, .resume-template.orange-template .club-desc
.resume-template.orange-template .work-achievements, .resume-template.orange-template .lang-item, .resume-template.orange-template .cert-item, .resume-template.orange-template .honor-item, .resume-template.orange-template .rec-item
.resume-template.orange-template .interests, .resume-template.orange-template .social-link, .resume-template.orange-template .social-links, .resume-template.orange-template .other-content, .resume-template.orange-template .custom-content
.resume-template.orange-template .pub-authors, .resume-template.orange-template .proj-tech, .resume-template.orange-template .fallback-row { color: #6b7280; }
.resume-template.orange-template .edu-date, .resume-template.orange-template .work-date, .resume-template.orange-template .proj-date, .resume-template.orange-template .club-date
.resume-template.orange-template .honor-date, .resume-template.orange-template .rec-contact, .resume-template.orange-template .pub-info { color: #6b7280; opacity: 0.75; }

.resume-template.orange-template .skill-item { display:inline-block; background:rgba(15,23,42,0.06); border:none; color:var(--accent-color); border-radius:999px; padding:2px 12px; margin:2px 6px 2px 0; font-size:calc(var(--font-size) * 0.92); }
`;

export default function OrangeTemplate({
  modules,
  interactive,
  onSelectSection,
}: TemplateComponentProps) {
  const sidebar = modules.filter((m) => SIDEBAR_TYPES.has(m.module_type));
  const main = modules.filter((m) => !SIDEBAR_TYPES.has(m.module_type));
  const opts = { interactive, onSelectSection };

  return (
    <div className="resume-template orange-template">
      <style>{TEMPLATE_BASE_STYLES + STYLES}</style>
      <div className="orange-layout">
        {sidebar.length > 0 && (
          <div className="orange-sidebar" style={main.length === 0 ? { width: "100%" } : undefined}>
            {sidebar.map((mod) => renderSection(mod, opts))}
          </div>
        )}
        {main.length > 0 && (
          <div className="orange-main">
            {main.map((mod) => renderSection(mod, opts))}
          </div>
        )}
      </div>
    </div>
  );
}
