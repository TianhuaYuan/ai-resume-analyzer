import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, fireEvent, screen, waitFor, act } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import QAPage from "../QAPage";
import { AppChatProvider } from "../../context/AppChatContext";
import { ToastProvider } from "../../components/Toast";

// v2 重构后 QAPage 用 askAgentStream（旧 askQuestionStream 已移除），
// 且挂载时自动创建/读取对话会话，需全部 mock（jsdom 无 fetch）。
vi.mock("../../api/qa", () => ({
  askAgentStream: vi.fn(() => () => {}),
  getHistory: vi.fn(async () => ({ items: [], total: 0 })),
  clearHistory: vi.fn(async () => ({ deleted_count: 0 })),
  deleteQa: vi.fn(async () => undefined),
  submitFeedback: vi.fn(async () => undefined),
  getQuota: vi.fn(async () => ({ enabled: true, used: 1000, limit: 10000, remaining: 9000, reset_at: null })),
  getConversations: vi.fn(async () => []),
  createConversation: vi.fn(async () => ({ id: 1, title: "新的对话", updated_at: "", message_count: 0 })),
  deleteConversation: vi.fn(async () => undefined),
  renameConversation: vi.fn(async () => ({ id: 1, title: "新的对话", updated_at: "" })),
}));

// QAPage 挂载时 listResumes 自动选第一份简历（优先 ready），id 需为 42（测试断言用）
const { DEFAULT_RESUME, SECOND_RESUME, BUILDER_RESUME, BUILDER_RESUME_B } = vi.hoisted(() => ({
  DEFAULT_RESUME: {
    id: 42,
    filename: "resume-42.pdf",
    parsed_text: "",
    chunk_count: 3,
    status: "ready",
    status_message: "",
    created_at: "",
  },
  SECOND_RESUME: {
    id: 43,
    filename: "resume-43.pdf",
    parsed_text: "",
    chunk_count: 1,
    status: "ready",
    status_message: "",
    created_at: "",
  },
  BUILDER_RESUME: {
    id: 42,
    filename: "resume-42.pdf",
    status: "ready",
    source: "upload",
    style: null,
    version: 1,
    created_at: "",
    modules: [{
      id: 1,
      resume_id: 42,
      module_type: "basic_info",
      content: { name: "Tianhua" },
      sort_order: 0,
      created_at: "",
    }],
  },
  BUILDER_RESUME_B: {
    id: 43,
    filename: "resume-43.pdf",
    status: "ready",
    source: "upload",
    style: null,
    version: 7,
    created_at: "",
    modules: [{
      id: 2,
      resume_id: 43,
      module_type: "basic_info",
      content: { name: "Resume B" },
      sort_order: 0,
      created_at: "",
    }],
  },
}));

vi.mock("../../api/resumes", () => ({
  listResumes: vi.fn(async () => ({ items: [DEFAULT_RESUME, SECOND_RESUME], total: 2 })),
  uploadResume: vi.fn(async () => ({ id: 42, filename: "resume.pdf", status: "processing" })),
}));

// QAPage 的 useEffect 会调用编辑锁生命周期 + 保存 + 创建简历（jsdom 无 fetch，必须全部 mock）
vi.mock("../../api/builder", () => ({
  getBuilderResume: vi.fn(async (id: number) => id === 43 ? BUILDER_RESUME_B : BUILDER_RESUME),
  saveDraft: vi.fn(async () => ({ ...BUILDER_RESUME, status: "draft" })),
  saveComplete: vi.fn(async () => ({ ...BUILDER_RESUME, status: "ready", version: 2 })),
  acquireEditLock: vi.fn(async () => ({ locked: false, lock_token: null })),
  renewEditLock: vi.fn(async () => ({ locked: false, lock_token: null })),
  releaseEditLock: vi.fn(async () => undefined),
  createBuilderResume: vi.fn(async () => ({ id: 43, filename: "未命名简历" })),
}));

