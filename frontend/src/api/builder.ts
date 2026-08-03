/**
 * T31: Builder API client.
 *
 * 对接后端 builder 相关端点：
 * - POST   /api/v1/resumes/builder          新建 builder 简历
 * - GET    /api/v1/resumes/{id}/builder      获取 builder 简历 + 模块
 * - PUT    /api/v1/resumes/{id}?mode=draft|complete  保存草稿 / 保存并完成
 * - GET    /api/v1/resumes/{id}/preview      预览 HTML（iframe src）
 * - GET    /api/v1/resumes/{id}/export       导出 PDF/Markdown
 * - POST   /api/v1/resumes/{id}/avatar       上传头像
 * - POST   /api/v1/resumes/parse-to-modules  反解析纯文本→模块
 * - POST   /api/v1/resumes/{id}/lock         获取编辑锁
 * - POST   /api/v1/resumes/{id}/lock/heartbeat  心跳续期
 * - DELETE /api/v1/resumes/{id}/lock         释放编辑锁
 * - POST   /api/v1/qa/ask/builder            Builder Agent SSE（复用 qa.ts 的 askBuilderStream）
 */

import { api } from "./client";
import { refreshToken, notifySessionExpired } from "./client";
import type { AgentSSEEvent } from "./qa";

// ── 类型定义 ──────────────────────────────────────────────────

/** 15 个模块类型（与后端 ModuleType 枚举对齐） */
export type ModuleType =
  | "basic_info"
  | "education"
  | "work_experience"
  | "project_experience"
  | "skills"
  | "language"
  | "honors"
  | "certificates"
  | "interests"
  | "club_activities"
  | "publications"
  | "recommendation"
  | "social_links"
  | "other"
  | "custom";

/** 模块 content 用宽松 dict（各模块 schema 不同，前端表单按 module_type 分发） */
export type ModuleContent = Record<string, unknown>;

// ── v2 统一结构类型（模块 Schema 重设计） ────────────────────

/** 所有模块共用的元数据 */
export interface ModuleMetadata {
  /** 模块标题（用户可编辑，替代 MODULE_LABELS 硬编码） */
  title: string;
  /** 模块级隐藏（不渲染、不导出） */
  hidden?: boolean;
}

/** 所有条目的基础字段 */
export interface BaseItem {
  /** 唯一标识 */
  id: string;
  /** 条目级隐藏 */
  hidden?: boolean;
}

// ── 各模块条目类型 ──────────────────────────────────────────

export interface EducationItem extends BaseItem {
  school: string;
  degree?: string;
  major?: string;
  start_date?: string;
  end_date?: string;
  gpa?: number;
  description?: string;
}

export interface WorkExperienceItem extends BaseItem {
  company: string;
  position: string;
  start_date?: string;
  end_date?: string;
  description?: string;
  achievements?: string[];
}

export interface ProjectExperienceItem extends BaseItem {
  name: string;
  role?: string;
  start_date?: string;
  end_date?: string;
  url?: string;
  description?: string;
  tech_stack?: string[];
}

export interface SkillItem extends BaseItem {
  name: string;
  level?: number;
  category?: string;
}

export interface LanguageItem extends BaseItem {
  name: string;
  proficiency?: string;
  score?: string;
}

export interface HonorItem extends BaseItem {
  title: string;
  date?: string;
  description?: string;
}

export interface CertificateItem extends BaseItem {
  name: string;
  issuer?: string;
  date?: string;
  score?: string;
}

export interface InterestItem extends BaseItem {
  name: string;
}

export interface ClubActivityItem extends BaseItem {
  name: string;
  role?: string;
  start_date?: string;
  end_date?: string;
  description?: string;
}

export interface PublicationItem extends BaseItem {
  title: string;
  authors?: string[];
  venue?: string;
  date?: string;
  url?: string;
}

export interface RecommendationItem extends BaseItem {
  name: string;
  title?: string;
  organization?: string;
  contact?: string;
  email?: string;
}

export interface SocialProfileItem extends BaseItem {
  platform: string;
  url: string;
  icon?: string;
}

export interface CustomSectionItem extends BaseItem {
  title: string;
  content: string;
}

// ── 各模块 content 类型 ────────────────────────────────────

export interface BasicInfoContent {
  metadata?: ModuleMetadata;
  name: string;
  phone?: string;
  email?: string;
  gender?: string;
  age?: number;
  location?: string;
  avatar?: string;
  job_title?: string;
  summary?: string;
  status?: string;
  hometown?: string;
  homepage_url?: string;
  github_url?: string;
  blog_url?: string;
  custom_fields?: Array<{ key: string; value: string }>;
}

