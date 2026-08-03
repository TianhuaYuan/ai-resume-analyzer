/**
 * mockData — 模板画廊 / 详情页的前端组件预览示例数据。
 *
 * 公开模板页（画廊/详情）没有真实简历数据，无法直接给 ResumeTemplateView 渲染，
 * 这里提供 createMockModules() + createMockStyle() 的占位预览。
 *
 * **重要：数据必须与后端 services/template_catalog.py 的 _placeholder_modules() 严格对齐**，
 * 确保前端 React 模板渲染与后端 preview_html iframe 渲染视觉一致，画廊预览风格统一。
 *
 * 仅用于展示；真实简历走 BuilderPage 的数据流。
 */

import type {
  ModuleContent,
  ModuleType,
  ResumeModule,
  ResumeStyle,
} from "../../../api/builder";
import type { TemplateConfig } from "../registry";

/**
 * 5 个占位模块（对齐后端 _placeholder_modules）：
 * basic_info + education + work_experience + project_experience + skills
 *
 * 字段名严格对齐 sections.tsx 各 Section 读取的 content schema，
 * 使前端 React 预览与后端 preview_html 视觉同源。
 */
export function createMockModules(): ResumeModule[] {
  const modules: Array<{ type: ModuleType; content: ModuleContent; order: number }> = [
    {
      type: "basic_info",
      order: 0,
      content: {
        name: "示例姓名",
        job_title: "目标岗位",
        location: "示例城市",
        summary: "具备扎实专业基础与项目实践经验的候选人示例。",
      },
    },
    {
      type: "education",
      order: 1,
      content: {
        entries: [
          {
            school: "示例大学",
            degree: "本科",
            major: "计算机科学与技术",
            start_date: "2021-09",
            end_date: "2025-06",
          },
        ],
      },
    },
    {
      type: "work_experience",
      order: 2,
      content: {
        entries: [
          {
            company: "示例科技公司",
            position: "开发工程师",
            start_date: "2025-07",
            end_date: "至今",
            description: "负责核心模块设计与开发，优化系统性能。",
          },
        ],
      },
    },
    {
      type: "project_experience",
      order: 3,
      content: {
        entries: [
          {
            name: "示例项目",
            role: "核心开发",
            start_date: "2024-03",
            end_date: "2024-09",
            description: "独立负责后端服务开发与部署上线。",
            tech_stack: ["Python", "FastAPI"],
          },
        ],
      },
    },
    {
      type: "skills",
      order: 4,
      content: {
        categories: [
          { name: "编程语言", items: ["Python", "TypeScript"] },
          { name: "框架工具", items: ["FastAPI", "React"] },
        ],
      },
    },
  ];

  return modules.map((m, i) => ({
    id: i + 1,
    resume_id: 0,
    module_type: m.type,
    content: m.content,
    sort_order: m.order,
    created_at: "2026-01-01T00:00:00Z",
  }));
}

/** 由模板 config 派生 mock style（主题色 + contentPadding 作页边距），可覆盖 accent_color */
export function createMockStyle(
  template: TemplateConfig,
  accentColor?: string,
): ResumeStyle {
  return {
    template_id: template.id,
    font_family: "Noto Sans CJK SC",
    font_size: "14px",
    line_height: 1.6,
    spacing: "8px",
    accent_color: accentColor ?? template.colorScheme.primary,
    margin: `${template.spacing.contentPadding}px`,
    page_size: "A4",
    section_spacing: `${template.spacing.sectionGap}px`,
    custom_css: "",
  };
}
