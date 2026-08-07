/**
 * 深蓝侧栏 模板 — 深蓝侧栏 + 主栏时间轴，现代专业（Magic azurill × RR azurill）
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
.resume-template.azurill-template {
  background: #ffffff;
  color: #1f2937;
}
.resume-template.azurill-template .azurill-layout {
  display: flex;
  min-height: 100%;
}
.resume-template.azurill-template .azurill-sidebar {
  width: 32%;
  flex-shrink: 0;
  background: #1e40af;
  color: #f1f5f9;
  padding: calc(var(--margin) * 0.75) calc(var(--margin) * 0.5);
}
.resume-template.azurill-template .azurill-main {
  flex: 1;
  min-width: 0;
  padding: var(--margin);
}

/* ── 侧栏内部 ── */
.resume-template.azurill-template .azurill-sidebar .module { margin-bottom: 20px; }
.resume-template.azurill-template .azurill-sidebar .module-title {
  color: #f1f5f9;
  font-size: calc(var(--font-size) * 1.02);
  font-weight: 700;
  letter-spacing: 1px;
  margin-bottom: 8px;
  padding-bottom: 5px;
  border-bottom: 2px solid rgba(255, 255, 255, 0.25);
}
.resume-template.azurill-template .azurill-sidebar .module-title::after { display: none; }
.resume-template.azurill-template .azurill-sidebar .module-content { padding-left: 0; }
.resume-template.azurill-template .azurill-sidebar .basic-name {
  color: #f1f5f9;
  font-size: calc(var(--font-size) * 1.7);
  letter-spacing: 2px;
  margin-bottom: 4px;
}
.resume-template.azurill-template .azurill-sidebar .basic-job-title {
  color: var(--accent-color);
  font-weight: 600;
  margin-bottom: 8px;
}
.resume-template.azurill-template .azurill-sidebar .basic-contact,
.resume-template.azurill-template .azurill-sidebar .basic-summary,
.resume-template.azurill-template .azurill-sidebar .basic-links,
.resume-template.azurill-template .azurill-sidebar .interests,
.resume-template.azurill-template .azurill-sidebar .social-links,
.resume-template.azurill-template .azurill-sidebar .lang-item,
.resume-template.azurill-template .azurill-sidebar .cert-item,
.resume-template.azurill-template .azurill-sidebar .honor-item,
.resume-template.azurill-template .azurill-sidebar .rec-item,
.resume-template.azurill-template .azurill-sidebar .fallback-row {
  color: #f1f5f9;
  opacity: 0.92;
  font-size: calc(var(--font-size) * 0.92);
  line-height: 1.8;
}
.resume-template.azurill-template .azurill-sidebar .basic-contact span { display: block; }
.resume-template.azurill-template .azurill-sidebar .basic-header { margin-bottom: 6px; padding-bottom: 6px; }
.resume-template.azurill-template .azurill-sidebar .basic-links a { color: var(--accent-color); }
.resume-template.azurill-template .azurill-sidebar .skill-cat { display: block; margin-bottom: 9px; }
.resume-template.azurill-template .azurill-sidebar .skill-name {
  color: #f1f5f9;
  font-weight: 600;
  display: block;
  margin-bottom: 4px;
  opacity: 0.85;
  min-width: 0;
}
.resume-template.azurill-template .azurill-sidebar .skill-item {
  display: inline-block;
  color: #f1f5f9;
  background: rgba(255, 255, 255, 0.14);
  border: none;
  border-radius: 999px;
  padding: 1px 9px;
  margin: 2px 4px 2px 0;
  font-size: calc(var(--font-size) * 0.85);
}

