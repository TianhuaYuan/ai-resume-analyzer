/**
 * SectionWrapper — 每个模块节的统一外壳（借鉴 Magic Resume SectionWrapper）。
 *
 * - 输出与后端 render_resume 一致的 DOM 结构（.module / .module-title / .module-content）
 * - 加 data-resume-section-id，编辑器预览中点击可选中对应板块
 * - 编辑器预览时 hover 高亮
 */

import type { ReactNode } from "react";
import type { ModuleType } from "../../../api/builder";
import { MODULE_TITLES } from "./sections";

interface SectionWrapperProps {
  moduleType: ModuleType;
  interactive?: boolean;
  onSelectSection?: (moduleType: ModuleType) => void;
  /** 是否显示模块标题（条目级分页时续页不显示标题，标题只跟第一条） */
  showTitle?: boolean;
  children: ReactNode;
}

export function SectionWrapper({
  moduleType,
  interactive = false,
  onSelectSection,
  showTitle = true,
  children,
}: SectionWrapperProps) {
  const title = MODULE_TITLES[moduleType] ?? moduleType;
  const handleClick = () => {
    if (interactive && onSelectSection) onSelectSection(moduleType);
  };

  return (
    <section
      className={`module module-${moduleType}${interactive ? " module-interactive" : ""}`}
      data-resume-section-id={moduleType}
      onClick={handleClick}
    >
      {showTitle && moduleType !== "basic_info" && <h2 className="module-title">{title}</h2>}
      <div className="module-content">{children}</div>
    </section>
  );
}
