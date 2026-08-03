/**
 * 商务单栏模板 — 对齐后端 templates/business.html。
 */

import { TEMPLATE_BASE_STYLES } from "../shared/templateBaseStyles";
import { renderSection } from "../shared/renderSection";
import type { TemplateComponentProps } from "../registry";

const BUSINESS_STYLES = `
  .resume-template.business-template { padding: var(--margin); }
  .resume-template.business-template .resume-container { width: 100%; margin: 0 auto; }
  .resume-template.business-template .basic-header {
    padding-bottom: 14px;
    margin-bottom: var(--section-spacing);
    border-bottom: 3px solid var(--accent-color);
  }
  .resume-template.business-template .basic-name {
    font-size: calc(var(--font-size) * 1.8);
    letter-spacing: 2px;
  }
  .resume-template.business-template .module-title { color: var(--accent-color); }
  .resume-template.business-template .module-title::after { display: none; }
  .resume-template.business-template .module {
    border-bottom: 1px solid #e2e8f0;
    margin-bottom: 12px;
  }
  .resume-template.business-template .module:last-child { border-bottom: none; }
  .resume-template.business-template .edu-school,
  .resume-template.business-template .work-company,
  .resume-template.business-template .proj-name { color: #0f172a; }
`;

export default function BusinessTemplate({
  modules,
  interactive,
  onSelectSection,
}: TemplateComponentProps) {
  return (
    <div className="resume-template business-template">
      <style>{TEMPLATE_BASE_STYLES + BUSINESS_STYLES}</style>
      <div className="resume-container">
        {modules.map((mod) => renderSection(mod, { interactive, onSelectSection }))}
      </div>
    </div>
  );
}
