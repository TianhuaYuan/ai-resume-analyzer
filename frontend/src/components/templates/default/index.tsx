/**
 * 经典蓝 模板 — 单栏百搭：左侧强调头 + 蓝色分割，通用性强（默认模板 + 兜底）
 *
 * 由 scripts/generate-templates/generate.mjs 生成，请勿手改。
 */

import { TEMPLATE_BASE_STYLES } from "../shared/templateBaseStyles";
import { renderSection } from "../shared/renderSection";
import type { TemplateComponentProps } from "../registry";

const STYLES = `
/* ── single 布局：单栏，根 padding = var(--margin)(分页测量依赖) ── */
.resume-template.default-template {
  padding: var(--margin);
  background: #ffffff;
  color: #1f2937;
}
.resume-template.default-template .resume-container { width: 100%; }

.resume-template.default-template .basic-header {
  padding-bottom: 16px;
  margin-bottom: var(--section-spacing);
}
.resume-template.default-template .basic-name {
  color: #1f2937;
  font-size: calc(var(--font-size) * 1.9);
  letter-spacing: 1px;
}
.resume-template.default-template .basic-job-title {
  font-weight: 600;
  margin-top: 4px;
}

.resume-template.default-template .module-title {
  font-size: calc(var(--font-size) * 1.12);
  color: #1f2937;
}
.resume-template.default-template .module-content { padding-left: 2px; }

/* 头部主标题/条目标题统一用 #1f2937 */
.resume-template.default-template .edu-school,
.resume-template.default-template .work-company,
.resume-template.default-template .proj-name,
.resume-template.default-template .club-name,
.resume-template.default-template .skill-name,
.resume-template.default-template .fallback-key,
.resume-template.default-template .other-title,
.resume-template.default-template .custom-title,
.resume-template.default-template .pub-title { color: #1f2937; }


/* 共享文字色 */
.resume-template.default-template .basic-summary, .resume-template.default-template .basic-contact, .resume-template.default-template .basic-links, .resume-template.default-template .basic-custom-fields
.resume-template.default-template .work-desc, .resume-template.default-template .proj-desc, .resume-template.default-template .edu-desc, .resume-template.default-template .club-desc
.resume-template.default-template .work-achievements, .resume-template.default-template .lang-item, .resume-template.default-template .cert-item, .resume-template.default-template .honor-item, .resume-template.default-template .rec-item
.resume-template.default-template .interests, .resume-template.default-template .social-link, .resume-template.default-template .social-links, .resume-template.default-template .other-content, .resume-template.default-template .custom-content
.resume-template.default-template .pub-authors, .resume-template.default-template .proj-tech, .resume-template.default-template .fallback-row { color: #6b7280; }
.resume-template.default-template .edu-date, .resume-template.default-template .work-date, .resume-template.default-template .proj-date, .resume-template.default-template .club-date
.resume-template.default-template .honor-date, .resume-template.default-template .rec-contact, .resume-template.default-template .pub-info { color: #6b7280; opacity: 0.75; }

.resume-template.default-template .basic-header::after { content:""; display:block; width:52px; height:3px; background:var(--accent-color); border-radius:2px; margin-top:10px; }

.resume-template.default-template .skill-item { display:inline-block; background:rgba(15,23,42,0.05); border:1px solid rgba(15,23,42,0.12); color:var(--accent-color); border-radius:4px; padding:1px 8px; margin:2px 4px 2px 0; font-size:calc(var(--font-size) * 0.92); }
`;

export default function DefaultTemplate({
  modules,
  interactive,
  onSelectSection,
}: TemplateComponentProps) {
  return (
    <div className="resume-template default-template">
      <style>{TEMPLATE_BASE_STYLES + STYLES}</style>
      <div className="resume-container">
        {modules.map((mod) => renderSection(mod, { interactive, onSelectSection }))}
      </div>
    </div>
  );
}
