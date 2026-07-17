import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// 每个用例都重新加载模块，保证单飞锁模块变量 refreshPromise 从干净状态开始
let refreshToken: () => Promise<boolean>;

beforeEach(async () => {
  vi.resetModules();
  localStorage.clear();
  const mod = await import("./client");
  refreshToken = mod.refreshToken;
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("refreshToken 单飞锁 (C1)", () => {
  it("并发 401 只发起一次真实刷新请求", async () => {
    localStorage.setItem("refresh_token", "old-refresh");
    const fetchMock = vi.fn(
      async () =>
        new Response(
          JSON.stringify({ access_token: "new-access", refresh_token: "new-refresh" }),
          { status: 200 }
        )
    );
    vi.stubGlobal("fetch", fetchMock);

    const [a, b] = await Promise.all([refreshToken(), refreshToken()]);

    expect(a).toBe(true);
    expect(b).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(localStorage.getItem("access_token")).toBe("new-access");
  });

  it("无 refresh_token 时直接返回 false，不发起请求，且释放锁", async () => {
    const fetchMock = vi.fn(
      async () =>
        new Response(
          JSON.stringify({ access_token: "a2", refresh_token: "r2" }),
          { status: 200 }
        )
    );
    vi.stubGlobal("fetch", fetchMock);

    // 第一次：没有 refresh_token → false，且不调用 fetch
    expect(await refreshToken()).toBe(false);
    expect(fetchMock).not.toHaveBeenCalled();

    // 补上 refresh_token 后再调用 → 锁已释放，真正发起请求并成功
    localStorage.setItem("refresh_token", "r");
    expect(await refreshToken()).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("刷新失败返回 false，并释放锁以便后续重试", async () => {
    localStorage.setItem("refresh_token", "r");
    const fetchMock = vi.fn(async () => new Response("err", { status: 500 }));
    vi.stubGlobal("fetch", fetchMock);

    expect(await refreshToken()).toBe(false);
    // 锁已释放：第二次调用会再次真正发起请求
    expect(await refreshToken()).toBe(false);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
