/**
 * 中文正装 模板 — 中文正式单栏，蓝色沉稳，适合国企/事业单位（Magic cn-formal-photo）
 *
 * 由 scripts/generate-templates/generate.mjs 生成，请勿手改。
 */

import { TEMPLATE_BASE_STYLES } from "../shared/templateBaseStyles";
import { renderSection } from "../shared/renderSection";
import type { TemplateComponentProps } from "../registry";

const STYLES = `
/* ── single 布局：单栏，根 padding = var(--margin)(分页测量依赖) ── */
.resume-template.cn-formal-template {
  padding: var(--margin);
  background: #ffffff;
  color: #111827;
}
.resume-template.cn-formal-template .resume-container { width: 100%; }

.resume-template.cn-formal-template .basic-header {
  padding-bottom: 16px;
  margin-bottom: var(--section-spacing);
}
.resume-template.cn-formal-template .basic-name {
  color: #111827;
  font-size: calc(var(--font-size) * 1.8);
  letter-spacing: 1px;
}
.resume-template.cn-formal-template .basic-job-title {
  font-weight: 700;
  margin-top: 4px;
}

.resume-template.cn-formal-template .module-title {
  font-size: calc(var(--font-size) * 1.1);
  color: #111827;
}
.resume-template.cn-formal-template .module-content { padding-left: 2px; }

/* 头部主标题/条目标题统一用 #111827 */
.resume-template.cn-formal-template .edu-school,
.resume-template.cn-formal-template .work-company,
.resume-template.cn-formal-template .proj-name,
.resume-template.cn-formal-template .club-name,
.resume-template.cn-formal-template .skill-name,
.resume-template.cn-formal-template .fallback-key,
.resume-template.cn-formal-template .other-title,
.resume-template.cn-formal-template .custom-title,
.resume-template.cn-formal-template .pub-title { color: #111827; }


/* 共享文字色 */
.resume-template.cn-formal-template .basic-summary, .resume-template.cn-formal-template .basic-contact, .resume-template.cn-formal-template .basic-links, .resume-template.cn-formal-template .basic-custom-fields
.resume-template.cn-formal-template .work-desc, .resume-template.cn-formal-template .proj-desc, .resume-template.cn-formal-template .edu-desc, .resume-template.cn-formal-template .club-desc
.resume-template.cn-formal-template .work-achievements, .resume-template.cn-formal-template .lang-item, .resume-template.cn-formal-template .cert-item, .resume-template.cn-formal-template .honor-item, .resume-template.cn-formal-template .rec-item
.resume-template.cn-formal-template .interests, .resume-template.cn-formal-template .social-link, .resume-template.cn-formal-template .social-links, .resume-template.cn-formal-template .other-content, .resume-template.cn-formal-template .custom-content
.resume-template.cn-formal-template .pub-authors, .resume-template.cn-formal-template .proj-tech, .resume-template.cn-formal-template .fallback-row { color: #4b5563; }
.resume-template.cn-formal-template .edu-date, .resume-template.cn-formal-template .work-date, .resume-template.cn-formal-template .proj-date, .resume-template.cn-formal-template .club-date
.resume-template.cn-formal-template .honor-date, .resume-template.cn-formal-template .rec-contact, .resume-template.cn-formal-template .pub-info { color: #4b5563; opacity: 0.75; }

.resume-template.cn-formal-template .basic-header::after { content:""; display:block; width:52px; height:3px; background:var(--accent-color); border-radius:2px; margin-top:10px; }

.resume-template.cn-formal-template .module-title { border-bottom: 2px solid #cbd5e1; padding-bottom: 4px; }
.resume-template.cn-formal-template .module-title::after { display: none; }

.resume-template.cn-formal-template .skill-item { display:inline-block; background:transparent; border:1px solid var(--accent-color); color:var(--accent-color); border-radius:4px; padding:1px 9px; margin:2px 5px 2px 0; font-size:calc(var(--font-size) * 0.92); }
`;

export default function CnFormalTemplate({
  modules,
  interactive,
  onSelectSection,
}: TemplateComponentProps) {
  return (
    <div className="resume-template cn-formal-template">
      <style>{TEMPLATE_BASE_STYLES + STYLES}</style>
      <div className="resume-container">
        {modules.map((mod) => renderSection(mod, { interactive, onSelectSection }))}
      </div>
    </div>
  );
}
