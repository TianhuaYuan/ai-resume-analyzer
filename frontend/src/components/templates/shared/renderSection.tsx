/**
 * renderSection — 模板内渲染单个模块节的辅助函数。
 *
 * 每个模板的布局组件用它在对应位置渲染模块：
 *   modules.map((mod) => renderSection(mod, { interactive, onSelectSection }))
 * 双栏/头带模板可手动挑 basic_info 等模块做特殊布局。
 */

import type { ModuleType, ResumeModule } from "../../../api/builder";
import { SectionContent } from "./sections";
import { SectionWrapper } from "./SectionWrapper";

export interface RenderSectionOptions {
  interactive?: boolean;
  onSelectSection?: (moduleType: ModuleType) => void;
}

export function renderSection(mod: ResumeModule, opts: RenderSectionOptions = {}) {
  return (
    <SectionWrapper
      key={mod.module_type}
      moduleType={mod.module_type}
      interactive={opts.interactive}
      onSelectSection={opts.onSelectSection}
      showTitle={mod.showTitle !== false}
    >
      <SectionContent
        moduleType={mod.module_type}
        content={mod.content}
        itemRange={mod.itemRange}
      />
    </SectionWrapper>
  );
}
