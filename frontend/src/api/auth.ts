import { api } from "./client";

interface LoginData {
  access_token: string;
  refresh_token: string;
}

export async function login(email: string, password: string): Promise<LoginData> {
  const data = await api.post("/api/v1/auth/login", { email, password }) as LoginData;
  localStorage.setItem("access_token", data.access_token);
  localStorage.setItem("refresh_token", data.refresh_token);
  return data;
}

export async function register(
  username: string,
  email: string,
  password: string,
  password_confirm: string,
  verification_code: string
) {
  return api.post("/api/v1/auth/register", {
    username,
    email,
    password,
    password_confirm,
    verification_code,
  });
}

/** 导出下载（GET 附件，需 blob；不走 api.get 的 JSON 解析） */
async function downloadExport(path: string, filename: string): Promise<void> {
  const token = localStorage.getItem("access_token");
  const res = await fetch(path, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) throw new Error(`导出失败（${res.status}）`);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

/** E4 导出增强：全量 JSON 导出（走 api.get 解析后由前端构造 JSON 文件下载） */
export async function exportDataJson(): Promise<void> {
  const data = await api.get("/api/v1/auth/export-data");
  const blob = new Blob([JSON.stringify(data, null, 2)], {
    type: "application/json;charset=utf-8",
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "resumes.json";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

/** E4 导出增强：简历模块全字段 CSV 长表（Excel/Sheets 直开） */
export function exportDataCsv(): Promise<void> {
  return downloadExport("/api/v1/auth/export-data/csv", "resumes.csv");
}

/** E4 导出增强：简历 Markdown 摘要 */
export function exportDataMarkdown(): Promise<void> {
  return downloadExport("/api/v1/auth/export-data/markdown", "resumes.md");
}

export async function sendCode(email: string): Promise<string> {
  const data = await api.post("/api/v1/auth/send-code", { email }) as { detail: string };
  return data.detail;
}

/**
 * 登出：先调后端撤销 JTI（SEC-005），再清本地 token。
 *
 * 后端失败不阻塞用户登出：即便 /logout 返回 5xx 或网络断开，
 * 本地 token 也会被清掉，用户体感登出成功。
 * 已签发的 token 在过期前仍有效（30min），但 JTI 黑名单失败可接受，
 * 强行阻塞用户反而暴露撤销机制的存在感。
 */
export async function logout() {
  const token = localStorage.getItem("access_token");
  if (token) {
    try {
      await api.post("/api/v1/auth/logout");
    } catch {
      // 静默吞掉：本地清理必须继续执行
    }
  }
  localStorage.removeItem("access_token");
  localStorage.removeItem("refresh_token");
}

/** C3：注销当前用户账户（级联清理全部数据，不可撤销） */
export async function deleteAccount(): Promise<void> {
  await api.delete("/api/v1/auth/account");
}

/**
 * 发起密码重置：新流程。
 *
 * 验证码通过后，后端直接修改密码（不再发送重置链接）。
 * 邮箱不存在时后端静默返回 200（防用户枚举）。
 *
 * 公开端点：不带 Authorization 头，调用时用户处于未登录状态。
 */
export async function forgotPassword(
    email: string,
    verification_code: string,
    new_password: string
): Promise<string> {
    const data = await api.post("/api/v1/auth/forgot-password", {
        email,
        verification_code,
        new_password,
    }) as { detail: string };
    return data.detail;
}

/**
 * 修改密码（登录状态下）。
 * 支持两种方式：旧密码验证 / 邮箱验证码。
 */
export async function changePassword(params: {
    mode: "password" | "code";
    old_password?: string;
    verification_code?: string;
    new_password: string;
}): Promise<string> {
    const data = await api.put("/api/v1/auth/password", params) as { detail: string };
    return data.detail;
}

/**
 * 修改邮箱（登录状态下）。
 */
export async function changeEmail(new_email: string, verification_code: string): Promise<string> {
    const data = await api.put("/api/v1/auth/email", { new_email, verification_code }) as { detail: string };
    return data.detail;
}

/**
 * 修改用户名（登录状态下）。
 */
export async function changeUsername(new_username: string): Promise<string> {
    const data = await api.put("/api/v1/auth/username", { new_username }) as { detail: string };
    return data.detail;
}

interface UserInfo {
    id: number;
    username: string;
    email: string;
    /** #9: 是否管理员 */
    is_admin?: boolean;
}

/**
 * 获取当前登录用户信息。
 */
export async function getCurrentUser(): Promise<UserInfo> {
    return api.get("/api/v1/auth/me") as Promise<UserInfo>;
}
