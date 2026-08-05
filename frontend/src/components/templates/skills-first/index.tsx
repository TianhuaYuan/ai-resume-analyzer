/**
 * 技能聚焦 模板 — 勃艮第强调 + 技能胶囊，成果导向（Magic skills-first）
 *
 * 由 scripts/generate-templates/generate.mjs 生成，请勿手改。
 */

import { TEMPLATE_BASE_STYLES } from "../shared/templateBaseStyles";
import { renderSection } from "../shared/renderSection";
import type { TemplateComponentProps } from "../registry";

const STYLES = `
/* ── single 布局：单栏，根 padding = var(--margin)(分页测量依赖) ── */
.resume-template.skills-first-template {
  padding: var(--margin);
  background: #ffffff;
  color: #1f2937;
}
.resume-template.skills-first-template .resume-container { width: 100%; }

.resume-template.skills-first-template .basic-header {
  padding-bottom: 16px;
  margin-bottom: var(--section-spacing);
}
.resume-template.skills-first-template .basic-name {
  color: #1f2937;
  font-size: calc(var(--font-size) * 1.8);
  letter-spacing: 1px;
}
.resume-template.skills-first-template .basic-job-title {
  font-weight: 700;
  margin-top: 4px;
}

.resume-template.skills-first-template .module-title {
  font-size: calc(var(--font-size) * 1.12);
  color: #1f2937;
}
.resume-template.skills-first-template .module-content { padding-left: 2px; }

/* 头部主标题/条目标题统一用 #1f2937 */
.resume-template.skills-first-template .edu-school,
.resume-template.skills-first-template .work-company,
.resume-template.skills-first-template .proj-name,
.resume-template.skills-first-template .club-name,
.resume-template.skills-first-template .skill-name,
.resume-template.skills-first-template .fallback-key,
.resume-template.skills-first-template .other-title,
.resume-template.skills-first-template .custom-title,
.resume-template.skills-first-template .pub-title { color: #1f2937; }


/* 共享文字色 */
.resume-template.skills-first-template .basic-summary, .resume-template.skills-first-template .basic-contact, .resume-template.skills-first-template .basic-links, .resume-template.skills-first-template .basic-custom-fields
.resume-template.skills-first-template .work-desc, .resume-template.skills-first-template .proj-desc, .resume-template.skills-first-template .edu-desc, .resume-template.skills-first-template .club-desc
.resume-template.skills-first-template .work-achievements, .resume-template.skills-first-template .lang-item, .resume-template.skills-first-template .cert-item, .resume-template.skills-first-template .honor-item, .resume-template.skills-first-template .rec-item
.resume-template.skills-first-template .interests, .resume-template.skills-first-template .social-link, .resume-template.skills-first-template .social-links, .resume-template.skills-first-template .other-content, .resume-template.skills-first-template .custom-content
.resume-template.skills-first-template .pub-authors, .resume-template.skills-first-template .proj-tech, .resume-template.skills-first-template .fallback-row { color: #6b7280; }
.resume-template.skills-first-template .edu-date, .resume-template.skills-first-template .work-date, .resume-template.skills-first-template .proj-date, .resume-template.skills-first-template .club-date
.resume-template.skills-first-template .honor-date, .resume-template.skills-first-template .rec-contact, .resume-template.skills-first-template .pub-info { color: #6b7280; opacity: 0.75; }

.resume-template.skills-first-template .basic-header::after { content:""; display:block; width:52px; height:3px; background:var(--accent-color); border-radius:2px; margin-top:10px; }

.resume-template.skills-first-template .skill-item { display:inline-block; background:rgba(15,23,42,0.06); border:none; color:var(--accent-color); border-radius:999px; padding:2px 12px; margin:2px 6px 2px 0; font-size:calc(var(--font-size) * 0.92); }
`;

export default function SkillsFirstTemplate({
  modules,
  interactive,
  onSelectSection,
}: TemplateComponentProps) {
  return (
    <div className="resume-template skills-first-template">
      <style>{TEMPLATE_BASE_STYLES + STYLES}</style>
      <div className="resume-container">
        {modules.map((mod) => renderSection(mod, { interactive, onSelectSection }))}
      </div>
    </div>
  );
}
