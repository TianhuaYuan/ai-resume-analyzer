import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// 每个用例重新加载模块，避免上一用例的 token 残留
let logout: () => Promise<void>;
let forgotPassword: (email: string) => Promise<string>;
let resetPassword: (token: string, newPassword: string) => Promise<string>;

beforeEach(async () => {
  vi.resetModules();
  localStorage.clear();
  const mod = await import("./auth");
  logout = mod.logout;
  forgotPassword = mod.forgotPassword;
  resetPassword = mod.resetPassword;
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function mockFetchOk(body: unknown = { detail: "已登出" }) {
  return vi.fn(async () => new Response(JSON.stringify(body), { status: 200 }));
}

function mockFetch(status: number) {
  return vi.fn(async () => new Response("err", { status }));
}

describe("auth.logout 调后端撤销令牌 (SEC-005 前端)", () => {
  it("有 token 时 POST /api/v1/auth/logout 并带 Authorization 头，成功后清本地", async () => {
    localStorage.setItem("access_token", "tok-A");
    localStorage.setItem("refresh_token", "tok-R");
    const fetchMock = mockFetchOk();
    vi.stubGlobal("fetch", fetchMock);

    await logout();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/auth/logout");
    expect(init?.method).toBe("POST");
    expect((init?.headers as Record<string, string>)?.Authorization).toBe("Bearer tok-A");
    expect(localStorage.getItem("access_token")).toBeNull();
    expect(localStorage.getItem("refresh_token")).toBeNull();
  });

  it("后端返回 500 时仍清本地（登出不阻塞用户）", async () => {
    localStorage.setItem("access_token", "tok-A");
    const fetchMock = mockFetch(500);
    vi.stubGlobal("fetch", fetchMock);

    await logout();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(localStorage.getItem("access_token")).toBeNull();
  });

  it("后端返回 401（token 已过期）时仍清本地，用户体感登出成功", async () => {
    localStorage.setItem("access_token", "tok-A");
    const fetchMock = mockFetch(401);
    vi.stubGlobal("fetch", fetchMock);

    await logout();

    // 401 触发 client.ts 的 refreshToken 逻辑，但 refresh_token 也没有 → 直接 clearSessionAndRedirect
    // 这里只断言：localStorage 被清，且 fetch 至少调用了 logout 请求
    expect(fetchMock).toHaveBeenCalled();
    // client.ts 在 401 + 刷新失败时会 localStorage.clear() + window.location.href = "/login"
    // 所以 access_token 一定没了
    expect(localStorage.getItem("access_token")).toBeNull();
  });

  it("无 token 时不发请求，直接清本地（幂等）", async () => {
    const fetchMock = mockFetchOk();
    vi.stubGlobal("fetch", fetchMock);

    await logout();

    expect(fetchMock).not.toHaveBeenCalled();
    expect(localStorage.getItem("access_token")).toBeNull();
  });
});

describe("auth.forgotPassword (Task 1.2)", () => {
  it("POST /api/v1/auth/forgot-password 含 email 字段，返回 detail 文案", async () => {
    const fetchMock = mockFetchOk({ detail: "若邮箱存在，重置链接已发送" });
    vi.stubGlobal("fetch", fetchMock);

    const detail = await forgotPassword("user@example.com");

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/auth/forgot-password");
    expect(init?.method).toBe("POST");
    const body = JSON.parse(init?.body as string);
    expect(body.email).toBe("user@example.com");
    expect(detail).toBe("若邮箱存在，重置链接已发送");
  });

  it("无 Authorization 头（公开端点，用户未登录）", async () => {
    const fetchMock = mockFetchOk({ detail: "若邮箱存在，重置链接已发送" });
    vi.stubGlobal("fetch", fetchMock);

    await forgotPassword("user@example.com");

    const [, init] = fetchMock.mock.calls[0];
    const headers = init?.headers as Record<string, string>;
    expect(headers?.Authorization).toBeUndefined();
  });

  it("后端 422（邮箱格式错）抛异常含错误消息", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ detail: "邮箱格式不合法" }), { status: 422 })
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(forgotPassword("not-an-email")).rejects.toThrow("邮箱格式不合法");
  });
});

describe("auth.resetPassword (Task 1.2)", () => {
  it("POST /api/v1/auth/reset-password 含 token + new_password，返回 detail 文案", async () => {
    const fetchMock = mockFetchOk({ detail: "密码已重置，请使用新密码登录" });
    vi.stubGlobal("fetch", fetchMock);

    const detail = await resetPassword("token-abc", "NewPass123!");

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/auth/reset-password");
    expect(init?.method).toBe("POST");
    const body = JSON.parse(init?.body as string);
    expect(body.token).toBe("token-abc");
    expect(body.new_password).toBe("NewPass123!");
    expect(detail).toBe("密码已重置，请使用新密码登录");
  });

  it("无 Authorization 头（公开端点）", async () => {
    const fetchMock = mockFetchOk({ detail: "密码已重置" });
    vi.stubGlobal("fetch", fetchMock);

    await resetPassword("tok", "NewPass123!");

    const [, init] = fetchMock.mock.calls[0];
    const headers = init?.headers as Record<string, string>;
    expect(headers?.Authorization).toBeUndefined();
  });

  it("后端 400（token 无效）抛异常含错误消息", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ detail: "无效或过期的重置凭证" }), { status: 400 })
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(resetPassword("invalid-token", "NewPass123!")).rejects.toThrow(
      "无效或过期的重置凭证"
    );
  });

  it("后端 422（密码强度不足）抛异常含错误消息", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ detail: "密码至少8位" }), { status: 422 })
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(resetPassword("tok", "short")).rejects.toThrow("密码至少8位");
  });
});
