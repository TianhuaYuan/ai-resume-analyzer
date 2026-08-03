/**
 * T31: ModuleForm — Builder 中间列模块表单组件。
 *
 * 智能分发器：根据 module_type 渲染不同的表单字段。
 * 使用 React.memo 避免父组件状态变更时不必要的重渲染。
 *
 * 支持的模块类型：
 * - basic_info：扁平字段（姓名/电话/邮箱等）
 * - education/work_experience/project_experience/language/honors/
 *   certificates/club_activities/publications/recommendation：条目列表编辑器
 * - skills：分类 + 逗号分隔技能项
 * - interests：逗号分隔标签输入
 * - social_links：社交平台字段
 * - other：标题 + 内容文本框
 * - custom：多板块编辑（content.entries 数组，兼容单板块 {title, content}）
 */

import { memo, useCallback, useState } from "react";
import { Plus, Trash, CaretUp, CaretDown, Eye, EyeSlash } from "@phosphor-icons/react";
import type { ModuleType, ModuleContent } from "../../api/builder";
import { MODULE_LABELS } from "./ModuleList";
import { RichTextEditor } from "./RichTextEditor";

// ── 字段配置类型 ──────────────────────────────────────────────

export type FieldType = "text" | "textarea" | "number" | "list";

export interface FieldConfig {
  key: string;
  label: string;
  type: FieldType;
  required?: boolean;
  placeholder?: string;
  /** number 字段的输入范围（映射到 input min/max，对齐后端 schema 约束） */
  min?: number;
  max?: number;
}

// ── 值读取辅助函数 ────────────────────────────────────────────

/** 从 content 中安全读取字符串值 */
export function getString(content: Record<string, unknown>, key: string): string {
  const v = content[key];
  if (typeof v === "string") return v;
  if (typeof v === "number") return String(v);
  return "";
}

/** 从 content 中安全读取数组并转为逗号分隔字符串 */
export function getListString(content: Record<string, unknown>, key: string): string {
  const v = content[key];
  if (Array.isArray(v)) return v.map((item) => String(item)).join(", ");
  if (typeof v === "string") return v;
  return "";
}

/** 从 content 中安全读取条目数组 */
export function getEntries(content: ModuleContent): Record<string, unknown>[] {
  const v = content.entries;
  return Array.isArray(v) ? (v as Record<string, unknown>[]) : [];
}

/** 将逗号分隔文本转为字符串数组（保留空串以维持输入光标） */
export function splitList(text: string): string[] {
  return text.split(",").map((s) => s.trim());
}

// ── 字段配置常量 ──────────────────────────────────────────────

/** basic_info 的字段配置（UP 简历对齐：扩展状态/籍贯/链接字段） */
export const BASIC_INFO_FIELDS: FieldConfig[] = [
  { key: "name", label: "姓名", type: "text", required: true, placeholder: "张三" },
  { key: "phone", label: "电话", type: "text", placeholder: "13800138000" },
  { key: "email", label: "邮箱", type: "text", placeholder: "zhangsan@example.com" },
  { key: "gender", label: "性别", type: "text", placeholder: "男 / 女" },
  { key: "age", label: "年龄", type: "number", placeholder: "25", min: 0, max: 150 },
  { key: "location", label: "所在地", type: "text", placeholder: "北京" },
  { key: "job_title", label: "求职意向", type: "text", placeholder: "前端开发工程师" },
  { key: "status", label: "当前状态", type: "text", placeholder: "在校生 / 求职中" },
  { key: "hometown", label: "籍贯", type: "text", placeholder: "广东广州" },
  { key: "github_url", label: "GitHub", type: "text", placeholder: "https://github.com/username" },
  { key: "blog_url", label: "博客", type: "text", placeholder: "https://blog.example.com" },
  { key: "homepage_url", label: "主页", type: "text", placeholder: "https://example.com" },
  { key: "summary", label: "个人简介", type: "textarea", placeholder: "3 年前端开发经验..." },
];