vi.mock("../../components/builder/A4PreviewPanel", () => ({
  A4PreviewPanel: ({ onSelectSection }: { onSelectSection: (type: string) => void }) => (
    <button aria-label="编辑基本信息" onClick={() => onSelectSection("basic_info")}>编辑基本信息</button>
  ),
}));

vi.mock("../../components/builder/ModuleCardEditor", () => ({
  ModuleCardEditor: ({ onChange }: { onChange: (type: string, content: object) => void }) => (
    <button aria-label="修改模块" onClick={() => onChange("basic_info", { name: "Changed" })}>修改模块</button>
  ),
}));

import { getHistory, clearHistory, deleteQa, submitFeedback, getQuota, askAgentStream } from "../../api/qa";
import { getBuilderResume, saveDraft } from "../../api/builder";

function renderPage(route = "/resumes/42") {
  // P2-12：测试路由与生产 App.tsx 保持一致（/resumes/:id）
  // QAPage 使用 useAppChat（与 Sidebar 共享对话状态），需包 AppChatProvider
  // QAPage 使用 useToast（失败提示），需包 ToastProvider，否则抛 "useToast must be used within ToastProvider"
  return render(
    <ToastProvider>
      <AppChatProvider>
        <MemoryRouter initialEntries={[route]}>
          <Routes>
            <Route path="/resumes/:id" element={<QAPage />} />
          </Routes>
        </MemoryRouter>
      </AppChatProvider>
    </ToastProvider>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  // 每个测试开始时重置默认 mock 实现，避免上个测试的 mockResolvedValue 泄漏
  vi.mocked(getHistory).mockResolvedValue({ items: [], total: 0 });
  vi.mocked(clearHistory).mockResolvedValue({ deleted_count: 0 });
  vi.mocked(deleteQa).mockResolvedValue(undefined);
  vi.mocked(submitFeedback).mockResolvedValue(undefined);
  vi.mocked(getQuota).mockResolvedValue({ enabled: true, used: 1000, limit: 10000, remaining: 9000, reset_at: null });
  vi.mocked(getBuilderResume).mockImplementation(async (id) => id === 43 ? BUILDER_RESUME_B : BUILDER_RESUME);
  vi.mocked(saveDraft).mockResolvedValue({ ...BUILDER_RESUME, status: "draft" });
  // jsdom 没有 scrollIntoView / scrollTo，QAPage 的滚动逻辑会调用它们
  Element.prototype.scrollIntoView = vi.fn();
  Element.prototype.scrollTo = vi.fn();
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

/**
 * 断言 getHistory 以 resumeId=42 + 分页参数被调用。
 * v2 引入对话会话后 getHistory 第 5 个参数是 conversationId（异步时序不确定），
 * 只校验前 4 个参数（resumeId, limit, offset, keyword）。
 */
function expectGetHistory(callIndex = 0) {
  expect(getHistory.mock.calls.length).toBeGreaterThan(0);
  expect(getHistory.mock.calls.some((c) => c[0] === 42 && c[1] === 20 && c[2] === 0)).toBe(true);
}

describe("QAPage 基本交互 (Task 4)", () => {
  it("初次加载自动选中简历并调用 getHistory", async () => {
    renderPage();
    await waitFor(() => {
      expectGetHistory();
    });
  });

  it("加载历史后显示问答消息", async () => {
    vi.mocked(getHistory).mockResolvedValue({
      items: [
        {
          id: 1,
          question: "什么是RAG",
          answer: "检索增强生成",
          created_at: "2026-07-19",
        },
      ],
      total: 1,
    });
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("什么是RAG")).toBeInTheDocument();
    });
    expect(screen.getByText("检索增强生成")).toBeInTheDocument();
  });

  it("空历史显示引导空状态", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/从简历打磨到面试准备/)).toBeInTheDocument();
    });
  });

  it("点击清除历史按钮弹出 ConfirmDialog 显示条数", async () => {
    vi.mocked(getHistory).mockResolvedValue({
      items: [
        {
          id: 1,
          question: "Q1",
          answer: "A1",
          created_at: "2026-07-19",
        },
      ],
      total: 1,
    });
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Q1")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText("清除历史"));
    expect(screen.getByText("清空问答历史？")).toBeInTheDocument();
    expect(screen.getByText(/共 1 条/)).toBeInTheDocument();
  });

  it("ConfirmDialog 确认后调用 clearHistory 并清空 chat", async () => {
    vi.mocked(getHistory).mockResolvedValue({
      items: [
        {
          id: 1,
          question: "Q1",
          answer: "A1",
          created_at: "2026-07-19",
        },
      ],
      total: 1,
    });
    vi.mocked(clearHistory).mockResolvedValue({ deleted_count: 1 });
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Q1")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText("清除历史"));
    fireEvent.click(screen.getByRole("button", { name: "清空" }));

    await waitFor(() => {
      expect(clearHistory.mock.calls.some((c) => c[0] === 42)).toBe(true);
    });
    await waitFor(() => {
      expect(screen.queryByText("Q1")).toBeNull();
    });
  });

  it("ConfirmDialog 取消不调用 clearHistory", async () => {
    vi.mocked(getHistory).mockResolvedValue({
      items: [
        {
          id: 1,
          question: "Q1",
          answer: "A1",
          created_at: "2026-07-19",
        },
      ],
      total: 1,
    });
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Q1")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText("清除历史"));
    fireEvent.click(screen.getByRole("button", { name: "取消" }));

    expect(clearHistory).not.toHaveBeenCalled();
    expect(screen.getByText("Q1")).toBeInTheDocument();
  });

  it("点击单条删除按钮调用 deleteQa 并从列表移除", async () => {
    vi.mocked(getHistory).mockResolvedValue({
      items: [
        {
          id: 10,
          question: "Q10",
          answer: "A10",
          created_at: "2026-07-19",
        },
      ],
      total: 1,
    });
    vi.mocked(deleteQa).mockResolvedValue(undefined);
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Q10")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByLabelText("删除该问答"));

    await waitFor(() => {
      expect(deleteQa).toHaveBeenCalledWith(10);
    });
    await waitFor(() => {
      expect(screen.queryByText("Q10")).toBeNull();
    });
  });

  it("getHistory 失败显示错误提示", async () => {
    vi.mocked(getHistory).mockRejectedValue(new Error("加载失败"));
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("加载失败")).toBeInTheDocument();
    });
  });

  it("chat 为空时清除历史按钮禁用", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/从简历打磨到面试准备/)).toBeInTheDocument();
    });

    const clearBtn = screen.getByText("清除历史").closest("button");
    expect(clearBtn?.disabled).toBe(true);
  });
});

