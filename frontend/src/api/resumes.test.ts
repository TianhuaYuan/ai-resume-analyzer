/**
 * exportResume 测试：验证正确读取 localStorage key。
 *
 * 问题：exportResume 使用 "token" 而非 "access_token"，导致永久 401。
 */

import { describe, it, expect, vi, beforeEach } from "vitest";

// Task 1.3: retryResume 测试
describe("retryResume (Task 1.3)", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it("POST /api/v1/resumes/{id}/retry 返回 UploadAsyncResult", async () => {
    localStorage.setItem("access_token", "tok-A");
    const fetchMock = vi.fn(async () =>
      new Response(
        JSON.stringify({ id: 42, filename: "retry.pdf", status: "processing" }),
        { status: 202 }
      )
    );
    vi.stubGlobal("fetch", fetchMock);

    const { retryResume } = await import("./resumes");
    const result = await retryResume(42);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/resumes/42/retry");
    expect(init?.method).toBe("POST");
    const headers = init?.headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer tok-A");
    expect(result).toEqual({ id: 42, filename: "retry.pdf", status: "processing" });
  });

  it("后端 409（非 failed 状态）抛异常含错误消息", async () => {
    localStorage.setItem("access_token", "tok-A");
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ detail: "当前状态不允许重试" }), { status: 409 })
    );
    vi.stubGlobal("fetch", fetchMock);

    const { retryResume } = await import("./resumes");
    await expect(retryResume(42)).rejects.toThrow("当前状态不允许重试");
  });

  it("后端 404（简历不存在）抛异常含错误消息", async () => {
    localStorage.setItem("access_token", "tok-A");
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ detail: "简历不存在" }), { status: 404 })
    );
    vi.stubGlobal("fetch", fetchMock);

    const { retryResume } = await import("./resumes");
    await expect(retryResume(999)).rejects.toThrow("简历不存在");
  });
});

describe('exportResume', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
  });

  it('reads access_token from localStorage', async () => {
    const mockToken = 'test-access-token-123';
    localStorage.setItem('access_token', mockToken);

    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      text: async () => '# 测试简历\n\n内容',
    });

    await import('./resumes').then(({ exportResume }) => exportResume(1));

    expect(fetch).toHaveBeenCalledWith(
      '/api/v1/resumes/1/export?format=markdown',
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: `Bearer ${mockToken}`,
        }),
      })
    );
  });

  it('does not use "token" as localStorage key', async () => {
    localStorage.setItem('token', 'wrong-token');
    localStorage.setItem('access_token', 'correct-token');

    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      text: async () => '# 测试简历',
    });

    await import('./resumes').then(({ exportResume }) => exportResume(1));

    expect(fetch).toHaveBeenCalledWith(
      '/api/v1/resumes/1/export?format=markdown',
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: 'Bearer correct-token',
        }),
      })
    );
  });

  it('throws error when response is not ok', async () => {
    localStorage.setItem('access_token', 'test-token');

    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
    });

    await expect(
      import('./resumes').then(({ exportResume }) => exportResume(1))
    ).rejects.toThrow('导出失败: 401');
  });
});

// ── Task 2.6: uploadResume Idempotency-Key 幂等键 ──

