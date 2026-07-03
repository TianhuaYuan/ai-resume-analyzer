const BASE = "";

async function refreshToken(): Promise<boolean> {
  const token = localStorage.getItem("refresh_token");
  if (!token) return false;
  try {
    const res = await fetch(`${BASE}/api/auth/refresh`, {
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

async function handleResponse(res: Response) {
  if (res.status === 204) return null;
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "请求失败" }));
    throw new Error(err.detail || "请求失败");
  }
  return res.json();
}

async function request(
  path: string,
  options: RequestInit = {}
): Promise<unknown> {
  const token = localStorage.getItem("access_token");
  const headers: Record<string, string> = {
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
    localStorage.clear();
    window.location.href = "/login";
    throw new Error("登录已过期");
  }

  return handleResponse(res);
}

export const api = {
  get: (path: string) => request(path),

  post: (path: string, body?: unknown, isFormData = false) =>
    request(path, {
      method: "POST",
      body: isFormData ? (body as FormData) : JSON.stringify(body),
      headers: isFormData
        ? undefined
        : { "Content-Type": "application/json" },
    }),

  delete: (path: string) => request(path, { method: "DELETE" }),
};