/** 条目类模块的字段配置 */
export const ENTRY_FIELD_CONFIGS: Partial<Record<ModuleType, FieldConfig[]>> = {
  education: [
    { key: "school", label: "学校", type: "text", required: true, placeholder: "清华大学" },
    { key: "degree", label: "学位", type: "text", placeholder: "本科 / 硕士" },
    { key: "major", label: "专业", type: "text", placeholder: "计算机科学" },
    { key: "start_date", label: "开始日期", type: "text", placeholder: "2020-09" },
    { key: "end_date", label: "结束日期", type: "text", placeholder: "2024-06" },
    { key: "gpa", label: "GPA", type: "number", placeholder: "3.8", min: 0, max: 10 },
    { key: "description", label: "描述", type: "textarea" },
  ],
  work_experience: [
    { key: "company", label: "公司", type: "text", required: true, placeholder: "字节跳动" },
    { key: "position", label: "职位", type: "text", required: true, placeholder: "前端开发工程师" },
    { key: "start_date", label: "开始日期", type: "text", placeholder: "2021-07" },
    { key: "end_date", label: "结束日期", type: "text", placeholder: "2024-06" },
    { key: "description", label: "工作描述", type: "textarea" },
    { key: "achievements", label: "主要成就（逗号分隔）", type: "list", placeholder: "优化首屏加载, 搭建组件库" },
  ],
  project_experience: [
    { key: "name", label: "项目名称", type: "text", required: true, placeholder: "AI 简历分析平台" },
    { key: "role", label: "担任角色", type: "text", placeholder: "前端负责人" },
    { key: "start_date", label: "开始日期", type: "text", placeholder: "2023-01" },
    { key: "end_date", label: "结束日期", type: "text", placeholder: "2023-12" },
    { key: "url", label: "项目链接", type: "text", placeholder: "https://github.com/..." },
    { key: "description", label: "项目描述", type: "textarea" },
    { key: "tech_stack", label: "技术栈（逗号分隔）", type: "list", placeholder: "React, TypeScript, Node.js" },
  ],
  language: [
    { key: "name", label: "语言", type: "text", required: true, placeholder: "英语" },
    { key: "proficiency", label: "熟练程度", type: "text", placeholder: "精通 / 熟练 / 一般" },
    { key: "score", label: "成绩/证书", type: "text", placeholder: "CET-6 580" },
  ],
  honors: [
    { key: "title", label: "奖项名称", type: "text", required: true, placeholder: "国家奖学金" },
    { key: "date", label: "获奖日期", type: "text", placeholder: "2023-10" },
    { key: "description", label: "描述", type: "textarea" },
  ],
  certificates: [
    { key: "name", label: "证书名称", type: "text", required: true, placeholder: "AWS Solutions Architect" },
    { key: "issuer", label: "颁发机构", type: "text", placeholder: "Amazon Web Services" },
    { key: "date", label: "获得日期", type: "text", placeholder: "2023-05" },
    { key: "score", label: "成绩", type: "text", placeholder: "950" },
  ],
  club_activities: [
    { key: "name", label: "社团/活动名称", type: "text", required: true, placeholder: "计算机协会" },
    { key: "role", label: "担任角色", type: "text", placeholder: "会长" },
    { key: "start_date", label: "开始日期", type: "text", placeholder: "2020-09" },
    { key: "end_date", label: "结束日期", type: "text", placeholder: "2022-06" },
    { key: "description", label: "描述", type: "textarea" },
  ],
  publications: [
    { key: "title", label: "论文标题", type: "text", required: true, placeholder: "Deep Learning for..." },
    { key: "authors", label: "作者（逗号分隔）", type: "list", placeholder: "张三, 李四" },
    { key: "venue", label: "发表期刊/会议", type: "text", placeholder: "ICML 2023" },
    { key: "date", label: "发表日期", type: "text", placeholder: "2023-07" },
    { key: "url", label: "链接", type: "text", placeholder: "https://doi.org/..." },
  ],
  recommendation: [
    { key: "name", label: "推荐人姓名", type: "text", required: true, placeholder: "王教授" },
    { key: "title", label: "头衔", type: "text", placeholder: "教授 / 博士生导师" },
    { key: "organization", label: "所属机构", type: "text", placeholder: "清华大学计算机系" },
    { key: "contact", label: "联系方式", type: "text", placeholder: "13800138000" },
    { key: "email", label: "邮箱", type: "text", placeholder: "wang@tsinghua.edu.cn" },
  ],
};

