const BASE = "";

/** 生成 UUID v4 作为前端 request_id（兼容所有浏览器） */
function generateRequestId(): string {
  const arr = new Uint8Array(16);
  if (typeof crypto !== "undefined" && typeof crypto.getRandomValues === "function") {
    crypto.getRandomValues(arr);
  } else {
    for (let i = 0; i < 16; i++) arr[i] = Math.floor(Math.random() * 256);
  }
  // UUID v4 格式：xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx
  arr[6] = (arr[6] & 0x0f) | 0x40;
  arr[8] = (arr[8] & 0x3f) | 0x80;
  return Array.from(arr, (b) => b.toString(16).padStart(2, "0")).join("").replace(
    /^(.{8})(.{4})(.{4})(.{4})(.{12})$/,
    "$1-$2-$3-$4-$5"
  );
}

// 单飞（single-flight）锁：并发的 401 只触发一次真实刷新。
// 否则多个请求同时 401 会各自刷新，后端若启用 refresh_token 轮转，
// 第二次刷新用的旧 refresh_token 已被第一次作废 → 全部失败、用户被踢登。
let refreshPromise: Promise<boolean> | null = null;

async function doRefresh(): Promise<boolean> {
  const token = localStorage.getItem("refresh_token");
  if (!token) return false;
  try {
    const res = await fetch(`${BASE}/api/v1/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: token }),
    });
    if (!res.ok) return false;
    const data = await res.json();
    localStorage.setItem("access_token", data.access_token);
    localStorage.setItem("refresh_token", data.refresh_token);
    return true;
  } catch {
    return false;
  }
}

export function refreshToken(): Promise<boolean> {
  if (!refreshPromise) {
    // 用 .finally 在微任务里释放锁：保证赋值 refreshPromise=p 先完成，
    // 再清锁。否则同步早返回时会先把锁置 null 又被赋值覆盖，导致锁永不释放。
    refreshPromise = doRefresh().finally(() => {
      refreshPromise = null;
    });
  }
  return refreshPromise;
}

/**
 * 触发「登录已过期」全局事件。
 *
 * 不在此直接跳登录页，而是发事件给 AuthProvider 处理——
 * 这样可以先弹 SessionExpiredDialog 友好提示，再由用户点按钮跳转，
 * 避免"秒退"体验。
 *
 * 如果调用方确实需要立即跳转（如登出成功后），使用 clearSessionAndRedirect。
 */
export function notifySessionExpired() {
  window.dispatchEvent(new CustomEvent("session:expired"));
}

/**
 * 应用自身使用的 localStorage key 白名单。
 * 清理会话时只删除这些 key，避免影响同域名下其他应用的数据。
 */
const APP_STORAGE_KEYS = ["access_token", "refresh_token"];

export function clearSessionAndRedirect() {
  // P1-20：不能用 localStorage.clear()，否则会清空同域名下其他应用的数据
  for (const key of APP_STORAGE_KEYS) {
    localStorage.removeItem(key);
  }
  window.location.href = "/login";
}

async function handleResponse(res: Response) {
  if (res.status === 204) return null;
  if (!res.ok) {
    const err = await res.json().catch(() => null);
    // 兼容新格式 {"error": {"code", "message", "request_id"}} 和旧格式 {"detail": "..."}
    const message =
      err?.error?.message || err?.detail || "请求失败";
    throw new Error(message);
  }
  return res.json();
}

async function request(
  path: string,
  options: RequestInit = {}
): Promise<unknown> {
  const token = localStorage.getItem("access_token");
  const headers: Record<string, string> = {
    "X-Request-ID": generateRequestId(),
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...((options.headers as Record<string, string>) || {}),
  };

  const res = await fetch(`${BASE}${path}`, { ...options, headers });

  // token 过期 → 静默刷新
  if (res.status === 401 && token) {
    const ok = await refreshToken();
    if (ok) {
      const newToken = localStorage.getItem("access_token");
      headers.Authorization = `Bearer ${newToken}`;
      return fetch(`${BASE}${path}`, { ...options, headers }).then(
        handleResponse
      );
    }
    // 刷新失败：弹全局过期提示，由用户点「去登录」再跳转
    notifySessionExpired();
    throw new Error("登录已过期");
  }

  return handleResponse(res);
}

export const api = {
  get: (path: string) => request(path),

  // Task 2.6: 扩展 headers 参数，支持 Idempotency-Key 等自定义头
  // isFormData=true 时不设 Content-Type（浏览器自动 multipart），但仍可传自定义 headers
  post: (
    path: string,
    body?: unknown,
    isFormData = false,
    headers?: Record<string, string>
  ) =>
    request(path, {
      method: "POST",
      body: isFormData ? (body as FormData) : JSON.stringify(body),
      headers: isFormData
        ? headers
        : { "Content-Type": "application/json", ...headers },
    }),

  delete: (path: string) => request(path, { method: "DELETE" }),
};
