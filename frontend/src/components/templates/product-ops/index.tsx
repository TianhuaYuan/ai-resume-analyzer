/**
 * 产品运营青绿 模板 — 青绿聚焦 + 简洁单栏，产品/运营岗（Magic product-ops-focus）
 *
 * 由 scripts/generate-templates/generate.mjs 生成，请勿手改。
 */

import { TEMPLATE_BASE_STYLES } from "../shared/templateBaseStyles";
import { renderSection } from "../shared/renderSection";
import type { TemplateComponentProps } from "../registry";

const STYLES = `
/* ── single 布局：单栏，根 padding = var(--margin)(分页测量依赖) ── */
.resume-template.product-ops-template {
  padding: var(--margin);
  background: #ffffff;
  color: #111827;
}
.resume-template.product-ops-template .resume-container { width: 100%; }

.resume-template.product-ops-template .basic-header {
  padding-bottom: 16px;
  margin-bottom: var(--section-spacing);
}
.resume-template.product-ops-template .basic-name {
  color: #111827;
  font-size: calc(var(--font-size) * 1.8);
  letter-spacing: 1px;
}
.resume-template.product-ops-template .basic-job-title {
  font-weight: 600;
  margin-top: 4px;
}

.resume-template.product-ops-template .module-title {
  font-size: calc(var(--font-size) * 1.1);
  color: #111827;
}
.resume-template.product-ops-template .module-content { padding-left: 2px; }

/* 头部主标题/条目标题统一用 #111827 */
.resume-template.product-ops-template .edu-school,
.resume-template.product-ops-template .work-company,
.resume-template.product-ops-template .proj-name,
.resume-template.product-ops-template .club-name,
.resume-template.product-ops-template .skill-name,
.resume-template.product-ops-template .fallback-key,
.resume-template.product-ops-template .other-title,
.resume-template.product-ops-template .custom-title,
.resume-template.product-ops-template .pub-title { color: #111827; }


/* 共享文字色 */
.resume-template.product-ops-template .basic-summary, .resume-template.product-ops-template .basic-contact, .resume-template.product-ops-template .basic-links, .resume-template.product-ops-template .basic-custom-fields
.resume-template.product-ops-template .work-desc, .resume-template.product-ops-template .proj-desc, .resume-template.product-ops-template .edu-desc, .resume-template.product-ops-template .club-desc
.resume-template.product-ops-template .work-achievements, .resume-template.product-ops-template .lang-item, .resume-template.product-ops-template .cert-item, .resume-template.product-ops-template .honor-item, .resume-template.product-ops-template .rec-item
.resume-template.product-ops-template .interests, .resume-template.product-ops-template .social-link, .resume-template.product-ops-template .social-links, .resume-template.product-ops-template .other-content, .resume-template.product-ops-template .custom-content
.resume-template.product-ops-template .pub-authors, .resume-template.product-ops-template .proj-tech, .resume-template.product-ops-template .fallback-row { color: #4b5563; }
.resume-template.product-ops-template .edu-date, .resume-template.product-ops-template .work-date, .resume-template.product-ops-template .proj-date, .resume-template.product-ops-template .club-date
.resume-template.product-ops-template .honor-date, .resume-template.product-ops-template .rec-contact, .resume-template.product-ops-template .pub-info { color: #4b5563; opacity: 0.75; }

.resume-template.product-ops-template .basic-header::after { content:""; display:block; width:52px; height:3px; background:var(--accent-color); border-radius:2px; margin-top:10px; }

.resume-template.product-ops-template .skill-item { display:inline-block; background:rgba(15,23,42,0.06); border:none; color:var(--accent-color); border-radius:999px; padding:2px 12px; margin:2px 6px 2px 0; font-size:calc(var(--font-size) * 0.92); }
`;

export default function ProductOpsTemplate({
  modules,
  interactive,
  onSelectSection,
}: TemplateComponentProps) {
  return (
    <div className="resume-template product-ops-template">
      <style>{TEMPLATE_BASE_STYLES + STYLES}</style>
      <div className="resume-container">
        {modules.map((mod) => renderSection(mod, { interactive, onSelectSection }))}
      </div>
    </div>
  );
}
