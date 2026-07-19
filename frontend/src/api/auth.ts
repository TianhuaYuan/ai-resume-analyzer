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
