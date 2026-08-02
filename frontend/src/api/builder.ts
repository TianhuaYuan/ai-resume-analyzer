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