export interface ListModuleContent<T extends BaseItem = BaseItem> {
  metadata?: ModuleMetadata;
  items: T[];
}

export interface SkillsContent {
  metadata?: ModuleMetadata;
  items: SkillItem[];
  show_levels?: boolean;
}

export interface SocialLinksContent {
  metadata?: ModuleMetadata;
  items: SocialProfileItem[];
}

export interface OtherContent {
  metadata?: ModuleMetadata;
  title?: string;
  content?: string;
}

export interface CustomContent {
  metadata?: ModuleMetadata;
  title?: string;
  content?: string;
  items?: CustomSectionItem[];
}

/** 模块类型 → content 类型映射（用于类型安全的表单分发） */
export type ModuleContentMap = {
  basic_info: BasicInfoContent;
  education: ListModuleContent<EducationItem>;
  work_experience: ListModuleContent<WorkExperienceItem>;
  project_experience: ListModuleContent<ProjectExperienceItem>;
  skills: SkillsContent;
  language: ListModuleContent<LanguageItem>;
  honors: ListModuleContent<HonorItem>;
  certificates: ListModuleContent<CertificateItem>;
  interests: ListModuleContent<InterestItem>;
  club_activities: ListModuleContent<ClubActivityItem>;
  publications: ListModuleContent<PublicationItem>;
  recommendation: ListModuleContent<RecommendationItem>;
  social_links: SocialLinksContent;
  other: OtherContent;
  custom: CustomContent;
};

/** 模块默认中文标题（与后端 DEFAULT_MODULE_LABELS 对齐） */
export const MODULE_LABELS: Record<ModuleType, string> = {
  basic_info: "基本信息",
  education: "教育经历",
  work_experience: "工作经历",
  project_experience: "项目经历",
  skills: "专业技能",
  language: "语言能力",
  honors: "荣誉奖项",
  certificates: "证书",
  interests: "兴趣爱好",
  club_activities: "社团活动",
  publications: "研究成果",
  recommendation: "推荐人",
  social_links: "社交链接",
  other: "其他",
  custom: "自定义",
};

/** 从 content 中提取模块标题（优先 metadata.title，兜底 MODULE_LABELS） */
export function getModuleTitle(content: ModuleContent, moduleType: ModuleType): string {
  const meta = content.metadata as ModuleMetadata | undefined;
  if (meta?.title) return meta.title;
  return MODULE_LABELS[moduleType] ?? moduleType;
}

/** 从 content 中提取 items 列表（兼容 entries / categories / string[]） */
export function getModuleItems(content: ModuleContent): BaseItem[] {
  if (Array.isArray(content.items)) return content.items as BaseItem[];
  if (Array.isArray(content.entries)) return content.entries as BaseItem[];
  if (Array.isArray(content.categories)) {
    // skills 旧格式：展平
    const items: SkillItem[] = [];
    for (const cat of content.categories as Array<{ name: string; items: string[] }>) {
      for (const name of cat.items ?? []) {
        items.push({ id: `skill_${name}`, name, category: cat.name });
      }
    }
    return items;
  }
  return [];
}

/** 简历模块 */
export interface ResumeModule {
  id: number;
  resume_id: number;
  module_type: ModuleType;
  content: ModuleContent;
  sort_order: number;
  created_at: string;
}

/** 创建/更新模块请求 */
export interface ResumeModuleInput {
  module_type: ModuleType;
  content: ModuleContent;
  sort_order: number;
}

/** 简历样式配置 */
export interface ResumeStyle {
  template_id: string;
  font_family: string;
  font_size: string;
  line_height: number;
  spacing: string;
  accent_color: string;
  margin: string;
  page_size: string;
  section_spacing: string;
  custom_css: string;
  /** 隐藏的模块类型（显隐控制，渲染时过滤，后端同步支持） */
  hidden_modules?: string[];
}

/** Builder 简历响应（含模块列表） */
export interface BuilderResume {
  id: number;
  filename: string;
  status: string;
  source: string;
  style: ResumeStyle | null;
  version: number;
  created_at: string;
  is_indexed?: boolean;
  is_stale?: boolean;
  modules: ResumeModule[];
}

/** 新建 builder 简历请求 */
export interface BuilderCreateRequest {
  filename?: string;
  modules?: ResumeModuleInput[];
  style?: ResumeStyle | null;
}

/** 保存请求（draft / complete 共用） */
export interface BuilderUpdateRequest {
  version?: number;
  filename?: string;
  modules?: ResumeModuleInput[];
  style?: ResumeStyle | null;
}

/** 编辑锁响应 */
export interface EditLockResponse {
  locked: boolean;
  lock_token: string | null;
  holder_id: number | null;
}

