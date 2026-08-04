import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, fireEvent, screen, waitFor, act } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import QAPage from "../QAPage";
import { AppChatProvider } from "../../context/AppChatContext";

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
const { DEFAULT_RESUME } = vi.hoisted(() => ({
  DEFAULT_RESUME: {
    id: 42,
    filename: "resume-42.pdf",
    parsed_text: "",
    chunk_count: 3,
    status: "ready",
    status_message: "",
    created_at: "",
  },
}));

vi.mock("../../api/resumes", () => ({
  listResumes: vi.fn(async () => ({ items: [DEFAULT_RESUME], total: 1 })),
  uploadResume: vi.fn(async () => ({ id: 42, filename: "resume.pdf", status: "processing" })),
}));

// QAPage 的 useEffect 会调用编辑锁生命周期 + 保存 + 创建简历（jsdom 无 fetch，必须全部 mock）
vi.mock("../../api/builder", () => ({
  getBuilderResume: vi.fn(async () => null),
  saveDraft: vi.fn(async () => ({ id: 42, version: 1 })),
  saveComplete: vi.fn(async () => ({ id: 42, version: 1 })),
  acquireEditLock: vi.fn(async () => ({ locked: false, lock_token: null })),
  renewEditLock: vi.fn(async () => ({ locked: false, lock_token: null })),
  releaseEditLock: vi.fn(async () => undefined),
  createBuilderResume: vi.fn(async () => ({ id: 43, filename: "未命名简历" })),
}));

import { getHistory, clearHistory, deleteQa, submitFeedback, getQuota } from "../../api/qa";

function renderPage(route = "/resumes/42") {
  // P2-12：测试路由与生产 App.tsx 保持一致（/resumes/:id）
  // QAPage 使用 useAppChat（与 Sidebar 共享对话状态），需包 AppChatProvider
  return render(
    <AppChatProvider>
      <MemoryRouter initialEntries={[route]}>
        <Routes>
          <Route path="/resumes/:id" element={<QAPage />} />
        </Routes>
      </MemoryRouter>
    </AppChatProvider>
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
  // jsdom 没有 scrollIntoView / scrollTo，QAPage 的滚动逻辑会调用它们
  Element.prototype.scrollIntoView = vi.fn();
  Element.prototype.scrollTo = vi.fn();
});

afterEach(() => {
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