/** social_links 的字段配置 */
export const SOCIAL_LINK_FIELDS: FieldConfig[] = [
  { key: "github", label: "GitHub", type: "text", placeholder: "https://github.com/username" },
  { key: "linkedin", label: "LinkedIn", type: "text", placeholder: "https://linkedin.com/in/username" },
  { key: "website", label: "个人网站", type: "text", placeholder: "https://example.com" },
  { key: "twitter", label: "Twitter", type: "text", placeholder: "https://twitter.com/username" },
  { key: "wechat", label: "微信", type: "text", placeholder: "wechat_id" },
];

// ── 通用输入样式 ──────────────────────────────────────────────

export const INPUT_CLASS =
  "w-full px-3 py-2 rounded-xl text-sm text-[var(--color-text)] " +
  "bg-[#F2F2F7] border border-transparent " +
  "placeholder:text-[var(--color-text-muted)] " +
  "focus:outline-none focus:bg-white focus:border-brand/40 " +
  "focus:ring-4 focus:ring-brand/15 transition-all duration-150";

export const LABEL_CLASS =
  "block text-xs font-medium text-[var(--color-text-muted)] mb-1";

// ── 单字段渲染组件 ────────────────────────────────────────────

interface FieldRendererProps {
  field: FieldConfig;
  value: string;
  onChange: (value: string) => void;
}

export function FieldRenderer({ field, value, onChange }: FieldRendererProps) {
  const label = (
    <label className={LABEL_CLASS}>
      {field.label}
      {field.required && <span className="ml-0.5 text-red-400">*</span>}
    </label>
  );

  if (field.type === "textarea") {
    return (
      <div>
        {label}
        <RichTextEditor
          value={value}
          onChange={onChange}
          placeholder={field.placeholder}
          rows={3}
          minHeight="80px"
        />
      </div>
    );
  }

  if (field.type === "number") {
    // 定义 min/max 的字段（age/gpa）在输入时 clamp 到合法范围，避免超范围值提交后 422
    const handleNumberChange = (raw: string) => {
      let next = raw;
      if (raw !== "" && field.min != null && field.max != null) {
        const num = Number(raw);
        if (!Number.isNaN(num)) {
          next = String(Math.min(Math.max(num, field.min), field.max));
        }
      }
      onChange(next);
    };
    return (
      <div>
        {label}
        <input
          type="number"
          value={value}
          onChange={(e) => handleNumberChange(e.target.value)}
          placeholder={field.placeholder}
          min={field.min}
          max={field.max}
          className={INPUT_CLASS}
        />
      </div>
    );
  }

  // text 或 list 都用普通输入框
  return (
    <div>
      {label}
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={field.placeholder}
        className={INPUT_CLASS}
      />
    </div>
  );
}

// ── 条目列表编辑器 ────────────────────────────────────────────

interface EntriesEditorProps {
  content: ModuleContent;
  onChange: (content: ModuleContent) => void;
  fields: FieldConfig[];
  moduleLabel: string;
}

