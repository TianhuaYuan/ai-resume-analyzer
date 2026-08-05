/**
 * 深板岩侧栏 模板 — 深灰侧栏 + 蓝色强调 + 主栏时间轴，沉稳技术风（Magic slate-sidebar × RR gengar）
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
.resume-template.slate-template {
  background: #ffffff;
  color: #0f172a;
}
.resume-template.slate-template .slate-layout {
  display: flex;
  min-height: 100%;
}
.resume-template.slate-template .slate-sidebar {
  width: 30%;
  flex-shrink: 0;
  background: #1e293b;
  color: #f1f5f9;
  padding: calc(var(--margin) * 0.75) calc(var(--margin) * 0.5);
}
.resume-template.slate-template .slate-main {
  flex: 1;
  min-width: 0;
  padding: var(--margin);
}

/* ── 侧栏内部 ── */
.resume-template.slate-template .slate-sidebar .module { margin-bottom: 20px; }
.resume-template.slate-template .slate-sidebar .module-title {
  color: #f1f5f9;
  font-size: calc(var(--font-size) * 1.02);
  font-weight: 700;
  letter-spacing: 1px;
  margin-bottom: 8px;
  padding-bottom: 5px;
  border-bottom: 2px solid rgba(255, 255, 255, 0.25);
}
.resume-template.slate-template .slate-sidebar .module-title::after { display: none; }
.resume-template.slate-template .slate-sidebar .module-content { padding-left: 0; }
.resume-template.slate-template .slate-sidebar .basic-name {
  color: #f1f5f9;
  font-size: calc(var(--font-size) * 1.7);
  letter-spacing: 2px;
  margin-bottom: 4px;
}
.resume-template.slate-template .slate-sidebar .basic-job-title {
  color: var(--accent-color);
  font-weight: 600;
  margin-bottom: 8px;
}
.resume-template.slate-template .slate-sidebar .basic-contact,
.resume-template.slate-template .slate-sidebar .basic-summary,
.resume-template.slate-template .slate-sidebar .basic-links,
.resume-template.slate-template .slate-sidebar .interests,
.resume-template.slate-template .slate-sidebar .social-links,
.resume-template.slate-template .slate-sidebar .lang-item,
.resume-template.slate-template .slate-sidebar .cert-item,
.resume-template.slate-template .slate-sidebar .honor-item,
.resume-template.slate-template .slate-sidebar .rec-item,
.resume-template.slate-template .slate-sidebar .fallback-row {
  color: #f1f5f9;
  opacity: 0.92;
  font-size: calc(var(--font-size) * 0.92);
  line-height: 1.8;
}
.resume-template.slate-template .slate-sidebar .basic-contact span { display: block; }
.resume-template.slate-template .slate-sidebar .basic-header { margin-bottom: 6px; padding-bottom: 6px; }
.resume-template.slate-template .slate-sidebar .basic-links a { color: var(--accent-color); }
.resume-template.slate-template .slate-sidebar .skill-cat { display: block; margin-bottom: 9px; }
.resume-template.slate-template .slate-sidebar .skill-name {
  color: #f1f5f9;
  font-weight: 600;
  display: block;
  margin-bottom: 4px;
  opacity: 0.85;
  min-width: 0;
}
.resume-template.slate-template .slate-sidebar .skill-item {
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
.resume-template.slate-template .slate-main .module { margin-bottom: var(--section-spacing); }
.resume-template.slate-template .slate-main .module-title {
  font-size: calc(var(--font-size) * 1.08);
  color: #0f172a;
}
.resume-template.slate-template .slate-main .edu-school,
.resume-template.slate-template .slate-main .work-company,
.resume-template.slate-template .slate-main .proj-name,
.resume-template.slate-template .slate-main .club-name,
.resume-template.slate-template .slate-main .skill-name,
.resume-template.slate-template .slate-main .fallback-key,
.resume-template.slate-template .slate-main .other-title,
.resume-template.slate-template .slate-main .custom-title,
.resume-template.slate-template .slate-main .pub-title { color: #0f172a; }


/* 共享文字色 */
.resume-template.slate-template .basic-summary, .resume-template.slate-template .basic-contact, .resume-template.slate-template .basic-links, .resume-template.slate-template .basic-custom-fields
.resume-template.slate-template .work-desc, .resume-template.slate-template .proj-desc, .resume-template.slate-template .edu-desc, .resume-template.slate-template .club-desc
.resume-template.slate-template .work-achievements, .resume-template.slate-template .lang-item, .resume-template.slate-template .cert-item, .resume-template.slate-template .honor-item, .resume-template.slate-template .rec-item
.resume-template.slate-template .interests, .resume-template.slate-template .social-link, .resume-template.slate-template .social-links, .resume-template.slate-template .other-content, .resume-template.slate-template .custom-content
.resume-template.slate-template .pub-authors, .resume-template.slate-template .proj-tech, .resume-template.slate-template .fallback-row { color: #475569; }
.resume-template.slate-template .edu-date, .resume-template.slate-template .work-date, .resume-template.slate-template .proj-date, .resume-template.slate-template .club-date
.resume-template.slate-template .honor-date, .resume-template.slate-template .rec-contact, .resume-template.slate-template .pub-info { color: #475569; opacity: 0.75; }

.resume-template.slate-template .skill-item { display:inline-block; background:rgba(15,23,42,0.05); border:1px solid rgba(15,23,42,0.12); color:var(--accent-color); border-radius:4px; padding:1px 8px; margin:2px 4px 2px 0; font-size:calc(var(--font-size) * 0.92); }

/* 主栏时间轴 */
.resume-template.slate-template .slate-main .module-education .module-content, .resume-template.slate-template .slate-main .module-work_experience .module-content, .resume-template.slate-template .slate-main .module-project_experience .module-content, .resume-template.slate-template .slate-main .module-club_activities .module-content { position:relative; padding-left:20px; }
.resume-template.slate-template .slate-main .module-education .module-content::before, .resume-template.slate-template .slate-main .module-work_experience .module-content::before, .resume-template.slate-template .slate-main .module-project_experience .module-content::before, .resume-template.slate-template .slate-main .module-club_activities .module-content::before { content:""; position:absolute; left:7px; top:4px; bottom:4px; width:1px; background:var(--accent-color); opacity:0.35; }
.resume-template.slate-template .slate-main .module-education .edu-item, .resume-template.slate-template .slate-main .module-work_experience .work-item, .resume-template.slate-template .slate-main .module-project_experience .proj-item, .resume-template.slate-template .slate-main .module-club_activities .club-item { position:relative; }
.resume-template.slate-template .slate-main .module-education .edu-item::before, .resume-template.slate-template .slate-main .module-work_experience .work-item::before, .resume-template.slate-template .slate-main .module-project_experience .proj-item::before, .resume-template.slate-template .slate-main .module-club_activities .club-item::before { content:""; position:absolute; left:-17px; top:6px; width:9px; height:9px; border-radius:50%; background:#ffffff; border:2px solid var(--accent-color); }
`;

export default function SlateTemplate({
  modules,
  interactive,
  onSelectSection,
}: TemplateComponentProps) {
  const sidebar = modules.filter((m) => SIDEBAR_TYPES.has(m.module_type));
  const main = modules.filter((m) => !SIDEBAR_TYPES.has(m.module_type));
  const opts = { interactive, onSelectSection };

  return (
    <div className="resume-template slate-template">
      <style>{TEMPLATE_BASE_STYLES + STYLES}</style>
      <div className="slate-layout">
        <div className="slate-sidebar">
          {sidebar.map((mod) => renderSection(mod, opts))}
        </div>
        <div className="slate-main">
          {main.map((mod) => renderSection(mod, opts))}
        </div>
      </div>
    </div>
  );
}