describe("uploadResume Idempotency-Key (Task 2.6)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    localStorage.setItem("access_token", "tok-A");
  });

  it("默认基于 file 元信息（name+size+lastModified）生成 hash 作为 Idempotency-Key", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(
        JSON.stringify({ id: 1, filename: "a.pdf", status: "processing" }),
        { status: 202 }
      )
    );
    vi.stubGlobal("fetch", fetchMock);

    const { uploadResume } = await import("./resumes");
    const file = new File(["content"], "a.pdf", { type: "application/pdf" });
    Object.defineProperty(file, "size", { value: 1024 });
    Object.defineProperty(file, "lastModified", { value: 1700000000000 });

    await uploadResume(file);

    const init = fetchMock.mock.calls[0][1] as RequestInit;
    const headers = init.headers as Record<string, string>;
    expect(headers["Idempotency-Key"]).toBeTruthy();
    // 应为 hex 字符串（hash 输出），非 UUID
    expect(headers["Idempotency-Key"]).toMatch(/^[a-f0-9]{32,}$/);
  });

  it("同文件重复上传生成相同 Idempotency-Key（同文件去重）", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(
        JSON.stringify({ id: 1, filename: "a.pdf", status: "processing" }),
        { status: 202 }
      )
    );
    vi.stubGlobal("fetch", fetchMock);

    const { uploadResume } = await import("./resumes");
    const file1 = new File(["content"], "a.pdf", { type: "application/pdf" });
    Object.defineProperty(file1, "size", { value: 1024 });
    Object.defineProperty(file1, "lastModified", { value: 1700000000000 });

    const file2 = new File(["content"], "a.pdf", { type: "application/pdf" });
    Object.defineProperty(file2, "size", { value: 1024 });
    Object.defineProperty(file2, "lastModified", { value: 1700000000000 });

    await uploadResume(file1);
    await uploadResume(file2);

    const init1 = fetchMock.mock.calls[0][1] as RequestInit;
    const init2 = fetchMock.mock.calls[1][1] as RequestInit;
    const key1 = (init1.headers as Record<string, string>)["Idempotency-Key"];
    const key2 = (init2.headers as Record<string, string>)["Idempotency-Key"];
    expect(key1).toBe(key2);
  });

  it("不同文件生成不同 Idempotency-Key", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(
        JSON.stringify({ id: 1, filename: "a.pdf", status: "processing" }),
        { status: 202 }
      )
    );
    vi.stubGlobal("fetch", fetchMock);

    const { uploadResume } = await import("./resumes");
    const file1 = new File(["content1"], "a.pdf", { type: "application/pdf" });
    Object.defineProperty(file1, "size", { value: 1024 });
    Object.defineProperty(file1, "lastModified", { value: 1700000000000 });

    const file2 = new File(["content2"], "b.pdf", { type: "application/pdf" });
    Object.defineProperty(file2, "size", { value: 2048 });
    Object.defineProperty(file2, "lastModified", { value: 1800000000000 });

    await uploadResume(file1);
    await uploadResume(file2);

    const init1 = fetchMock.mock.calls[0][1] as RequestInit;
    const init2 = fetchMock.mock.calls[1][1] as RequestInit;
    const key1 = (init1.headers as Record<string, string>)["Idempotency-Key"];
    const key2 = (init2.headers as Record<string, string>)["Idempotency-Key"];
    expect(key1).not.toBe(key2);
  });

  it("overrideKey 参数优先于 file hash（重试场景复用旧 key）", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(
        JSON.stringify({ id: 1, filename: "a.pdf", status: "processing" }),
        { status: 202 }
      )
    );
    vi.stubGlobal("fetch", fetchMock);

    const { uploadResume } = await import("./resumes");
    const file = new File(["content"], "a.pdf", { type: "application/pdf" });
    Object.defineProperty(file, "size", { value: 1024 });
    Object.defineProperty(file, "lastModified", { value: 1700000000000 });

    const overrideKey = "custom-retry-key-12345";
    await uploadResume(file, overrideKey);

    const init = fetchMock.mock.calls[0][1] as RequestInit;
    const headers = init.headers as Record<string, string>;
    expect(headers["Idempotency-Key"]).toBe(overrideKey);
  });

  it("FormData body 仍正确传递（isFormData=true 不破坏 Content-Type）", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(
        JSON.stringify({ id: 1, filename: "a.pdf", status: "processing" }),
        { status: 202 }
      )
    );
    vi.stubGlobal("fetch", fetchMock);

    const { uploadResume } = await import("./resumes");
    const file = new File(["content"], "a.pdf", { type: "application/pdf" });
    Object.defineProperty(file, "size", { value: 1024 });
    Object.defineProperty(file, "lastModified", { value: 1700000000000 });

    await uploadResume(file);

    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.body).toBeInstanceOf(FormData);
    // isFormData=true 时不应显式设 Content-Type（浏览器自动 multipart）
    const headers = init.headers as Record<string, string>;
    expect(headers["Content-Type"]).toBeUndefined();
  });
});