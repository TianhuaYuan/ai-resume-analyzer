/**
 * 专业双栏模板 — 对齐后端 templates/professional.html。
 *
 * 左栏（浅色底）放 basic_info/skills/language/social_links/interests，
 * 右栏（白底）放其余模块。对齐后端 render_resume 的 sidebar 分流。
 */

import { TEMPLATE_BASE_STYLES } from "../shared/templateBaseStyles";
import { renderSection } from "../shared/renderSection";
import type { TemplateComponentProps } from "../registry";

// 对齐后端 sidebar_types
const SIDEBAR_TYPES = new Set([
  "basic_info",
  "skills",
  "language",
  "social_links",
  "interests",
]);

const PROFESSIONAL_STYLES = `
  .resume-template.professional-template { background: #fff; }
  .professional-layout {
    display: flex;
    min-height: 100%;
  }
  .professional-sidebar {
    width: 32%;
    flex-shrink: 0;
    background: var(--color-sidebar-bg, #f1f5f9);
    padding: calc(var(--margin) * 0.7) calc(var(--margin) * 0.5);
  }
  .professional-main {
    flex: 1;
    min-width: 0;
    padding: var(--margin);
  }
  .resume-template.professional-template .module { margin-bottom: 12px; }
  .resume-template.professional-template .module-title::after { display: none; }
  .resume-template.professional-template .module-title {
    font-size: calc(var(--font-size) * 1.08);
    margin-bottom: 6px;
  }
  .resume-template.professional-template .basic-name {
    font-size: calc(var(--font-size) * 1.6);
    letter-spacing: 1px;
  }
  .resume-template.professional-template .basic-job-title {
    font-size: calc(var(--font-size) * 1.0);
  }
  .resume-template.professional-template .basic-contact {
    font-size: calc(var(--font-size) * 0.85);
    line-height: 1.6;
  }
  .resume-template.professional-template .module-content { padding-left: 0; }
`;

export default function ProfessionalTemplate({
  modules,
  interactive,
  onSelectSection,
}: TemplateComponentProps) {
  const sidebar = modules.filter((m) => SIDEBAR_TYPES.has(m.module_type));
  const main = modules.filter((m) => !SIDEBAR_TYPES.has(m.module_type));
  const opts = { interactive, onSelectSection };

  return (
    <div className="resume-template professional-template">
      <style>{TEMPLATE_BASE_STYLES + PROFESSIONAL_STYLES}</style>
      <div className="professional-layout">
        <div className="professional-sidebar">
          {sidebar.map((mod) => renderSection(mod, opts))}
        </div>
        <div className="professional-main">
          {main.map((mod) => renderSection(mod, opts))}
        </div>
      </div>
    </div>
  );
}