/** 反解析结果 */
export interface ParseToModulesResult {
  modules: ResumeModuleInput[];
  total: number;
}

// ── API 函数 ──────────────────────────────────────────────────

/** 新建 builder 简历 */
export async function createBuilderResume(
  body: BuilderCreateRequest = {},
): Promise<BuilderResume> {
  return api.post("/api/v1/resumes/builder", body) as Promise<BuilderResume>;
}

/** 获取 builder 简历 + 模块列表 */
export async function getBuilderResume(id: number): Promise<BuilderResume> {
  return api.get(`/api/v1/resumes/${id}/builder`) as Promise<BuilderResume>;
}

/** 保存草稿（last-write-wins，不查 version） */
export async function saveDraft(
  id: number,
  body: Partial<BuilderUpdateRequest>,
): Promise<BuilderResume> {
  return api.put(`/api/v1/resumes/${id}?mode=draft`, body) as Promise<BuilderResume>;
}

/** 保存并完成（乐观锁 → 合并 parsed_text → 向量化重建 → ready） */
export async function saveComplete(
  id: number,
  version: number,
  body: Partial<BuilderUpdateRequest>,
): Promise<BuilderResume> {
  return api.put(`/api/v1/resumes/${id}?mode=complete`, {
    version,
    ...body,
  }) as Promise<BuilderResume>;
}

/**
 * 获取预览 HTML（#7 修复）。
 *
 * 之前用 getPreviewUrl(?t=token) 作为 iframe src，但后端只认 Authorization header，
 * iframe src 无法带 header → 401 无法预览。改为 fetch（带 header）拿 HTML → iframe.srcDoc。
 */
/**
 * 获取预览 HTML — POST 传入当前 modules + style，后端实时渲染（不读数据库）。
 *
 * 这样样式/内容变更立即反映到预览，无需等待 5s 自动保存。
 * 首次加载（无编辑数据）时传 null，后端 fallback 到 GET（读数据库）。
 */
export async function fetchPreviewHtml(
  id: number,
  data?: { modules: ResumeModuleInput[]; style: ResumeStyle },
): Promise<string> {
  const token = localStorage.getItem("access_token");
  const headers: Record<string, string> = {
    Authorization: `Bearer ${token ?? ""}`,
    "X-Request-ID": crypto.randomUUID?.() ?? "",
  };

  // 有编辑数据 → POST 实时渲染；无数据 → GET 从数据库读取
  if (data) {
    headers["Content-Type"] = "application/json";
    const resp = await fetch(`/api/v1/resumes/${id}/preview`, {
      method: "POST",
      headers,
      body: JSON.stringify(data),
    });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: "预览加载失败" }));
      throw new Error((err as { detail?: string }).detail || `预览加载失败 (${resp.status})`);
    }
    return resp.text();
  }

  const resp = await fetch(`/api/v1/resumes/${id}/preview`, { headers });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: "预览加载失败" }));
    throw new Error((err as { detail?: string }).detail || `预览加载失败 (${resp.status})`);
  }
  return resp.text();
}

/** 导出简历（PDF/Markdown）— 返回下载 URL */
export function getExportUrl(id: number, format: "pdf" | "markdown"): string {
  const token = localStorage.getItem("access_token") || "";
  return `/api/v1/resumes/${id}/export?format=${format}&t=${token}`;
}

/** 触发浏览器下载导出文件 */
export async function downloadExport(id: number, format: "pdf" | "markdown"): Promise<void> {
  const token = localStorage.getItem("access_token");
  const resp = await fetch(
    `/api/v1/resumes/${id}/export?format=${format}`,
    {
      headers: {
        Authorization: `Bearer ${token}`,
        "X-Request-ID": crypto.randomUUID?.() ?? "",
      },
    },
  );
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: "导出失败" }));
    throw new Error((err as { detail?: string }).detail || "导出失败");
  }
  const blob = await resp.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  // 从 Content-Disposition 提取文件名，兜底用默认名
  const cd = resp.headers.get("Content-Disposition") || "";
  const match = cd.match(/filename="?(.+?)"?$/);
  a.download = match?.[1] || `resume_${id}.${format === "pdf" ? "pdf" : "md"}`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

/** 上传头像 */
export async function uploadAvatar(
  resumeId: number,
  file: File,
): Promise<{ avatar_url: string }> {
  const form = new FormData();
  form.append("file", file);
  return api.post(`/api/v1/resumes/${resumeId}/avatar`, form, true) as Promise<{
    avatar_url: string;
  }>;
}

/** 反解析纯文本→模块列表 */
export async function parseToModules(
  text: string,
): Promise<ParseToModulesResult> {
  return api.post("/api/v1/resumes/parse-to-modules", { text }) as Promise<ParseToModulesResult>;
}