export function EntriesEditor({ content, onChange, fields, moduleLabel }: EntriesEditorProps) {
  const entries = getEntries(content);

  const handleAdd = useCallback(() => {
    onChange({ ...content, entries: [...entries, {}] });
  }, [content, entries, onChange]);

  const handleRemove = useCallback(
    (index: number) => {
      const newEntries = entries.filter((_, i) => i !== index);
      onChange({ ...content, entries: newEntries });
    },
    [content, entries, onChange],
  );

  const handleMoveUp = useCallback(
    (index: number) => {
      if (index === 0) return;
      const newEntries = [...entries];
      [newEntries[index - 1], newEntries[index]] = [newEntries[index], newEntries[index - 1]];
      onChange({ ...content, entries: newEntries });
    },
    [content, entries, onChange],
  );

  const handleMoveDown = useCallback(
    (index: number) => {
      if (index === entries.length - 1) return;
      const newEntries = [...entries];
      [newEntries[index + 1], newEntries[index]] = [newEntries[index], newEntries[index + 1]];
      onChange({ ...content, entries: newEntries });
    },
    [content, entries, onChange],
  );

  const handleFieldChange = useCallback(
    (index: number, key: string, value: string) => {
      const newEntries = [...entries];
      const entry = { ...newEntries[index] };

      if (fields.find((f) => f.key === key)?.type === "number") {
        entry[key] = value === "" ? "" : Number(value);
      } else if (fields.find((f) => f.key === key)?.type === "list") {
        entry[key] = splitList(value);
      } else {
        entry[key] = value;
      }

      newEntries[index] = entry;
      onChange({ ...content, entries: newEntries });
    },
    [content, entries, onChange, fields],
  );

  return (
    <div className="space-y-4">
      {entries.map((entry, index) => (
        <div
          key={index}
          className={`p-3 rounded-xl border space-y-3 transition-all ${
            entry.hidden
              ? "bg-amber-50/50 border-amber-200/50 opacity-60"
              : "bg-[var(--color-bg-secondary)] border-[var(--color-border)]"
          }`}
        >
          {/* 条目头部：序号 + 排序/删除按钮 */}
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-[var(--color-text-muted)]">
              {moduleLabel} #{index + 1}
            </span>
            <div className="flex items-center gap-1">
              <button
                onClick={() => handleMoveUp(index)}
                disabled={index === 0}
                className="p-1 rounded text-[var(--color-text-muted)]
                  hover:text-brand hover:bg-brand/10
                  disabled:opacity-30 disabled:cursor-not-allowed
                  transition-all cursor-pointer"
                aria-label="上移"
              >
                <CaretUp size={14} weight="bold" aria-hidden="true" />
              </button>
              <button
                onClick={() => handleMoveDown(index)}
                disabled={index === entries.length - 1}
                className="p-1 rounded text-[var(--color-text-muted)]
                  hover:text-brand hover:bg-brand/10
                  disabled:opacity-30 disabled:cursor-not-allowed
                  transition-all cursor-pointer"
                aria-label="下移"
              >
                <CaretDown size={14} weight="bold" aria-hidden="true" />
              </button>
              <button
                onClick={() => handleRemove(index)}
                className="p-1 rounded text-[var(--color-text-muted)]
                  hover:text-red-400 hover:bg-red-500/10
                  transition-all cursor-pointer"
                aria-label="删除条目"
              >
                <Trash size={14} weight="regular" aria-hidden="true" />
              </button>
              {/* 条目隐藏切换 */}
              <button
                onClick={() => {
                  const newEntries = [...entries];
                  newEntries[index] = { ...newEntries[index], hidden: !newEntries[index].hidden };
                  onChange({ ...content, entries: newEntries });
                }}
                className={`p-1 rounded transition-all cursor-pointer ${
                  entry.hidden
                    ? "text-amber-400 bg-amber-500/10"
                    : "text-[var(--color-text-muted)] hover:text-[var(--color-text-secondary)] hover:bg-[var(--color-border)]"
                }`}
                title={entry.hidden ? "显示条目" : "隐藏条目"}
                aria-label={entry.hidden ? "显示条目" : "隐藏条目"}
              >
                {entry.hidden ? (
                  <EyeSlash size={14} weight="regular" aria-hidden="true" />
                ) : (
                  <Eye size={14} weight="regular" aria-hidden="true" />
                )}
              </button>
            </div>
          </div>

          {/* 条目字段 */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {fields.map((field) => {
              const fieldConfig = fields.find((f) => f.key === field.key);
              const isList = fieldConfig?.type === "list";
              const isFullWidth = field.type === "textarea" || isList;

              return (
                <div
                  key={field.key}
                  className={isFullWidth ? "sm:col-span-2" : ""}
                >
                  <FieldRenderer
                    field={field}
                    value={
                      field.type === "list"
                        ? getListString(entry, field.key)
                        : field.type === "number"
                        ? getString(entry, field.key)
                        : getString(entry, field.key)
                    }
                    onChange={(v) => handleFieldChange(index, field.key, v)}
                  />
                </div>
              );
            })}
          </div>
        </div>
      ))}

      {/* 添加条目按钮 */}
      <button
        onClick={handleAdd}
        className="w-full flex items-center justify-center gap-1.5 py-2.5
          rounded-xl text-xs font-medium text-[var(--color-text-secondary)]
          border border-dashed border-[var(--color-border)]
          hover:text-brand hover:border-brand/30 hover:bg-brand/5
          active:scale-[0.98] motion-reduce:active:scale-100
          transition-all cursor-pointer"
      >
        <Plus size={14} weight="bold" aria-hidden="true" />
        添加{moduleLabel}
      </button>
    </div>
  );
}

// ── Skills 分类编辑器 ─────────────────────────────────────────

interface SkillsFormProps {
  content: ModuleContent;
  onChange: (content: ModuleContent) => void;
}

export function SkillsForm({ content, onChange }: SkillsFormProps) {
  // 兼容新旧格式：items（新）或 categories（旧）
  const items: Array<{ id?: string; name: string; level?: number; category?: string }> =
    Array.isArray(content.items)
      ? (content.items as Array<{ id?: string; name: string; level?: number; category?: string }>)
      : [];

  const handleAddSkill = useCallback(() => {
    const newItems = [...items, { name: "", level: 3, category: "" }];
    onChange({ ...content, items: newItems });
  }, [content, items, onChange]);

  const handleRemoveSkill = useCallback(
    (index: number) => {
      onChange({ ...content, items: items.filter((_, i) => i !== index) });
    },
    [content, items, onChange],
  );

  const handleSkillChange = useCallback(
    (index: number, field: string, value: string | number) => {
      const newItems = [...items];
      newItems[index] = { ...newItems[index], [field]: value };
      onChange({ ...content, items: newItems });
    },
    [content, items, onChange],
  );

  // 按 category 分组显示
  const grouped = items.reduce<Record<string, Array<{ item: typeof items[0]; index: number }>>>((acc, item, i) => {
    const cat = item.category || "其他";
    if (!acc[cat]) acc[cat] = [];
    acc[cat].push({ item, index: i });
    return acc;
  }, {});

  const categories = Object.keys(grouped);

  return (
    <div className="space-y-4">
      {categories.map((cat) => (
        <div
          key={cat}
          className="p-3 rounded-xl bg-[var(--color-bg-secondary)] border border-[var(--color-border)] space-y-3"
        >
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-[var(--color-text-muted)]">
              {cat}
            </span>
          </div>
          {/* 该分类下的技能条目 */}
          {grouped[cat]?.map(({ item, index: i }) => (
            <div key={i} className="flex items-center gap-2">
              <input
                type="text"
                value={item.name}
                onChange={(e) => handleSkillChange(i, "name", e.target.value)}
                placeholder="技能名称"
                className={`flex-1 ${INPUT_CLASS}`}
              />
              {/* 熟练度 1-5 */}
              <div className="flex items-center gap-0.5" title={`熟练度 ${item.level || 3}/5`}>
                {[1, 2, 3, 4, 5].map((v) => (
                  <button
                    key={v}
                    onClick={() => handleSkillChange(i, "level", v)}
                    className={`w-4 h-4 rounded-full text-[10px] transition-all cursor-pointer ${
                      v <= (item.level || 3)
                        ? "bg-brand text-white"
                        : "bg-[var(--color-border)] text-[var(--color-text-muted)]"
                    }`}
                  >
                    {v}
                  </button>
                ))}
              </div>
              {/* 分类标签 */}
              <input
                type="text"
                value={item.category || ""}
                onChange={(e) => handleSkillChange(i, "category", e.target.value)}
                placeholder="分类"
                className="w-20 text-xs px-2 py-1 rounded border border-[var(--color-border)] bg-white"
              />
              <button
                onClick={() => handleRemoveSkill(i)}
                className="p-1 rounded text-[var(--color-text-muted)] hover:text-red-400 hover:bg-red-500/10 transition-all cursor-pointer"
              >
                <Trash size={12} />
              </button>
            </div>
          ))}
        </div>
      ))}

      <button
        onClick={handleAddSkill}
        className="w-full flex items-center justify-center gap-1.5 py-2.5
          rounded-xl text-xs font-medium text-[var(--color-text-secondary)]
          border border-dashed border-[var(--color-border)]
          hover:text-brand hover:border-brand/30 hover:bg-brand/5
          active:scale-[0.98] motion-reduce:active:scale-100
          transition-all cursor-pointer"
      >
        <Plus size={14} weight="bold" aria-hidden="true" />
        添加技能
      </button>
    </div>
  );
}

// ── 兴趣爱好编辑器 ────────────────────────────────────────────

interface InterestsFormProps {
  content: ModuleContent;
  onChange: (content: ModuleContent) => void;
}

export function InterestsForm({ content, onChange }: InterestsFormProps) {
  const itemsRaw = content.items;
  const items: string[] = Array.isArray(itemsRaw) ? (itemsRaw as string[]) : [];
  const itemsText = items.join(", ");

  return (
    <div>
      <label className={LABEL_CLASS}>兴趣爱好（逗号分隔）</label>
      <input
        type="text"
        value={itemsText}
        onChange={(e) =>
          onChange({ ...content, items: splitList(e.target.value) })
        }
        placeholder="阅读, 篮球, 摄影, 旅行"
        className={INPUT_CLASS}
      />
      <p className="mt-1.5 text-[11px] text-[var(--color-text-muted)]">
        多个兴趣用英文逗号分隔
      </p>
    </div>
  );
}

// ── 社交链接编辑器 ────────────────────────────────────────────

interface SocialLinksFormProps {
  content: ModuleContent;
  onChange: (content: ModuleContent) => void;
}

export function SocialLinksForm({ content, onChange }: SocialLinksFormProps) {
  const handleFieldChange = useCallback(
    (key: string, value: string) => {
      onChange({ ...content, [key]: value });
    },
    [content, onChange],
  );

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
      {SOCIAL_LINK_FIELDS.map((field) => (
        <FieldRenderer
          key={field.key}
          field={field}
          value={getString(content, field.key)}
          onChange={(v) => handleFieldChange(field.key, v)}
        />
      ))}
    </div>
  );
}

