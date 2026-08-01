import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { askQuestionStream, shouldSkipEvent, getHistory, clearHistory, deleteQa, askAgentStream, type SSEEvent, type AgentSSEEvent } from "./qa";

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

// ── Agent SSE 字段对齐测试（Spec 对齐） ──

const agentEv = (e: Partial<AgentSSEEvent> & { type: AgentSSEEvent["type"] }) =>
  `data: ${JSON.stringify(e)}\n\n`;

describe("askAgentStream (Spec SSE 字段对齐)", () => {
  it("传 compareIds 时 body 包含 compare_ids", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(
        makeSSE([
          agentEv({
            type: "agent_done",
            answer: "ok",
            qa_id: 1,
            token_usage: { prompt_tokens: 10, completion_tokens: 5 },
            process_trace: { rounds: 0, tool_sequence: [], duration_ms: 50 },
            sources: [],
            degraded: false,
          }),
        ]),
        { status: 200 }
      )
    );
    vi.stubGlobal("fetch", fetchMock);

    await new Promise<void>((resolve) => {
      askAgentStream(1, "q", () => {}, () => {}, () => resolve(), {
        compareIds: [2, 3],
      });
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const body = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(body.compare_ids).toEqual([2, 3]);
  });

  it("不传 compareIds 时 body 不含 compare_ids", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(
        makeSSE([
          agentEv({
            type: "agent_done",
            answer: "ok",
            qa_id: 1,
            token_usage: { prompt_tokens: 10, completion_tokens: 5 },
            process_trace: { rounds: 0, tool_sequence: [], duration_ms: 50 },
            sources: [],
            degraded: false,
          }),
        ]),
        { status: 200 }
      )
    );
    vi.stubGlobal("fetch", fetchMock);

    await new Promise<void>((resolve) => {
      askAgentStream(1, "q", () => {}, () => {}, () => resolve());
    });

    const body = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(body.compare_ids).toBeUndefined();
  });

  it("接收新 SSE 字段（tool_name/args/summary/detail/agent_thought/usage/token_usage/sources/degraded）", async () => {
    const events: AgentSSEEvent[] = [];
    const sseChunks = [
      agentEv({
        type: "agent_start",
        resume_id: 1,
        tools: [{ name: "search_resume", description: "搜索简历" }],
      }),
      agentEv({
        type: "agent_thought",
        content: "我需要先搜索简历",
      }),
      agentEv({
        type: "usage",
        prompt_tokens: 100,
        completion_tokens: 50,
        total: { prompt_tokens: 100, completion_tokens: 50 },
      }),
      agentEv({
        type: "tool_call",
        id: "tc1",
        tool_name: "search_resume",
        args: '{"query":"Python"}',
      }),
      agentEv({
        type: "tool_result",
        id: "tc1",
        tool_name: "search_resume",
        summary: "找到3个结果",
        detail: "完整结果文本...",
      }),
      agentEv({
        type: "agent_done",
        answer: "这是答案",
        qa_id: 42,
        sources: [{ text: "来源1", score: 0.9 }],
        token_usage: { prompt_tokens: 200, completion_tokens: 100 },
        process_trace: {
          rounds: 1,
          tool_sequence: ["search_resume"],
          duration_ms: 500,
        },
        degraded: false,
      }),
    ];

    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(makeSSE(sseChunks), { status: 200 }))
    );

    await new Promise<void>((resolve) => {
      askAgentStream(1, "q", (e) => events.push(e), () => {}, () => resolve());
    });

    expect(events).toHaveLength(6);

    // agent_start
    expect(events[0].type).toBe("agent_start");
    expect(events[0].resume_id).toBe(1);
    expect(events[0].tools).toHaveLength(1);
    expect(events[0].tools![0].name).toBe("search_resume");

    // agent_thought
    expect(events[1].type).toBe("agent_thought");
    expect(events[1].content).toBe("我需要先搜索简历");

    // usage
    expect(events[2].type).toBe("usage");
    expect(events[2].prompt_tokens).toBe(100);
    expect(events[2].completion_tokens).toBe(50);

    // tool_call — 用 tool_name + args（非 name + arguments）
    expect(events[3].type).toBe("tool_call");
    expect(events[3].tool_name).toBe("search_resume");
    expect(events[3].args).toBe('{"query":"Python"}');
    expect(events[3].name).toBeUndefined();
    expect(events[3].arguments).toBeUndefined();

    // tool_result — 用 tool_name + summary/detail（非 name + result）
    expect(events[4].type).toBe("tool_result");
    expect(events[4].tool_name).toBe("search_resume");
    expect(events[4].summary).toBe("找到3个结果");
    expect(events[4].detail).toBe("完整结果文本...");
    expect(events[4].result).toBeUndefined();

    // agent_done — 用 token_usage（非 usage），process_trace 是 CompactTrace
    expect(events[5].type).toBe("agent_done");
    expect(events[5].token_usage).toEqual({
      prompt_tokens: 200,
      completion_tokens: 100,
    });
    expect(events[5].usage).toBeUndefined();
    expect(events[5].process_trace).toEqual({
      rounds: 1,
      tool_sequence: ["search_resume"],
      duration_ms: 500,
    });
    expect(events[5].degraded).toBe(false);
    expect(events[5].sources).toEqual([{ text: "来源1", score: 0.9 }]);
  });

  it("401 先刷新再重试", async () => {
    const order: number[] = [];
    const fetchMock = vi.fn(async () => {
      order.push(order.length);
      if (order.length === 1) return new Response("", { status: 401 });
      return new Response(
        makeSSE([
          agentEv({
            type: "agent_done",
            answer: "ok",
            qa_id: 1,
            token_usage: { prompt_tokens: 10, completion_tokens: 5 },
            process_trace: { rounds: 0, tool_sequence: [], duration_ms: 50 },
            sources: [],
            degraded: false,
          }),
        ]),
        { status: 200 }
      );
    });
    vi.stubGlobal("fetch", fetchMock);
    vi.mocked(refreshToken).mockResolvedValue(true);

    await new Promise<void>((resolve) => {
      askAgentStream(1, "q", () => {}, () => {}, () => resolve());
    });

    expect(refreshToken).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("C2: 流正常结束后 onDone 被调用", async () => {
    const stream = makeSSE([
      agentEv({
        type: "agent_done",
        answer: "done",
        qa_id: 1,
        token_usage: { prompt_tokens: 10, completion_tokens: 5 },
        process_trace: { rounds: 0, tool_sequence: [], duration_ms: 50 },
        sources: [],
        degraded: false,
      }),
    ]);
    vi.stubGlobal("fetch", vi.fn(async () => new Response(stream, { status: 200 })));

    let doneCalled = false;
    await new Promise<void>((resolve) => {
      askAgentStream(1, "q", () => {}, () => {}, () => {
        doneCalled = true;
        resolve();
      });
    });

    expect(doneCalled).toBe(true);
  });
});
