/**
 * 青绿时间轴 模板 — 单栏时间轴 + 节点圆点，突出职业轨迹（Magic timeline-pro × RR azurill）
 *
 * 由 scripts/generate-templates/generate.mjs 生成，请勿手改。
 */

import { TEMPLATE_BASE_STYLES } from "../shared/templateBaseStyles";
import { renderSection } from "../shared/renderSection";
import type { TemplateComponentProps } from "../registry";

const STYLES = `
/* ── timeline 布局：单栏 + 经历时间轴(竖线 + 节点圆点)。根 padding = var(--margin) ── */
.resume-template.timeline-pro-template {
  padding: var(--margin);
  background: #ffffff;
  color: #0f172a;
}
.resume-template.timeline-pro-template .resume-container { width: 100%; }

.resume-template.timeline-pro-template .basic-header { padding-bottom: 16px; margin-bottom: var(--section-spacing); }
.resume-template.timeline-pro-template .basic-name {
  color: #0f172a;
  font-size: calc(var(--font-size) * 1.8);
  letter-spacing: 1px;
}
.resume-template.timeline-pro-template .basic-job-title { font-weight: 600; }

/* 仅经历类模块(main 四大类)启用时间轴 */
.resume-template.timeline-pro-template .module-education .module-content,
.resume-template.timeline-pro-template .module-work_experience .module-content,
.resume-template.timeline-pro-template .module-project_experience .module-content,
.resume-template.timeline-pro-template .module-club_activities .module-content {
  position: relative;
  padding-left: 20px;
}
.resume-template.timeline-pro-template .module-education .module-content::before,
.resume-template.timeline-pro-template .module-work_experience .module-content::before,
.resume-template.timeline-pro-template .module-project_experience .module-content::before,
.resume-template.timeline-pro-template .module-club_activities .module-content::before {
  content: "";
  position: absolute;
  left: 7px;
  top: 4px;
  bottom: 4px;
  width: 1px;
  background: var(--accent-color);
  opacity: 0.35;
}
.resume-template.timeline-pro-template .module-education .edu-item,
.resume-template.timeline-pro-template .module-work_experience .work-item,
.resume-template.timeline-pro-template .module-project_experience .proj-item,
.resume-template.timeline-pro-template .module-club_activities .club-item {
  position: relative;
}
.resume-template.timeline-pro-template .module-education .edu-item::before,
.resume-template.timeline-pro-template .module-work_experience .work-item::before,
.resume-template.timeline-pro-template .module-project_experience .proj-item::before,
.resume-template.timeline-pro-template .module-club_activities .club-item::before {
  content: "";
  position: absolute;
  left: -17px;
  top: 6px;
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: #ffffff;
  border: 2px solid var(--accent-color);
}

.resume-template.timeline-pro-template .module-title {
  font-size: calc(var(--font-size) * 1.1);
  color: #0f172a;
}
.resume-template.timeline-pro-template .edu-school,
.resume-template.timeline-pro-template .work-company,
.resume-template.timeline-pro-template .proj-name,
.resume-template.timeline-pro-template .club-name,
.resume-template.timeline-pro-template .skill-name,
.resume-template.timeline-pro-template .fallback-key,
.resume-template.timeline-pro-template .other-title,
.resume-template.timeline-pro-template .custom-title,
.resume-template.timeline-pro-template .pub-title { color: #0f172a; }


/* 共享文字色 */
.resume-template.timeline-pro-template .basic-summary, .resume-template.timeline-pro-template .basic-contact, .resume-template.timeline-pro-template .basic-links, .resume-template.timeline-pro-template .basic-custom-fields
.resume-template.timeline-pro-template .work-desc, .resume-template.timeline-pro-template .proj-desc, .resume-template.timeline-pro-template .edu-desc, .resume-template.timeline-pro-template .club-desc
.resume-template.timeline-pro-template .work-achievements, .resume-template.timeline-pro-template .lang-item, .resume-template.timeline-pro-template .cert-item, .resume-template.timeline-pro-template .honor-item, .resume-template.timeline-pro-template .rec-item
.resume-template.timeline-pro-template .interests, .resume-template.timeline-pro-template .social-link, .resume-template.timeline-pro-template .social-links, .resume-template.timeline-pro-template .other-content, .resume-template.timeline-pro-template .custom-content
.resume-template.timeline-pro-template .pub-authors, .resume-template.timeline-pro-template .proj-tech, .resume-template.timeline-pro-template .fallback-row { color: #4b5563; }
.resume-template.timeline-pro-template .edu-date, .resume-template.timeline-pro-template .work-date, .resume-template.timeline-pro-template .proj-date, .resume-template.timeline-pro-template .club-date
.resume-template.timeline-pro-template .honor-date, .resume-template.timeline-pro-template .rec-contact, .resume-template.timeline-pro-template .pub-info { color: #4b5563; opacity: 0.75; }

.resume-template.timeline-pro-template .basic-header::after { content:""; display:block; width:52px; height:3px; background:var(--accent-color); border-radius:2px; margin-top:10px; }

.resume-template.timeline-pro-template .module-title::after { display: none; }

.resume-template.timeline-pro-template .skill-item { display:inline-block; background:rgba(15,23,42,0.05); border:1px solid rgba(15,23,42,0.12); color:var(--accent-color); border-radius:4px; padding:1px 8px; margin:2px 4px 2px 0; font-size:calc(var(--font-size) * 0.92); }
`;

export default function TimelineProTemplate({
  modules,
  interactive,
  onSelectSection,
}: TemplateComponentProps) {
  return (
    <div className="resume-template timeline-pro-template">
      <style>{TEMPLATE_BASE_STYLES + STYLES}</style>
      <div className="resume-container">
        {modules.map((mod) => renderSection(mod, { interactive, onSelectSection }))}
      </div>
    </div>
  );
}
