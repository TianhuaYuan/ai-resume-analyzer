import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// 每个用例重新加载模块，避免上一用例的 token 残留
let logout: () => Promise<void>;

beforeEach(async () => {
  vi.resetModules();
  localStorage.clear();
  const mod = await import("./auth");
  logout = mod.logout;
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function mockFetchOk() {
  return vi.fn(async () => new Response(JSON.stringify({ detail: "已登出" }), { status: 200 }));
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