// ── 内联 AI API（UP 简历对齐：一键优化 / 智能检查 / 智能改写） ──

/** AI 检查问题项 */
export interface AICheckIssue {
  severity: "high" | "medium" | "low";
  category: string;
  description: string;
}

/** 一键优化 */
export async function aiOptimize(
  resumeId: number,
  text: string,
  moduleType: string = "basic_info",
): Promise<{ optimized_text: string; original_text: string }> {
  return api.post(`/api/v1/resumes/${resumeId}/ai/optimize`, {
    text,
    module_type: moduleType,
  }) as Promise<{ optimized_text: string; original_text: string }>;
}

/** 智能检查 */
export async function aiCheck(
  resumeId: number,
  text: string,
  moduleType: string = "basic_info",
): Promise<{ issues: AICheckIssue[] }> {
  return api.post(`/api/v1/resumes/${resumeId}/ai/check`, {
    text,
    module_type: moduleType,
  }) as Promise<{ issues: AICheckIssue[] }>;
}

/** 智能改写 */
export async function aiRewrite(
  resumeId: number,
  text: string,
  instruction: string = "",
  moduleType: string = "basic_info",
): Promise<{ rewritten_text: string; original_text: string }> {
  return api.post(`/api/v1/resumes/${resumeId}/ai/rewrite`, {
    text,
    instruction,
    module_type: moduleType,
  }) as Promise<{ rewritten_text: string; original_text: string }>;
}

// ── 编辑锁 API ────────────────────────────────────────────────

/** 获取编辑锁 */
export async function acquireEditLock(
  resumeId: number,
): Promise<EditLockResponse> {
  return api.post(`/api/v1/resumes/${resumeId}/lock`) as Promise<EditLockResponse>;
}

/** 心跳续期 */
export async function renewEditLock(
  resumeId: number,
  lockToken: string,
): Promise<EditLockResponse> {
  return api.post(`/api/v1/resumes/${resumeId}/lock/heartbeat`, {
    lock_token: lockToken,
  }) as Promise<EditLockResponse>;
}

/** 释放编辑锁 */
export async function releaseEditLock(
  resumeId: number,
  lockToken: string,
): Promise<void> {
  await api.delete(
    `/api/v1/resumes/${resumeId}/lock?lock_token=${encodeURIComponent(lockToken)}`,
  );
}

// ── Builder Agent SSE ─────────────────────────────────────────

/**
 * T30: Builder Agent SSE 流式问答。调用 POST /api/v1/qa/ask/builder。
 *
 * 复用 Agent SSE 事件协议（agent_start/tool_call/tool_result/agent_done）。
 * Builder 工具集：generate_module/check_module/modify_module/rewrite_resume/ask_info。
 *
 * 返回 abort 函数用于取消请求。
 */
export function askBuilderStream(
  resume_id: number,
  question: string,
  onEvent: (event: AgentSSEEvent) => void,
  onError: (err: Error) => void,
  onDone?: () => void,
): () => void {
  const abort = new AbortController();
  let aborted = false;

  const url = "/api/v1/qa/ask/builder";

  const buildHeaders = (): Record<string, string> => ({
    "Content-Type": "application/json",
    ...(localStorage.getItem("access_token")
      ? { Authorization: `Bearer ${localStorage.getItem("access_token")}` }
      : {}),
  });

  const body = JSON.stringify({ resume_id, question });

  (async () => {
    try {
      let res = await fetch(url, {
        method: "POST",
        headers: buildHeaders(),
        body,
        signal: abort.signal,
      });

      if (res.status === 401) {
        const ok = await refreshToken();
        if (!ok) {
          notifySessionExpired();
          throw new Error("登录已过期");
        }
        res = await fetch(url, {
          method: "POST",
          headers: buildHeaders(),
          body,
          signal: abort.signal,
        });
      }

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "请求失败" }));
        throw new Error((err as { detail?: string }).detail || "请求失败");
      }

      const reader = res.body?.getReader();
      if (!reader) throw new Error("无法读取响应流");

      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split("\n\n");
        buffer = parts.pop() || "";

        for (const part of parts) {
          const line = part.trim();
          if (!line.startsWith("data: ")) continue;
          try {
            const data: AgentSSEEvent = JSON.parse(line.slice(6));
            onEvent(data);
          } catch {
            // 跳过解析失败的行
          }
        }
      }
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") {
        aborted = true;
        return;
      }
      onError(err instanceof Error ? err : new Error("Builder 请求失败"));
    } finally {
      if (!aborted) onDone?.();
    }
  })();

  return () => abort.abort();
}
