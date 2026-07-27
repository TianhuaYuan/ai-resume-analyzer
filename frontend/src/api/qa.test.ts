import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { askQuestionStream, shouldSkipEvent, getHistory, clearHistory, deleteQa, type SSEEvent } from "./qa";

// 拦截 client 的刷新，避免真实网络；保留 notifySessionExpired 原实现（只是 dispatch 事件）
vi.mock("./client", async () => {
  const actual = await vi.importActual<typeof import("./client")>("./client");
  return {
    ...actual,
    api: { post: vi.fn(), get: vi.fn(), delete: vi.fn() },
    refreshToken: vi.fn(),
  };
});

import { api } from "./client";
import { refreshToken } from "./client";

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
  vi.mocked(api.get).mockReset();
  vi.mocked(api.delete).mockReset();
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

  it("H10: 刷新失败则触发 session:expired 事件并抛错", async () => {
    const fetchMock = vi.fn(async () => new Response("", { status: 401 }));
    vi.stubGlobal("fetch", fetchMock);
    vi.mocked(refreshToken).mockResolvedValue(false);

    const handler = vi.fn();
    window.addEventListener("session:expired", handler);

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

    expect(handler).toHaveBeenCalledTimes(1);
    expect(errs[0].message).toBe("登录已过期");
    window.removeEventListener("session:expired", handler);
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

  // ── Task 2.3: mode 参数 ──

  it("Task 2.3: 不传 mode 时默认走 stream 模式（URL 不带 query）", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(makeSSE([ev({ type: "done", sources: [] })]), { status: 200 })
    );
    vi.stubGlobal("fetch", fetchMock);

    await new Promise<void>((resolve) => {
      askQuestionStream(1, "q", () => {}, () => {}, () => resolve());
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const callUrl = fetchMock.mock.calls[0][0] as string;
    expect(callUrl).toBe("/api/v1/qa/ask/stream");
  });

  it("Task 2.3: 传 mode='agentic' 时 URL 附加 ?mode=agentic", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(makeSSE([ev({ type: "done", sources: [] })]), { status: 200 })
    );
    vi.stubGlobal("fetch", fetchMock);

    await new Promise<void>((resolve) => {
      askQuestionStream(1, "q", () => {}, () => {}, () => resolve(), { mode: "agentic" });
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const callUrl = fetchMock.mock.calls[0][0] as string;
    expect(callUrl).toBe("/api/v1/qa/ask/stream?mode=agentic");
  });

  it("Task 2.3: 传 mode='stream' 时 URL 仍附加 ?mode=stream（显式传递）", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(makeSSE([ev({ type: "done", sources: [] })]), { status: 200 })
    );
    vi.stubGlobal("fetch", fetchMock);

    await new Promise<void>((resolve) => {
      askQuestionStream(1, "q", () => {}, () => {}, () => resolve(), { mode: "stream" });
    });

    const callUrl = fetchMock.mock.calls[0][0] as string;
    expect(callUrl).toBe("/api/v1/qa/ask/stream?mode=stream");
  });

  it("Task 2.3: 401 刷新重试时保留原 mode 参数", async () => {
    const fetchMock = vi.fn(async () => {
      if (fetchMock.mock.calls.length === 1) return new Response("", { status: 401 });
      return new Response(makeSSE([ev({ type: "done", sources: [] })]), { status: 200 });
    });
    vi.stubGlobal("fetch", fetchMock);
    vi.mocked(refreshToken).mockResolvedValue(true);

    await new Promise<void>((resolve) => {
      askQuestionStream(1, "q", () => {}, () => {}, () => resolve(), { mode: "agentic" });
    });

    expect(fetchMock).toHaveBeenCalledTimes(2);
    const url1 = fetchMock.mock.calls[0][0] as string;
    const url2 = fetchMock.mock.calls[1][0] as string;
    expect(url1).toBe("/api/v1/qa/ask/stream?mode=agentic");
    expect(url2).toBe("/api/v1/qa/ask/stream?mode=agentic");
  });
});

describe("getHistory (Task 4 keyword 搜索)", () => {
  it("无 keyword 时只带 limit/offset 参数", async () => {
    vi.mocked(api.get).mockResolvedValue({ items: [], total: 0 });
    await getHistory(42, 20, 0);
    expect(api.get).toHaveBeenCalledWith(
      "/api/v1/qa/history/42?limit=20&offset=0"
    );
  });

  it("有 keyword 时拼到 query string", async () => {
    vi.mocked(api.get).mockResolvedValue({ items: [], total: 0 });
    await getHistory(42, 20, 0, "Python");
    expect(api.get).toHaveBeenCalledWith(
      "/api/v1/qa/history/42?limit=20&offset=0&keyword=Python"
    );
  });

  it("keyword 是空白字符串时不拼参数（避免空搜索）", async () => {
    vi.mocked(api.get).mockResolvedValue({ items: [], total: 0 });
    await getHistory(42, 20, 0, "   ");
    expect(api.get).toHaveBeenCalledWith(
      "/api/v1/qa/history/42?limit=20&offset=0"
    );
  });
});

describe("clearHistory (Task 4 清空历史)", () => {
  it("DELETE /api/v1/qa/history/{id} 带正确路径", async () => {
    vi.mocked(api.delete).mockResolvedValue({ deleted_count: 5 });
    const result = await clearHistory(42);
    expect(api.delete).toHaveBeenCalledWith("/api/v1/qa/history/42");
    expect(result.deleted_count).toBe(5);
  });

  it("后端返回 404 时抛 Error（简历不存在）", async () => {
    vi.mocked(api.delete).mockRejectedValue(new Error("简历不存在"));
    await expect(clearHistory(99999)).rejects.toThrow("简历不存在");
  });
});

describe("deleteQa (Task 4 删单条)", () => {
  it("DELETE /api/v1/qa/{qa_id} 带正确路径", async () => {
    vi.mocked(api.delete).mockResolvedValue(undefined);
    await deleteQa(123);
    expect(api.delete).toHaveBeenCalledWith("/api/v1/qa/123");
  });

  it("后端返回 404 时抛 Error（qa 不存在）", async () => {
    vi.mocked(api.delete).mockRejectedValue(new Error("问答记录不存在"));
    await expect(deleteQa(99999)).rejects.toThrow("问答记录不存在");
  });
});
