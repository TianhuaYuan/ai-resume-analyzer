/**
 * 卡片现代 模板 — 浅灰底 + 白卡片模块，现代轻盈（Magic ditto × RR lapras）
 *
 * 由 scripts/generate-templates/generate.mjs 生成，请勿手改。
 */

import { TEMPLATE_BASE_STYLES } from "../shared/templateBaseStyles";
import { renderSection } from "../shared/renderSection";
import type { TemplateComponentProps } from "../registry";

const STYLES = `
/* ── cards 布局：浅色页底 + 白色卡片模块。根 padding = var(--margin) ── */
.resume-template.ditto-template {
  padding: var(--margin);
  background: #f9fafb;
  color: #1f2937;
}
.resume-template.ditto-template .resume-container { width: 100%; }

/* 每个 .module 呈现为独立卡片 */
.resume-template.ditto-template .module {
  background: #ffffff;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  padding: 16px 20px;
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.06);
}
.resume-template.ditto-template .module-title {
  font-size: calc(var(--font-size) * 1.1);
  color: #1f2937;
}

.resume-template.ditto-template .basic-header { margin-bottom: 4px; padding-bottom: 8px; }
.resume-template.ditto-template .basic-name {
  color: #1f2937;
  font-size: calc(var(--font-size) * 1.8);
  letter-spacing: 1px;
}
.resume-template.ditto-template .basic-job-title { font-weight: 600; }

.resume-template.ditto-template .edu-school,
.resume-template.ditto-template .work-company,
.resume-template.ditto-template .proj-name,
.resume-template.ditto-template .club-name,
.resume-template.ditto-template .skill-name,
.resume-template.ditto-template .fallback-key,
.resume-template.ditto-template .other-title,
.resume-template.ditto-template .custom-title,
.resume-template.ditto-template .pub-title { color: #1f2937; }


/* 共享文字色 */
.resume-template.ditto-template .basic-summary, .resume-template.ditto-template .basic-contact, .resume-template.ditto-template .basic-links, .resume-template.ditto-template .basic-custom-fields
.resume-template.ditto-template .work-desc, .resume-template.ditto-template .proj-desc, .resume-template.ditto-template .edu-desc, .resume-template.ditto-template .club-desc
.resume-template.ditto-template .work-achievements, .resume-template.ditto-template .lang-item, .resume-template.ditto-template .cert-item, .resume-template.ditto-template .honor-item, .resume-template.ditto-template .rec-item
.resume-template.ditto-template .interests, .resume-template.ditto-template .social-link, .resume-template.ditto-template .social-links, .resume-template.ditto-template .other-content, .resume-template.ditto-template .custom-content
.resume-template.ditto-template .pub-authors, .resume-template.ditto-template .proj-tech, .resume-template.ditto-template .fallback-row { color: #6b7280; }
.resume-template.ditto-template .edu-date, .resume-template.ditto-template .work-date, .resume-template.ditto-template .proj-date, .resume-template.ditto-template .club-date
.resume-template.ditto-template .honor-date, .resume-template.ditto-template .rec-contact, .resume-template.ditto-template .pub-info { color: #6b7280; opacity: 0.75; }

.resume-template.ditto-template .basic-header::after { content:""; display:block; width:52px; height:3px; background:var(--accent-color); border-radius:2px; margin-top:10px; }

.resume-template.ditto-template .module-title::after { display: none; }

.resume-template.ditto-template .skill-item { display:inline-block; background:rgba(15,23,42,0.06); border:none; color:var(--accent-color); border-radius:999px; padding:2px 12px; margin:2px 6px 2px 0; font-size:calc(var(--font-size) * 0.92); }
`;

export default function DittoTemplate({
  modules,
  interactive,
  onSelectSection,
}: TemplateComponentProps) {
  return (
    <div className="resume-template ditto-template">
      <style>{TEMPLATE_BASE_STYLES + STYLES}</style>
      <div className="resume-container">
        {modules.map((mod) => renderSection(mod, { interactive, onSelectSection }))}
      </div>
    </div>
  );
}
