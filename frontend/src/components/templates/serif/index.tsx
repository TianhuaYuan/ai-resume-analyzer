/**
 * 衬线留白 模板 — 衬线字体 + 大留白，Premium 质感，ATS 友好（Magic serif-minimal × RR scizor）
 *
 * 由 scripts/generate-templates/generate.mjs 生成，请勿手改。
 */

import { TEMPLATE_BASE_STYLES } from "../shared/templateBaseStyles";
import { renderSection } from "../shared/renderSection";
import type { TemplateComponentProps } from "../registry";

const STYLES = `
/* ── single 布局：单栏，根 padding = var(--margin)(分页测量依赖) ── */
.resume-template.serif-template {
  padding: var(--margin);
  background: #ffffff;
  color: #111827;
}
.resume-template.serif-template .resume-container { width: 100%; }

.resume-template.serif-template .basic-header {
  padding-bottom: 16px;
  margin-bottom: var(--section-spacing);
}
.resume-template.serif-template .basic-name {
  color: #111827;
  font-size: calc(var(--font-size) * 1.8);
  letter-spacing: 1px;
}
.resume-template.serif-template .basic-job-title {
  font-weight: 600;
  margin-top: 4px;
}

.resume-template.serif-template .module-title {
  font-size: calc(var(--font-size) * 1.1);
  color: #111827;
}
.resume-template.serif-template .module-content { padding-left: 2px; }

/* 头部主标题/条目标题统一用 #111827 */
.resume-template.serif-template .edu-school,
.resume-template.serif-template .work-company,
.resume-template.serif-template .proj-name,
.resume-template.serif-template .club-name,
.resume-template.serif-template .skill-name,
.resume-template.serif-template .fallback-key,
.resume-template.serif-template .other-title,
.resume-template.serif-template .custom-title,
.resume-template.serif-template .pub-title { color: #111827; }


/* 共享文字色 */
.resume-template.serif-template .basic-summary, .resume-template.serif-template .basic-contact, .resume-template.serif-template .basic-links, .resume-template.serif-template .basic-custom-fields
.resume-template.serif-template .work-desc, .resume-template.serif-template .proj-desc, .resume-template.serif-template .edu-desc, .resume-template.serif-template .club-desc
.resume-template.serif-template .work-achievements, .resume-template.serif-template .lang-item, .resume-template.serif-template .cert-item, .resume-template.serif-template .honor-item, .resume-template.serif-template .rec-item
.resume-template.serif-template .interests, .resume-template.serif-template .social-link, .resume-template.serif-template .social-links, .resume-template.serif-template .other-content, .resume-template.serif-template .custom-content
.resume-template.serif-template .pub-authors, .resume-template.serif-template .proj-tech, .resume-template.serif-template .fallback-row { color: #6b7280; }
.resume-template.serif-template .edu-date, .resume-template.serif-template .work-date, .resume-template.serif-template .proj-date, .resume-template.serif-template .club-date
.resume-template.serif-template .honor-date, .resume-template.serif-template .rec-contact, .resume-template.serif-template .pub-info { color: #6b7280; opacity: 0.75; }

.resume-template.serif-template .basic-header::after { content:""; display:block; width:52px; height:3px; background:var(--accent-color); border-radius:2px; margin-top:10px; }

.resume-template.serif-template .skill-item { display:inline-block; background:none; border:none; color:#111827; border-radius:0; padding:0; margin:0 8px 0 0; font-size:calc(var(--font-size) * 0.95); }
`;

export default function SerifTemplate({
  modules,
  interactive,
  onSelectSection,
}: TemplateComponentProps) {
  return (
    <div className="resume-template serif-template">
      <style>{TEMPLATE_BASE_STYLES + STYLES}</style>
      <div className="resume-container">
        {modules.map((mod) => renderSection(mod, { interactive, onSelectSection }))}
      </div>
    </div>
  );
}
