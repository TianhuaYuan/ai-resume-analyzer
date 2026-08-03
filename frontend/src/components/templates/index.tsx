/**
 * ResumeTemplateView — 前端模板渲染统一入口（替代 iframe + 后端 HTML 预览）。
 *
 * 借鉴 Magic Resume：按 template_id 解析模板组件，React 组件直接 DOM 渲染。
 * 数据源是当前编辑的 modules + style（不读数据库），内容变更实时反映。
 *
 * CSS 变量注入：把 ResumeStyle 映射为 --font-family/--accent-color 等 CSS 变量，
 * 模板基础样式与后端 templates/*.html 同源，视觉一致。
 */

import { useMemo, type CSSProperties } from "react";
import type { ModuleType, ResumeModule, ResumeStyle } from "../../api/builder";
import { getTemplateComponent } from "./registry";

export interface ResumeTemplateViewProps {
  /** 当前编辑的模块列表（含 basic_info 等） */
  modules: ResumeModule[];
  /** 样式配置（驱动 CSS 变量） */
  style: ResumeStyle;
  /** 隐藏的模块类型（显隐控制） */
  hiddenModules?: string[];
  /** 是否可交互（编辑器预览 true：点击板块选中；模板库缩略图 false） */
  interactive?: boolean;
  /** 点击板块回调 */
  onSelectSection?: (moduleType: ModuleType) => void;
}

export function ResumeTemplateView({
  modules,
  style,
  hiddenModules,
  interactive = false,
  onSelectSection,
}: ResumeTemplateViewProps) {
  const Template = getTemplateComponent(style.template_id);

  // 过滤隐藏板块 + 按 sort_order 排序
  const sortedModules = useMemo(() => {
    const hidden = new Set(hiddenModules ?? style.hidden_modules ?? []);
    return [...modules]
      .filter((m) => !hidden.has(m.module_type))
      .sort((a, b) => a.sort_order - b.sort_order);
  }, [modules, style.hidden_modules, hiddenModules]);

  // ResumeStyle → CSS 变量（与后端 _build_css_vars 对齐）
  const cssVars = useMemo(() => {
    const s = style ?? ({} as ResumeStyle);
    return {
      "--font-family": s.font_family ?? "Noto Sans CJK SC",
      "--font-size": s.font_size ?? "14px",
      "--line-height": String(s.line_height ?? 1.6),
      "--spacing": s.spacing ?? "8px",
      "--accent-color": s.accent_color ?? "#2563eb",
      "--margin": s.margin ?? "16mm",
      "--page-size": s.page_size ?? "A4",
      "--section-spacing": s.section_spacing ?? "16px",
    } as CSSProperties;
  }, [style]);

  return (
    <div className="resume-template-root" style={cssVars}>
      <Template
        modules={sortedModules}
        style={style}
        interactive={interactive}
        onSelectSection={onSelectSection}
      />
      {style?.custom_css && <style>{style.custom_css}</style>}
    </div>
  );
}