// ── 标题+内容编辑器（other / custom）──────────────────────────

interface TextContentFormProps {
  content: ModuleContent;
  onChange: (content: ModuleContent) => void;
  titleLabel: string;
  contentRequired: boolean;
}

export function TextContentForm({
  content,
  onChange,
  titleLabel,
  contentRequired,
}: TextContentFormProps) {
  return (
    <div className="space-y-3">
      <div>
        <label className={LABEL_CLASS}>
          {titleLabel}
          {contentRequired && <span className="ml-0.5 text-red-400">*</span>}
        </label>
        <input
          type="text"
          value={getString(content, "title")}
          onChange={(e) => onChange({ ...content, title: e.target.value })}
          placeholder="请输入标题"
          className={INPUT_CLASS}
        />
      </div>
      <div>
        <label className={LABEL_CLASS}>
          内容
          <span className="ml-0.5 text-red-400">*</span>
        </label>
        <RichTextEditor
          value={getString(content, "content")}
          onChange={(v) => onChange({ ...content, content: v })}
          placeholder="请输入内容"
          rows={8}
          minHeight="160px"
        />
      </div>
    </div>
  );
}

// ── 自定义模块多板块编辑器（custom） ──────────────────────────

interface CustomModuleFormProps {
  content: ModuleContent;
  onChange: (content: ModuleContent) => void;
}