describe("QAPage 草稿 dirty 防线", () => {
  async function openModuleEditor() {
    const previewButton = await screen.findByTitle("打开简历预览");
    fireEvent.click(previewButton);
    await screen.findByRole("button", { name: "编辑基本信息" });
    fireEvent.click(screen.getByRole("button", { name: "编辑基本信息" }));
    await screen.findByRole("button", { name: "修改模块" });
  }

  it("加载 ready 简历不会自动保存草稿", async () => {
    renderPage();
    await waitFor(() => expect(getBuilderResume).toHaveBeenCalledWith(42));

    vi.useFakeTimers();
    await act(async () => { await vi.advanceTimersByTimeAsync(5000); });

    expect(saveDraft).not.toHaveBeenCalled();
    vi.useRealTimers();
  });

  it("用户直接编辑后才触发自动保存", async () => {
    renderPage();
    await openModuleEditor();
    vi.mocked(saveDraft).mockClear();

    vi.useFakeTimers();
    fireEvent.click(screen.getByRole("button", { name: "修改模块" }));
    await act(async () => { await vi.advanceTimersByTimeAsync(5000); });

    expect(saveDraft).toHaveBeenCalledTimes(1);
    expect(saveDraft).toHaveBeenCalledWith(42, expect.objectContaining({
      modules: [expect.objectContaining({ module_type: "basic_info", content: { name: "Changed" } })],
    }));
    vi.useRealTimers();
  });

  it("自动保存失败保留 dirty，允许用户重试", async () => {
    renderPage();
    await openModuleEditor();
    vi.mocked(saveDraft)
      .mockClear()
      .mockRejectedValueOnce(new Error("network"))
      .mockResolvedValue({ ...BUILDER_RESUME, status: "draft" });

    vi.useFakeTimers();
    fireEvent.click(screen.getByRole("button", { name: "修改模块" }));
    await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
    expect(saveDraft).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: /保存草稿/ }));
    await act(async () => { await Promise.resolve(); });
    expect(saveDraft).toHaveBeenCalledTimes(2);
    vi.useRealTimers();
  });

  it("refresh 响应晚到时不覆盖期间的用户编辑", async () => {
    renderPage();
    await openModuleEditor();

    let resolveRefresh!: (value: typeof BUILDER_RESUME) => void;
    const refreshPromise = new Promise<typeof BUILDER_RESUME>((resolve) => { resolveRefresh = resolve; });
    vi.mocked(getBuilderResume).mockImplementationOnce(() => refreshPromise);
    vi.useFakeTimers();
    window.dispatchEvent(new Event("resume:modules-refresh"));
    await act(async () => { await vi.advanceTimersByTimeAsync(500); });

    fireEvent.click(screen.getByRole("button", { name: "修改模块" }));
    await act(async () => { resolveRefresh(BUILDER_RESUME); await Promise.resolve(); });
    fireEvent.click(screen.getByRole("button", { name: /保存草稿/ }));
    await act(async () => { await Promise.resolve(); });

    expect(saveDraft).toHaveBeenLastCalledWith(42, expect.objectContaining({
      modules: [expect.objectContaining({ content: { name: "Changed" } })],
    }));
    vi.useRealTimers();
  });

  it("切换简历后旧手动保存失败不污染新简历 UI", async () => {
    renderPage();
    await openModuleEditor();

    let rejectSave!: (reason?: unknown) => void;
    const pendingSave = new Promise<never>((_resolve, reject) => { rejectSave = reject; });
    vi.mocked(saveDraft).mockImplementationOnce(() => pendingSave);
    fireEvent.click(screen.getByRole("button", { name: "修改模块" }));
    fireEvent.click(screen.getByRole("button", { name: /保存草稿/ }));
    await waitFor(() => expect(saveDraft).toHaveBeenCalledWith(42, expect.anything()));

    fireEvent.change(screen.getByRole("combobox", { name: "切换简历" }), { target: { value: "43" } });
    await waitFor(() => expect(getBuilderResume).toHaveBeenCalledWith(43));
    await act(async () => { rejectSave(new Error("A 保存失败")); await Promise.resolve(); });

    expect(screen.queryByText("A 保存失败")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /保存草稿/ })).not.toBeDisabled();
  });
});

