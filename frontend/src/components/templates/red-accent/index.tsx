/**
 * 红色强调 模板 — 红色强调线 + 干净单栏，醒目现代（Magic red-accent）
 *
 * 由 scripts/generate-templates/generate.mjs 生成，请勿手改。
 */

import { TEMPLATE_BASE_STYLES } from "../shared/templateBaseStyles";
import { renderSection } from "../shared/renderSection";
import type { TemplateComponentProps } from "../registry";

const STYLES = `
/* ── single 布局：单栏，根 padding = var(--margin)(分页测量依赖) ── */
.resume-template.red-accent-template {
  padding: var(--margin);
  background: #ffffff;
  color: #1f2937;
}
.resume-template.red-accent-template .resume-container { width: 100%; }

.resume-template.red-accent-template .basic-header {
  padding-bottom: 16px;
  margin-bottom: var(--section-spacing);
}
.resume-template.red-accent-template .basic-name {
  color: #1f2937;
  font-size: calc(var(--font-size) * 1.9);
  letter-spacing: 1px;
}
.resume-template.red-accent-template .basic-job-title {
  font-weight: 700;
  margin-top: 4px;
}

.resume-template.red-accent-template .module-title {
  font-size: calc(var(--font-size) * 1.12);
  color: #1f2937;
}
.resume-template.red-accent-template .module-content { padding-left: 2px; }

/* 头部主标题/条目标题统一用 #1f2937 */
.resume-template.red-accent-template .edu-school,
.resume-template.red-accent-template .work-company,
.resume-template.red-accent-template .proj-name,
.resume-template.red-accent-template .club-name,
.resume-template.red-accent-template .skill-name,
.resume-template.red-accent-template .fallback-key,
.resume-template.red-accent-template .other-title,
.resume-template.red-accent-template .custom-title,
.resume-template.red-accent-template .pub-title { color: #1f2937; }


/* 共享文字色 */
.resume-template.red-accent-template .basic-summary, .resume-template.red-accent-template .basic-contact, .resume-template.red-accent-template .basic-links, .resume-template.red-accent-template .basic-custom-fields
.resume-template.red-accent-template .work-desc, .resume-template.red-accent-template .proj-desc, .resume-template.red-accent-template .edu-desc, .resume-template.red-accent-template .club-desc
.resume-template.red-accent-template .work-achievements, .resume-template.red-accent-template .lang-item, .resume-template.red-accent-template .cert-item, .resume-template.red-accent-template .honor-item, .resume-template.red-accent-template .rec-item
.resume-template.red-accent-template .interests, .resume-template.red-accent-template .social-link, .resume-template.red-accent-template .social-links, .resume-template.red-accent-template .other-content, .resume-template.red-accent-template .custom-content
.resume-template.red-accent-template .pub-authors, .resume-template.red-accent-template .proj-tech, .resume-template.red-accent-template .fallback-row { color: #6b7280; }
.resume-template.red-accent-template .edu-date, .resume-template.red-accent-template .work-date, .resume-template.red-accent-template .proj-date, .resume-template.red-accent-template .club-date
.resume-template.red-accent-template .honor-date, .resume-template.red-accent-template .rec-contact, .resume-template.red-accent-template .pub-info { color: #6b7280; opacity: 0.75; }

.resume-template.red-accent-template .basic-header::after { content:""; display:block; width:52px; height:3px; background:var(--accent-color); border-radius:2px; margin-top:10px; }

.resume-template.red-accent-template .skill-item { display:inline-block; background:rgba(15,23,42,0.05); border:1px solid rgba(15,23,42,0.12); color:var(--accent-color); border-radius:4px; padding:1px 8px; margin:2px 4px 2px 0; font-size:calc(var(--font-size) * 0.92); }
`;

export default function RedAccentTemplate({
  modules,
  interactive,
  onSelectSection,
}: TemplateComponentProps) {
  return (
    <div className="resume-template red-accent-template">
      <style>{TEMPLATE_BASE_STYLES + STYLES}</style>
      <div className="resume-container">
        {modules.map((mod) => renderSection(mod, { interactive, onSelectSection }))}
      </div>
    </div>
  );
}