/**
 * custom 模块的多板块编辑。
 *
 * 后端支持 content.entries: Array<{ title: string; content: string }>（多板块），
 * 同时向后兼容旧的单板块 { title, content }。此处：
 * - content.entries 为数组 → 多板块编辑（每板块可折叠：标题输入 + 内容编辑器 + 删除 + 添加板块）
 * - 否则 → 复用 TextContentForm 单板块编辑（向后兼容）
 */
export function CustomModuleForm({ content, onChange }: CustomModuleFormProps) {
  const [collapsed, setCollapsed] = useState<Set<number>>(new Set());

  // 向后兼容：无 entries 数组 → 单板块编辑
  if (!Array.isArray(content.entries)) {
    return (
      <TextContentForm
        content={content}
        onChange={onChange}
        titleLabel="板块标题"
        contentRequired
      />
    );
  }

  const entries = content.entries as Array<{ title?: string; content?: string }>;

  const toggleCollapsed = (index: number) => {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });
  };

  const updateEntry = (
    index: number,
    patch: Partial<{ title: string; content: string }>,
  ) => {
    const next = [...entries];
    next[index] = { ...(next[index] ?? {}), ...patch };
    onChange({ ...content, entries: next });
  };

  const addEntry = () => {
    onChange({ ...content, entries: [...entries, { title: "", content: "" }] });
  };

  const removeEntry = (index: number) => {
    onChange({ ...content, entries: entries.filter((_, i) => i !== index) });
    // 清理折叠状态：被删项之后的索引整体前移
    setCollapsed((prev) => {
      const next = new Set<number>();
      prev.forEach((i) => {
        if (i === index) return;
        next.add(i > index ? i - 1 : i);
      });
      return next;
    });
  };

  return (
    <div className="space-y-3">
      {entries.length === 0 && (
        <p className="text-[11px] text-[var(--color-text-muted)]">
          暂无板块，点击下方「添加板块」开始
        </p>
      )}

      {entries.map((entry, index) => {
        const isCollapsed = collapsed.has(index);
        const title = typeof entry?.title === "string" ? entry.title : "";
        return (
          <div
            key={index}
            className="p-3 rounded-xl bg-[var(--color-bg-secondary)] border border-[var(--color-border)] space-y-2"
          >
            {/* 头部：折叠按钮 + 删除 */}
            <div className="flex items-center gap-1">
              <button
                onClick={() => toggleCollapsed(index)}
                className="flex-1 flex items-center gap-1.5 min-w-0 text-left
                  text-[var(--color-text-secondary)] hover:text-brand
                  transition-colors cursor-pointer"
                aria-label={isCollapsed ? `展开板块 ${index + 1}` : `折叠板块 ${index + 1}`}
                aria-expanded={!isCollapsed}
              >
                <CaretDown
                  size={14}
                  weight="bold"
                  className={`shrink-0 transition-transform duration-200 ${
                    isCollapsed ? "-rotate-90" : ""
                  }`}
                  aria-hidden="true"
                />
                <span className="flex-1 text-xs font-medium truncate">
                  {title || `板块 ${index + 1}`}
                </span>
              </button>
              <button
                onClick={() => removeEntry(index)}
                className="shrink-0 p-1 rounded text-[var(--color-text-muted)]
                  hover:text-red-400 hover:bg-red-500/10
                  transition-all cursor-pointer"
                aria-label={`删除板块 ${index + 1}`}
              >
                <Trash size={14} weight="regular" aria-hidden="true" />
              </button>
            </div>

            {!isCollapsed && (
              <div className="space-y-2">
                <div>
                  <label className={LABEL_CLASS}>板块标题</label>
                  <input
                    type="text"
                    value={title}
                    onChange={(e) => updateEntry(index, { title: e.target.value })}
                    placeholder="如：项目亮点 / 专业技能补充"
                    className={INPUT_CLASS}
                  />
                </div>
                <div>
                  <label className={LABEL_CLASS}>内容</label>
                  <RichTextEditor
                    value={typeof entry?.content === "string" ? entry.content : ""}
                    onChange={(v) => updateEntry(index, { content: v })}
                    placeholder="请输入板块内容"
                    rows={6}
                    minHeight="120px"
                  />
                </div>
              </div>
            )}
          </div>
        );
      })}

      {/* 添加板块 */}
      <button
        onClick={addEntry}
        className="w-full flex items-center justify-center gap-1.5 py-2.5
          rounded-xl text-xs font-medium text-[var(--color-text-secondary)]
          border border-dashed border-[var(--color-border)]
          hover:text-brand hover:border-brand/30 hover:bg-brand/5
          active:scale-[0.98] motion-reduce:active:scale-100
          transition-all cursor-pointer"
      >
        <Plus size={14} weight="bold" aria-hidden="true" />
        添加板块
      </button>
    </div>
  );
}