describe("QAPage 搜索防抖 (Task 4)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("搜索框输入 300ms 后触发带 keyword 的 getHistory", async () => {
    vi.mocked(getHistory).mockResolvedValue({ items: [], total: 0 });
    renderPage();
    // 让初次加载 + 初次防抖 setTimeout 都走完
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });
    expectGetHistory();
    getHistory.mockClear();

    const searchInput = screen.getByPlaceholderText("搜索问答");
    fireEvent.change(searchInput, { target: { value: "Python" } });

    // 防抖中，还没触发
    expect(getHistory).not.toHaveBeenCalled();

    // 推进 300ms 触发防抖
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });

    expect(getHistory.mock.calls.some((c) => c[0] === 42 && c[1] === 20 && c[2] === 0 && c[3] === "Python")).toBe(true);
  });

  it("搜索框清除按钮清空 keyword 并重新加载", async () => {
    vi.mocked(getHistory).mockResolvedValue({ items: [], total: 0 });
    renderPage();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });
    getHistory.mockClear();

    const searchInput = screen.getByPlaceholderText("搜索问答");
    fireEvent.change(searchInput, { target: { value: "Python" } });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });
    expect(getHistory.mock.calls.some((c) => c[3] === "Python")).toBe(true);
    getHistory.mockClear();

    const clearBtn = screen.getByLabelText("清除搜索");
    fireEvent.click(clearBtn);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });
    expect(getHistory.mock.calls.some((c) => c[0] === 42 && c[3] === undefined)).toBe(true);
  });

  it("搜索结果为空时显示没有匹配的问答", async () => {
    vi.mocked(getHistory).mockResolvedValue({ items: [], total: 0 });
    renderPage();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });

    const searchInput = screen.getByPlaceholderText("搜索问答");
    fireEvent.change(searchInput, { target: { value: "NotExist" } });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });

    expect(screen.getByText("没有匹配的问答")).toBeInTheDocument();
  });
});

