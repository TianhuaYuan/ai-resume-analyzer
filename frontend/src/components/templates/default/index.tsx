/**
 * 经典单栏模板 — 对齐后端 templates/default.html。
 */

import { TEMPLATE_BASE_STYLES } from "../shared/templateBaseStyles";
import { renderSection } from "../shared/renderSection";
import type { TemplateComponentProps } from "../registry";

const DEFAULT_STYLES = `
  .resume-template.default-template { padding: var(--margin); }
  .resume-template.default-template .resume-container { width: 100%; margin: 0 auto; }
  .resume-template.default-template .basic-header {
    padding-bottom: 14px;
    margin-bottom: var(--section-spacing);
    border-bottom: 2px solid var(--accent-color);
  }
`;

export default function DefaultTemplate({
  modules,
  interactive,
  onSelectSection,
}: TemplateComponentProps) {
  return (
    <div className="resume-template default-template">
      <style>{TEMPLATE_BASE_STYLES + DEFAULT_STYLES}</style>
      <div className="resume-container">
        {modules.map((mod) => renderSection(mod, { interactive, onSelectSection }))}
      </div>
    </div>
  );
}
