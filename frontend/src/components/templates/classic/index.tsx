/**
 * 经典衬线 模板 — 衬线经典排版，学术/正式岗位首选（Magic classic）
 *
 * 由 scripts/generate-templates/generate.mjs 生成，请勿手改。
 */

import { TEMPLATE_BASE_STYLES } from "../shared/templateBaseStyles";
import { renderSection } from "../shared/renderSection";
import type { TemplateComponentProps } from "../registry";

const STYLES = `
/* ── single 布局：单栏，根 padding = var(--margin)(分页测量依赖) ── */
.resume-template.classic-template {
  padding: var(--margin);
  background: #ffffff;
  color: #000000;
}
.resume-template.classic-template .resume-container { width: 100%; }

.resume-template.classic-template .basic-header {
  padding-bottom: 16px;
  margin-bottom: var(--section-spacing);
}
.resume-template.classic-template .basic-name {
  color: #000000;
  font-size: calc(var(--font-size) * 1.9);
  letter-spacing: 1px;
}
.resume-template.classic-template .basic-job-title {
  font-weight: 600;
  margin-top: 4px;
}

.resume-template.classic-template .module-title {
  font-size: calc(var(--font-size) * 1.12);
  color: #000000;
}
.resume-template.classic-template .module-content { padding-left: 2px; }

/* 头部主标题/条目标题统一用 #000000 */
.resume-template.classic-template .edu-school,
.resume-template.classic-template .work-company,
.resume-template.classic-template .proj-name,
.resume-template.classic-template .club-name,
.resume-template.classic-template .skill-name,
.resume-template.classic-template .fallback-key,
.resume-template.classic-template .other-title,
.resume-template.classic-template .custom-title,
.resume-template.classic-template .pub-title { color: #000000; }


/* 共享文字色 */
.resume-template.classic-template .basic-summary, .resume-template.classic-template .basic-contact, .resume-template.classic-template .basic-links, .resume-template.classic-template .basic-custom-fields
.resume-template.classic-template .work-desc, .resume-template.classic-template .proj-desc, .resume-template.classic-template .edu-desc, .resume-template.classic-template .club-desc
.resume-template.classic-template .work-achievements, .resume-template.classic-template .lang-item, .resume-template.classic-template .cert-item, .resume-template.classic-template .honor-item, .resume-template.classic-template .rec-item
.resume-template.classic-template .interests, .resume-template.classic-template .social-link, .resume-template.classic-template .social-links, .resume-template.classic-template .other-content, .resume-template.classic-template .custom-content
.resume-template.classic-template .pub-authors, .resume-template.classic-template .proj-tech, .resume-template.classic-template .fallback-row { color: #666666; }
.resume-template.classic-template .edu-date, .resume-template.classic-template .work-date, .resume-template.classic-template .proj-date, .resume-template.classic-template .club-date
.resume-template.classic-template .honor-date, .resume-template.classic-template .rec-contact, .resume-template.classic-template .pub-info { color: #666666; opacity: 0.75; }

.resume-template.classic-template .basic-header::after { content:""; display:block; width:52px; height:3px; background:var(--accent-color); border-radius:2px; margin-top:10px; }

.resume-template.classic-template .module-title { border-bottom: 2px solid #cccccc; padding-bottom: 4px; }
.resume-template.classic-template .module-title::after { display: none; }

.resume-template.classic-template .skill-item { display:inline-block; background:none; border:none; color:#000000; border-radius:0; padding:0; margin:0 8px 0 0; font-size:calc(var(--font-size) * 0.95); }
`;

export default function ClassicTemplate({
  modules,
  interactive,
  onSelectSection,
}: TemplateComponentProps) {
  return (
    <div className="resume-template classic-template">
      <style>{TEMPLATE_BASE_STYLES + STYLES}</style>
      <div className="resume-container">
        {modules.map((mod) => renderSection(mod, { interactive, onSelectSection }))}
      </div>
    </div>
  );
}