// ── 主组件：模块表单分发器 ────────────────────────────────────

interface ModuleFormProps {
  /** 当前模块类型 */
  moduleType: ModuleType;
  /** 当前模块内容 */
  content: ModuleContent;
  /** 内容变更回调 */
  onChange: (content: ModuleContent) => void;
}

/**
 * #6: 自定义键值字段编辑器（basic_info 预设字段之外的自定义项）。
 * content.custom_fields: Array<{ key: string; value: string }>
 */
export function CustomFieldsEditor({
  content,
  onChange,
}: {
  content: ModuleContent;
  onChange: (c: ModuleContent) => void;
}) {
  const fields: Array<{ key: string; value: string }> = Array.isArray(
    content.custom_fields,
  )
    ? (content.custom_fields as Array<{ key: string; value: string }>)
    : [];

  const updateFields = (next: Array<{ key: string; value: string }>) => {
    onChange({ ...content, custom_fields: next });
  };

  const addField = () => updateFields([...fields, { key: "", value: "" }]);
  const updateField = (
    index: number,
    patch: Partial<{ key: string; value: string }>,
  ) => {
    const next = [...fields];
    next[index] = { ...next[index], ...patch };
    updateFields(next);
  };
  const removeField = (index: number) =>
    updateFields(fields.filter((_, i) => i !== index));

  const inputCls =
    "px-2 py-1.5 rounded-lg text-xs bg-[#F2F2F7] border border-transparent " +
    "focus:outline-none focus:bg-white focus:border-brand/40 focus:ring-4 focus:ring-brand/15 " +
    "text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] transition-all duration-150";

  return (
    <div className="sm:col-span-2 mt-2">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-medium text-[var(--color-text-secondary)]">
          自定义字段
        </span>
        <button
          onClick={addField}
          className="px-2 py-1 rounded-md text-[11px] text-brand
            hover:text-[#0077ed] hover:bg-brand/10
            transition-colors cursor-pointer"
          aria-label="添加自定义字段"
        >
          + 添加字段
        </button>
      </div>

      {fields.length === 0 ? (
        <p className="text-[11px] text-[var(--color-text-muted)]">
          暂无自定义字段，可添加如：国籍、期望薪资、到岗时间等
        </p>
      ) : (
        <div className="space-y-2">
          {fields.map((f, i) => (
            <div key={i} className="flex items-center gap-2">
              <input
                className={`${inputCls} flex-1`}
                placeholder="字段名"
                value={f.key}
                onChange={(e) => updateField(i, { key: e.target.value })}
                aria-label={`自定义字段 ${i + 1} 名称`}
              />
              <input
                className={`${inputCls} flex-[2]`}
                placeholder="字段值"
                value={f.value}
                onChange={(e) => updateField(i, { value: e.target.value })}
                aria-label={`自定义字段 ${i + 1} 值`}
              />
              <button
                onClick={() => removeField(i)}
                className="shrink-0 p-1.5 rounded-md text-[11px] text-[var(--color-text-muted)]
                  hover:text-red-400 hover:bg-red-500/10
                  transition-colors cursor-pointer"
                aria-label={`删除自定义字段 ${i + 1}`}
              >
                ✕
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function ModuleFormImpl({ moduleType, content, onChange }: ModuleFormProps) {
  const label = MODULE_LABELS[moduleType];

  // 判断是否为条目类模块
  const entryFields = ENTRY_FIELD_CONFIGS[moduleType];

  return (
    <div className="flex flex-col h-full">
      {/* 模块标题 */}
      <div className="shrink-0 px-5 py-3 border-b border-[var(--color-border)]">
        <h3 className="text-sm font-semibold text-[var(--color-text)]">{label}</h3>
      </div>

      {/* 表单内容 */}
      <div className="flex-1 overflow-y-auto px-5 py-4">
        {/* basic_info：扁平字段 */}
        {moduleType === "basic_info" && (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {BASIC_INFO_FIELDS.map((field) => {
              const isFullWidth = field.type === "textarea";
              return (
                <div key={field.key} className={isFullWidth ? "sm:col-span-2" : ""}>
                  <FieldRenderer
                    field={field}
                    value={getString(content, field.key)}
                    onChange={(v) => {
                      if (field.type === "number") {
                        onChange({ ...content, [field.key]: v === "" ? "" : Number(v) });
                      } else {
                        onChange({ ...content, [field.key]: v });
                      }
                    }}
                  />
                </div>
              );
            })}
            {/* #6: 预设字段之外的自定义键值字段 */}
            <CustomFieldsEditor content={content} onChange={onChange} />
          </div>
        )}

        {/* 条目类模块 */}
        {entryFields && <EntriesEditor content={content} onChange={onChange} fields={entryFields} moduleLabel={label} />}

        {/* skills：分类 + 技能项 */}
        {moduleType === "skills" && <SkillsForm content={content} onChange={onChange} />}

        {/* interests：逗号分隔 */}
        {moduleType === "interests" && <InterestsForm content={content} onChange={onChange} />}

        {/* social_links */}
        {moduleType === "social_links" && <SocialLinksForm content={content} onChange={onChange} />}

        {/* other：标题 + 内容 */}
        {moduleType === "other" && (
          <TextContentForm
            content={content}
            onChange={onChange}
            titleLabel="标题"
            contentRequired
          />
        )}

        {/* custom：多板块编辑（向后兼容单板块 {title, content}） */}
        {moduleType === "custom" && <CustomModuleForm content={content} onChange={onChange} />}
      </div>
    </div>
  );
}

export const ModuleForm = memo(ModuleFormImpl);
