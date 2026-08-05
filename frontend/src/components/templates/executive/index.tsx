/**
 * 深蓝头带 模板 — 深蓝头带 + 职业时间轴，商务正式（Magic executive-band × RR ditto）
 *
 * 由 scripts/generate-templates/generate.mjs 生成，请勿手改。
 */

import { TEMPLATE_BASE_STYLES } from "../shared/templateBaseStyles";
import { renderSection } from "../shared/renderSection";
import { SectionContent } from "../shared/sections";
import type { TemplateComponentProps } from "../registry";

const STYLES = `
/* ── banner 布局：顶部彩色头带 + 下方单栏正文。根 padding = var(--margin) ── */
.resume-template.executive-template {
  padding: var(--margin);
  background: #ffffff;
  color: #0f172a;
}
.resume-template.executive-template .executive-banner {
  background: var(--accent-color);
  color: #ffffff;
  border-radius: 8px;
  padding: 20px 24px;
  margin-bottom: var(--section-spacing);
}
.resume-template.executive-template .executive-banner .basic-header { margin: 0; padding: 0; }
.resume-template.executive-template .executive-banner .basic-name {
  color: #ffffff;
  font-size: calc(var(--font-size) * 1.9);
  letter-spacing: 2px;
}
.resume-template.executive-template .executive-banner .basic-job-title {
  color: rgba(255, 255, 255, 0.92);
  font-weight: 600;
  margin-top: 2px;
}
.resume-template.executive-template .executive-banner .basic-contact,
.resume-template.executive-template .executive-banner .basic-links,
.resume-template.executive-template .executive-banner .basic-custom-fields {
  color: rgba(255, 255, 255, 0.85);
  margin-top: 4px;
}
.resume-template.executive-template .executive-banner .basic-links a { color: #ffffff; text-decoration: underline; }
.resume-template.executive-template .executive-banner .basic-summary {
  color: rgba(255, 255, 255, 0.9);
  margin-top: 8px;
  text-align: left;
}
.resume-template.executive-template .executive-banner .basic-avatar {
  border: 2px solid rgba(255, 255, 255, 0.6);
}

.resume-template.executive-template .executive-body { width: 100%; }
.resume-template.executive-template .executive-body .module-title {
  font-size: calc(var(--font-size) * 1.12);
  color: #0f172a;
}
.resume-template.executive-template .executive-body .edu-school,
.resume-template.executive-template .executive-body .work-company,
.resume-template.executive-template .executive-body .proj-name,
.resume-template.executive-template .executive-body .club-name,
.resume-template.executive-template .executive-body .skill-name,
.resume-template.executive-template .executive-body .fallback-key,
.resume-template.executive-template .executive-body .other-title,
.resume-template.executive-template .executive-body .custom-title,
.resume-template.executive-template .executive-body .pub-title { color: #0f172a; }


/* 共享文字色 */
.resume-template.executive-template .basic-summary, .resume-template.executive-template .basic-contact, .resume-template.executive-template .basic-links, .resume-template.executive-template .basic-custom-fields
.resume-template.executive-template .work-desc, .resume-template.executive-template .proj-desc, .resume-template.executive-template .edu-desc, .resume-template.executive-template .club-desc
.resume-template.executive-template .work-achievements, .resume-template.executive-template .lang-item, .resume-template.executive-template .cert-item, .resume-template.executive-template .honor-item, .resume-template.executive-template .rec-item
.resume-template.executive-template .interests, .resume-template.executive-template .social-link, .resume-template.executive-template .social-links, .resume-template.executive-template .other-content, .resume-template.executive-template .custom-content
.resume-template.executive-template .pub-authors, .resume-template.executive-template .proj-tech, .resume-template.executive-template .fallback-row { color: #475569; }
.resume-template.executive-template .edu-date, .resume-template.executive-template .work-date, .resume-template.executive-template .proj-date, .resume-template.executive-template .club-date
.resume-template.executive-template .honor-date, .resume-template.executive-template .rec-contact, .resume-template.executive-template .pub-info { color: #475569; opacity: 0.75; }

.resume-template.executive-template .skill-item { display:inline-block; background:rgba(15,23,42,0.05); border:1px solid rgba(15,23,42,0.12); color:var(--accent-color); border-radius:4px; padding:1px 8px; margin:2px 4px 2px 0; font-size:calc(var(--font-size) * 0.92); }

/* 主栏时间轴 */
.resume-template.executive-template .executive-body .module-education .module-content, .resume-template.executive-template .executive-body .module-work_experience .module-content, .resume-template.executive-template .executive-body .module-project_experience .module-content, .resume-template.executive-template .executive-body .module-club_activities .module-content { position:relative; padding-left:20px; }
.resume-template.executive-template .executive-body .module-education .module-content::before, .resume-template.executive-template .executive-body .module-work_experience .module-content::before, .resume-template.executive-template .executive-body .module-project_experience .module-content::before, .resume-template.executive-template .executive-body .module-club_activities .module-content::before { content:""; position:absolute; left:7px; top:4px; bottom:4px; width:1px; background:var(--accent-color); opacity:0.35; }
.resume-template.executive-template .executive-body .module-education .edu-item, .resume-template.executive-template .executive-body .module-work_experience .work-item, .resume-template.executive-template .executive-body .module-project_experience .proj-item, .resume-template.executive-template .executive-body .module-club_activities .club-item { position:relative; }
.resume-template.executive-template .executive-body .module-education .edu-item::before, .resume-template.executive-template .executive-body .module-work_experience .work-item::before, .resume-template.executive-template .executive-body .module-project_experience .proj-item::before, .resume-template.executive-template .executive-body .module-club_activities .club-item::before { content:""; position:absolute; left:-17px; top:6px; width:9px; height:9px; border-radius:50%; background:#ffffff; border:2px solid var(--accent-color); }
`;

export default function ExecutiveTemplate({
  modules,
  interactive,
  onSelectSection,
}: TemplateComponentProps) {
  const basic = modules.filter((m) => m.module_type === "basic_info");
  const rest = modules.filter((m) => m.module_type !== "basic_info");
  const opts = { interactive, onSelectSection };

  return (
    <div className="resume-template executive-template">
      <style>{TEMPLATE_BASE_STYLES + STYLES}</style>
      {basic.length > 0 && (
        <div className="executive-banner">
          {basic.map((m) => (
            <SectionContent key={m.module_type} moduleType={m.module_type} content={m.content} />
          ))}
        </div>
      )}
      <div className="executive-body">
        {rest.map((mod) => renderSection(mod, opts))}
      </div>
    </div>
  );
}
