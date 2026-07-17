import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { askQuestionStream, shouldSkipEvent, type SSEEvent } from "./qa";

// 拦截 client 的刷新/跳转，避免真实网络与页面跳转
vi.mock("./client", () => ({
  api: { post: vi.fn(), get: vi.fn(), delete: vi.fn() },
  refreshToken: vi.fn(),
  clearSessionAndRedirect: vi.fn(),
}));

import { refreshToken, clearSessionAndRedirect } from "./client";

function makeSSE(chunks: string[]): ReadableStream<Uint8Array> {
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const c of chunks) controller.enqueue(new TextEncoder().encode(c));
      controller.close();
    },
  });
}

const ev = (e: Partial<SSEEvent> & { type: SSEEvent["type"] }) =>
  `data: ${JSON.stringify(e)}\n\n`;

beforeEach(() => {
  localStorage.setItem("access_token", "x");
  vi.mocked(refreshToken).mockReset();
  vi.mocked(clearSessionAndRedirect).mockReset();
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("shouldSkipEvent 纯函数 (N5)", () => {
  it("后端未下发 id 时不去重", () => {
    const seen = new Set<string>();
    const e = { type: "token", content: "a" } as SSEEvent;
    expect(shouldSkipEvent(seen, e)).toBe(false);
    expect(shouldSkipEvent(seen, e)).toBe(false);
  });
  it("相同 id 第二次返回 true", () => {
    const seen = new Set<string>();
    const e = { id: 5, type: "token" } as SSEEvent;
    expect(shouldSkipEvent(seen, e)).toBe(false);
    expect(shouldSkipEvent(seen, e)).toBe(true);
  });
});

describe("askQuestionStream", () => {
  it("H10: 流式 401 先刷新再重试一次", async () => {
    const order: number[] = [];
    const fetchMock = vi.fn(async () => {
      order.push(order.length);
      if (order.length === 1) return new Response("", { status: 401 });
      return new Response(
        makeSSE([
          ev({ id: 1, type: "token", content: "hi" }),
          ev({ id: 2, type: "done", sources: [] }),
        ]),
        { status: 200 }
      );
    });
    vi.stubGlobal("fetch", fetchMock);
    vi.mocked(refreshToken).mockResolvedValue(true);

    const events: SSEEvent[] = [];
    await new Promise<void>((resolve) => {
      askQuestionStream(1, "q", (e) => events.push(e), () => {}, () => resolve());
    });

    expect(refreshToken).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(events.map((e) => e.type)).toEqual(["token", "done"]);
  });

  it("H10: 刷新失败则跳转登录页并抛错", async () => {
    const fetchMock = vi.fn(async () => new Response("", { status: 401 }));
    vi.stubGlobal("fetch", fetchMock);
    vi.mocked(refreshToken).mockResolvedValue(false);

    const errs: Error[] = [];
    await new Promise<void>((resolve) => {
      askQuestionStream(
        1,
        "q",
        () => {},
        (e) => {
          errs.push(e);
          resolve();
        },
        () => {}
      );
    });

    expect(clearSessionAndRedirect).toHaveBeenCalledTimes(1);
    expect(errs[0].message).toBe("登录已过期");
  });

  it("C2: 流正常结束但缺 done 事件，onDone 仍被调用、onError 不被调用", async () => {
    const stream = makeSSE([ev({ type: "token", content: "abc" })]);
    vi.stubGlobal("fetch", vi.fn(async () => new Response(stream, { status: 200 })));

    const events: SSEEvent[] = [];
    let doneCalled = false;
    let errorCalled = false;
    await new Promise<void>((resolve) => {
      askQuestionStream(
        1,
        "q",
        (e) => events.push(e),
        () => {
          errorCalled = true;
        },
        () => {
          doneCalled = true;
          resolve();
        }
      );
    });

    expect(events.map((e) => e.type)).toEqual(["token"]);
    expect(doneCalled).toBe(true);
    expect(errorCalled).toBe(false);
  });

  it("N5: 相同 id 的 SSE 事件被去重，只投递一次", async () => {
    const stream = makeSSE([
      ev({ id: 1, type: "token", content: "A" }),
      ev({ id: 1, type: "token", content: "A" }), // 重复
      ev({ id: 2, type: "done", sources: [] }),
    ]);
    vi.stubGlobal("fetch", vi.fn(async () => new Response(stream, { status: 200 })));

    const events: SSEEvent[] = [];
    await new Promise<void>((resolve) => {
      askQuestionStream(1, "q", (e) => events.push(e), () => {}, () => resolve());
    });

    const tokens = events.filter((e) => e.type === "token");
    expect(tokens).toHaveLength(1); // 去重后只收到一次
    expect(events.map((e) => e.type)).toEqual(["token", "done"]);
  });
});
