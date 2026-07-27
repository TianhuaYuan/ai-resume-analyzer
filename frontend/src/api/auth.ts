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
  password_confirm: string
) {
  return api.post("/api/v1/auth/register", {
    username,
    email,
    password,
    password_confirm,
  });
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

/**
 * Task 1.2: 发起密码重置申请。
 *
 * 后端无论邮箱是否存在都返回 200（防止用户枚举攻击），前端只需提示
 * "若邮箱存在，重置链接已发送"，不区分用户是否存在。
 *
 * 公开端点：不带 Authorization 头，调用时用户处于未登录状态。
 */
export async function forgotPassword(email: string): Promise<string> {
  const data = await api.post("/api/v1/auth/forgot-password", { email }) as { detail: string };
  return data.detail;
}

/**
 * Task 1.2: 完成密码重置。
 *
 * 用 reset token + 新密码提交到后端，后端校验 token（decode + type=reset +
 * 未撤销 + 一次性）后更新密码哈希并撤销 token jti。
 *
 * 公开端点：不带 Authorization 头。
 */
export async function resetPassword(token: string, newPassword: string): Promise<string> {
  const data = await api.post("/api/v1/auth/reset-password", {
    token,
    new_password: newPassword,
  }) as { detail: string };
  return data.detail;
}
