/**
 * 中文紧凑 模板 — 中文紧凑单栏，一页纸信息密度高（Magic compact-cn-photo）
 *
 * 由 scripts/generate-templates/generate.mjs 生成，请勿手改。
 */

import { TEMPLATE_BASE_STYLES } from "../shared/templateBaseStyles";
import { renderSection } from "../shared/renderSection";
import type { TemplateComponentProps } from "../registry";

const STYLES = `
/* ── single 布局：单栏，根 padding = var(--margin)(分页测量依赖) ── */
.resume-template.compact-cn-template {
  padding: var(--margin);
  background: #ffffff;
  color: #000000;
}
.resume-template.compact-cn-template .resume-container { width: 100%; }

.resume-template.compact-cn-template .basic-header {
  padding-bottom: 16px;
  margin-bottom: var(--section-spacing);
}
.resume-template.compact-cn-template .basic-name {
  color: #000000;
  font-size: calc(var(--font-size) * 1.7);
  letter-spacing: 1px;
}
.resume-template.compact-cn-template .basic-job-title {
  font-weight: 700;
  margin-top: 4px;
}

.resume-template.compact-cn-template .module-title {
  font-size: calc(var(--font-size) * 1.05);
  color: #000000;
}
.resume-template.compact-cn-template .module-content { padding-left: 2px; }

/* 头部主标题/条目标题统一用 #000000 */
.resume-template.compact-cn-template .edu-school,
.resume-template.compact-cn-template .work-company,
.resume-template.compact-cn-template .proj-name,
.resume-template.compact-cn-template .club-name,
.resume-template.compact-cn-template .skill-name,
.resume-template.compact-cn-template .fallback-key,
.resume-template.compact-cn-template .other-title,
.resume-template.compact-cn-template .custom-title,
.resume-template.compact-cn-template .pub-title { color: #000000; }


/* 共享文字色 */
.resume-template.compact-cn-template .basic-summary, .resume-template.compact-cn-template .basic-contact, .resume-template.compact-cn-template .basic-links, .resume-template.compact-cn-template .basic-custom-fields
.resume-template.compact-cn-template .work-desc, .resume-template.compact-cn-template .proj-desc, .resume-template.compact-cn-template .edu-desc, .resume-template.compact-cn-template .club-desc
.resume-template.compact-cn-template .work-achievements, .resume-template.compact-cn-template .lang-item, .resume-template.compact-cn-template .cert-item, .resume-template.compact-cn-template .honor-item, .resume-template.compact-cn-template .rec-item
.resume-template.compact-cn-template .interests, .resume-template.compact-cn-template .social-link, .resume-template.compact-cn-template .social-links, .resume-template.compact-cn-template .other-content, .resume-template.compact-cn-template .custom-content
.resume-template.compact-cn-template .pub-authors, .resume-template.compact-cn-template .proj-tech, .resume-template.compact-cn-template .fallback-row { color: #333333; }
.resume-template.compact-cn-template .edu-date, .resume-template.compact-cn-template .work-date, .resume-template.compact-cn-template .proj-date, .resume-template.compact-cn-template .club-date
.resume-template.compact-cn-template .honor-date, .resume-template.compact-cn-template .rec-contact, .resume-template.compact-cn-template .pub-info { color: #333333; opacity: 0.75; }

.resume-template.compact-cn-template .basic-header::after { content:""; display:block; width:52px; height:3px; background:var(--accent-color); border-radius:2px; margin-top:10px; }

.resume-template.compact-cn-template .skill-item { display:inline-block; background:none; border:none; color:#000000; border-radius:0; padding:0; margin:0 8px 0 0; font-size:calc(var(--font-size) * 0.95); }
`;

export default function CompactCnTemplate({
  modules,
  interactive,
  onSelectSection,
}: TemplateComponentProps) {
  return (
    <div className="resume-template compact-cn-template">
      <style>{TEMPLATE_BASE_STYLES + STYLES}</style>
      <div className="resume-container">
        {modules.map((mod) => renderSection(mod, { interactive, onSelectSection }))}
      </div>
    </div>
  );
}