/* ── 主栏 ── */
.resume-template.azurill-template .azurill-main .module { margin-bottom: var(--section-spacing); }
.resume-template.azurill-template .azurill-main .module-title {
  font-size: calc(var(--font-size) * 1.08);
  color: #1f2937;
}
.resume-template.azurill-template .azurill-main .edu-school,
.resume-template.azurill-template .azurill-main .work-company,
.resume-template.azurill-template .azurill-main .proj-name,
.resume-template.azurill-template .azurill-main .club-name,
.resume-template.azurill-template .azurill-main .skill-name,
.resume-template.azurill-template .azurill-main .fallback-key,
.resume-template.azurill-template .azurill-main .other-title,
.resume-template.azurill-template .azurill-main .custom-title,
.resume-template.azurill-template .azurill-main .pub-title { color: #1f2937; }


/* 共享文字色 */
.resume-template.azurill-template .basic-summary, .resume-template.azurill-template .basic-contact, .resume-template.azurill-template .basic-links, .resume-template.azurill-template .basic-custom-fields
.resume-template.azurill-template .work-desc, .resume-template.azurill-template .proj-desc, .resume-template.azurill-template .edu-desc, .resume-template.azurill-template .club-desc
.resume-template.azurill-template .work-achievements, .resume-template.azurill-template .lang-item, .resume-template.azurill-template .cert-item, .resume-template.azurill-template .honor-item, .resume-template.azurill-template .rec-item
.resume-template.azurill-template .interests, .resume-template.azurill-template .social-link, .resume-template.azurill-template .social-links, .resume-template.azurill-template .other-content, .resume-template.azurill-template .custom-content
.resume-template.azurill-template .pub-authors, .resume-template.azurill-template .proj-tech, .resume-template.azurill-template .fallback-row { color: #6b7280; }
.resume-template.azurill-template .edu-date, .resume-template.azurill-template .work-date, .resume-template.azurill-template .proj-date, .resume-template.azurill-template .club-date
.resume-template.azurill-template .honor-date, .resume-template.azurill-template .rec-contact, .resume-template.azurill-template .pub-info { color: #6b7280; opacity: 0.75; }

.resume-template.azurill-template .module-title::after { display: none; }

.resume-template.azurill-template .skill-item { display:inline-block; background:rgba(15,23,42,0.05); border:1px solid rgba(15,23,42,0.12); color:var(--accent-color); border-radius:4px; padding:1px 8px; margin:2px 4px 2px 0; font-size:calc(var(--font-size) * 0.92); }

/* 主栏时间轴 */
.resume-template.azurill-template .azurill-main .module-education .module-content, .resume-template.azurill-template .azurill-main .module-work_experience .module-content, .resume-template.azurill-template .azurill-main .module-project_experience .module-content, .resume-template.azurill-template .azurill-main .module-club_activities .module-content { position:relative; padding-left:20px; }
.resume-template.azurill-template .azurill-main .module-education .module-content::before, .resume-template.azurill-template .azurill-main .module-work_experience .module-content::before, .resume-template.azurill-template .azurill-main .module-project_experience .module-content::before, .resume-template.azurill-template .azurill-main .module-club_activities .module-content::before { content:""; position:absolute; left:7px; top:4px; bottom:4px; width:1px; background:var(--accent-color); opacity:0.35; }
.resume-template.azurill-template .azurill-main .module-education .edu-item, .resume-template.azurill-template .azurill-main .module-work_experience .work-item, .resume-template.azurill-template .azurill-main .module-project_experience .proj-item, .resume-template.azurill-template .azurill-main .module-club_activities .club-item { position:relative; }
.resume-template.azurill-template .azurill-main .module-education .edu-item::before, .resume-template.azurill-template .azurill-main .module-work_experience .work-item::before, .resume-template.azurill-template .azurill-main .module-project_experience .proj-item::before, .resume-template.azurill-template .azurill-main .module-club_activities .club-item::before { content:""; position:absolute; left:-17px; top:6px; width:9px; height:9px; border-radius:50%; background:#ffffff; border:2px solid var(--accent-color); }
`;

export default function AzurillTemplate({
  modules,
  interactive,
  onSelectSection,
}: TemplateComponentProps) {
  const sidebar = modules.filter((m) => SIDEBAR_TYPES.has(m.module_type));
  const main = modules.filter((m) => !SIDEBAR_TYPES.has(m.module_type));
  const opts = { interactive, onSelectSection };

  return (
    <div className="resume-template azurill-template">
      <style>{TEMPLATE_BASE_STYLES + STYLES}</style>
      <div className="azurill-layout">
        {sidebar.length > 0 && (
          <div className="azurill-sidebar" style={main.length === 0 ? { width: "100%" } : undefined}>
            {sidebar.map((mod) => renderSection(mod, opts))}
          </div>
        )}
        {main.length > 0 && (
          <div className="azurill-main">
            {main.map((mod) => renderSection(mod, opts))}
          </div>
        )}
      </div>
    </div>
  );
}
