/**
 * 优雅单栏模板 — 对齐后端 templates/elegant.html。
 */

import { TEMPLATE_BASE_STYLES } from "../shared/templateBaseStyles";
import { renderSection } from "../shared/renderSection";
import type { TemplateComponentProps } from "../registry";

const ELEGANT_STYLES = `
  .resume-template.elegant-template { padding: var(--margin); }
  .resume-template.elegant-template .resume-container { width: 100%; margin: 0 auto; }
  .resume-template.elegant-template .basic-header {
    text-align: center;
    padding-bottom: 16px;
    margin-bottom: var(--section-spacing);
    border-bottom: 1px solid #e2e8f0;
  }
  .resume-template.elegant-template .basic-name {
    font-size: calc(var(--font-size) * 1.8);
    letter-spacing: 3px;
  }
  .resume-template.elegant-template .basic-job-title {
    letter-spacing: 1px;
  }
  .resume-template.elegant-template .module-title {
    font-weight: 500;
    letter-spacing: 2px;
    color: #111827;
    justify-content: center;
  }
  .resume-template.elegant-template .module-title::after {
    height: 1px;
    opacity: 0.2;
    max-width: 40px;
    flex: none;
    margin-left: 8px;
  }
  .resume-template.elegant-template .module {
    border-bottom: 1px solid #f1f5f9;
    margin-bottom: 14px;
  }
  .resume-template.elegant-template .module:last-child { border-bottom: none; }
  .resume-template.elegant-template .edu-school,
  .resume-template.elegant-template .work-company,
  .resume-template.elegant-template .proj-name { font-weight: 500; letter-spacing: 0.5px; }
`;

export default function ElegantTemplate({
  modules,
  interactive,
  onSelectSection,
}: TemplateComponentProps) {
  return (
    <div className="resume-template elegant-template">
      <style>{TEMPLATE_BASE_STYLES + ELEGANT_STYLES}</style>
      <div className="resume-container">
        {modules.map((mod) => renderSection(mod, { interactive, onSelectSection }))}
      </div>
    </div>
  );
}
