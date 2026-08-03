/**
 * 极简单栏模板 — 对齐后端 templates/minimal.html。
 */

import { TEMPLATE_BASE_STYLES } from "../shared/templateBaseStyles";
import { renderSection } from "../shared/renderSection";
import type { TemplateComponentProps } from "../registry";

const MINIMAL_STYLES = `
  /* padding 必须等于 var(--margin)：分页测量按此值计算单页可用高度，
     若模板私自缩放会导致预览分页与实际不符 */
  .resume-template.minimal-template { padding: var(--margin); }
  .resume-template.minimal-template .resume-container { width: 100%; margin: 0 auto; }
  .resume-template.minimal-template .basic-header {
    padding-bottom: 8px;
    margin-bottom: 12px;
  }
  .resume-template.minimal-template .basic-name {
    font-size: calc(var(--font-size) * 1.7);
    letter-spacing: 1px;
  }
  .resume-template.minimal-template .module {
    margin-bottom: 10px;
    padding-bottom: 4px;
  }
  .resume-template.minimal-template .module-title::after { display: none; }
  .resume-template.minimal-template .module-title {
    font-weight: 600;
    letter-spacing: 1px;
    margin-bottom: 6px;
  }
  .resume-template.minimal-template .edu-item,
  .resume-template.minimal-template .work-item,
  .resume-template.minimal-template .proj-item,
  .resume-template.minimal-template .club-item {
    margin-bottom: calc(var(--section-spacing) * 0.8);
  }
`;

export default function MinimalTemplate({
  modules,
  interactive,
  onSelectSection,
}: TemplateComponentProps) {
  return (
    <div className="resume-template minimal-template">
      <style>{TEMPLATE_BASE_STYLES + MINIMAL_STYLES}</style>
      <div className="resume-container">
        {modules.map((mod) => renderSection(mod, { interactive, onSelectSection }))}
      </div>
    </div>
  );
}