describe("QAPage AI 能力入口触发（回归：location.state 死循环）", () => {
  it("携带 question 进入只发送一次，回答完成后 asking 复位不重发", async () => {
    // 模拟后端完整问答周期：收到 agent_done → onDone 结束流（asking 复位 false）。
    // 用 setTimeout 延迟触发，模拟真实 LLM 生成耗时（毫秒级），
    // 确保对话加载 / getHistory 先完成，避免 loadHistory 清掉刚完成的消息。
    vi.mocked(askAgentStream).mockImplementation(
      (_resumeId, _q, onEvent, _onError, onDone) => {
        setTimeout(() => {
          onEvent({
            type: "agent_done",
            qa_id: 1,
            answer: "诊断完成",
            process_trace: { rounds: 1, tool_sequence: [], duration_ms: 1 },
          });
          onDone?.();
        }, 50);
        return () => {};
      },
    );

    render(
      <ToastProvider>
        <AppChatProvider>
          {/* 模拟 AI 能力页 / FloatingAIPanel 的 navigate("/qa", { state: { question } }) */}
          <MemoryRouter
            initialEntries={[{ pathname: "/qa", state: { question: "帮我诊断这份简历" } }]}
          >
            <Routes>
              <Route path="/qa" element={<QAPage />} />
            </Routes>
          </MemoryRouter>
        </AppChatProvider>
      </ToastProvider>,
    );

    // 简历 id=42 就绪后应自动发送一次该问题
    await waitFor(() => {
      expect(askAgentStream).toHaveBeenCalledTimes(1);
    });
    expect(askAgentStream.mock.calls[0][0]).toBe(42);
    expect(askAgentStream.mock.calls[0][1]).toBe("帮我诊断这份简历");

    // 等待问答周期结束（agent_done → asking=false）后，不得重复发送（死循环回归点）
    await waitFor(() => {
      expect(screen.getByText("诊断完成")).toBeInTheDocument();
    });
    expect(askAgentStream).toHaveBeenCalledTimes(1);
  });

  it("进入时历史加载晚到，新问题也排在历史之后（底部）而非顶部", async () => {
    // 历史含 1 条旧消息；askAgentStream 保持流式（不触发 agent_done，asking 一直为 true），
    // 使 loadHistory 的 setChat 在 sendQuestion 追加消息之后执行——复现"消息插到顶部"的竞态
    vi.mocked(getHistory).mockResolvedValue({
      items: [
        { id: 1, question: "历史问题", answer: "历史答案", created_at: "2026-07-01" },
      ],
      total: 1,
    });
    vi.mocked(askAgentStream).mockImplementation(() => () => {});

    const { container } = render(
      <ToastProvider>
        <AppChatProvider>
          <MemoryRouter
            initialEntries={[{ pathname: "/qa", state: { question: "帮我诊断这份简历" } }]}
          >
            <Routes>
              <Route path="/qa" element={<QAPage />} />
            </Routes>
          </MemoryRouter>
        </AppChatProvider>
      </ToastProvider>,
    );

    await waitFor(() => {
      expect(screen.getByText("历史问题")).toBeInTheDocument();
      expect(screen.getByText("帮我诊断这份简历")).toBeInTheDocument();
    });

    // 新问题必须排在历史消息之后（底部），而非插到顶部
    const text = container.textContent ?? "";
    expect(text.indexOf("历史问题")).toBeLessThan(text.indexOf("帮我诊断这份简历"));
  });
});
