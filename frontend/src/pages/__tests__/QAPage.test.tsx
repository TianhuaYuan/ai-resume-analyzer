import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, fireEvent, screen, waitFor, act } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import QAPage from "../QAPage";

vi.mock("../../api/qa", () => ({
  askQuestionStream: vi.fn(() => () => {}),
  getHistory: vi.fn(async () => ({ items: [], total: 0 })),
  clearHistory: vi.fn(async () => ({ deleted_count: 0 })),
  deleteQa: vi.fn(async () => undefined),
}));

vi.mock("../../api/resumes", () => ({
  listResumes: vi.fn(async () => ({ items: [], total: 0 })),
}));

import { getHistory, clearHistory, deleteQa } from "../../api/qa";

function renderPage(route = "/resumes/42") {
  // P2-12：测试路由与生产 App.tsx 保持一致（/resumes/:id）
  return render(
    <MemoryRouter initialEntries={[route]}>
      <Routes>
        <Route path="/resumes/:id" element={<QAPage />} />
      </Routes>
    </MemoryRouter>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  // 每个测试开始时重置默认 mock 实现，避免上个测试的 mockResolvedValue 泄漏
  vi.mocked(getHistory).mockResolvedValue({ items: [], total: 0 });
  vi.mocked(clearHistory).mockResolvedValue({ deleted_count: 0 });
  vi.mocked(deleteQa).mockResolvedValue(undefined);
  // jsdom 没有 scrollIntoView，QAPage 的 chatEndRef 会调用它
  Element.prototype.scrollIntoView = vi.fn();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("QAPage 基本交互 (Task 4)", () => {
  it("初次加载调用 getHistory(resumeId, 20, 0, undefined)", async () => {
    renderPage();
    await waitFor(() => {
      expect(getHistory).toHaveBeenCalledWith(42, 20, 0, undefined);
    });
  });

  it("加载历史后显示问答消息", async () => {
    vi.mocked(getHistory).mockResolvedValue({
      items: [
        {
          id: 1,
          question: "什么是RAG",
          answer: "检索增强生成",
          sources: [],
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

  it("空历史显示开始提问空状态", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("开始提问")).toBeInTheDocument();
    });
  });

  it("点击清除历史按钮弹出 ConfirmDialog 显示条数", async () => {
    vi.mocked(getHistory).mockResolvedValue({
      items: [
        {
          id: 1,
          question: "Q1",
          answer: "A1",
          sources: [],
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
          sources: [],
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
      expect(clearHistory).toHaveBeenCalledWith(42);
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
          sources: [],
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
          sources: [],
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
    vi.mocked(getHistory).mockResolvedValue({ items: [], total: 0 });
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("开始提问")).toBeInTheDocument();
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
    expect(getHistory).toHaveBeenCalledWith(42, 20, 0, undefined);
    getHistory.mockClear();

    const searchInput = screen.getByPlaceholderText("搜索问答");
    fireEvent.change(searchInput, { target: { value: "Python" } });

    // 防抖中，还没触发
    expect(getHistory).not.toHaveBeenCalled();

    // 推进 300ms 触发防抖
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });

    expect(getHistory).toHaveBeenCalledWith(42, 20, 0, "Python");
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
    expect(getHistory).toHaveBeenCalledWith(42, 20, 0, "Python");
    getHistory.mockClear();

    const clearBtn = screen.getByLabelText("清除搜索");
    fireEvent.click(clearBtn);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });
    expect(getHistory).toHaveBeenCalledWith(42, 20, 0, undefined);
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

// ── P2-16：来源段落截断应有展开按钮 ──

describe("SourceCard 展开/收起 (P2-16)", () => {
  const LONG_TEXT = "这是一段很长的来源文本".repeat(30); // > 220 字符

  it("长来源默认截断并显示展开按钮", async () => {
    vi.mocked(getHistory).mockResolvedValue({
      items: [
        {
          id: 1,
          question: "Q",
          answer: "A",
          sources: [LONG_TEXT],
          created_at: "2026-07-19",
        },
      ],
      total: 1,
    });
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Q")).toBeInTheDocument();
    });

    // 展开来源
    fireEvent.click(screen.getByText(/来源/));
    // 截断后应有展开按钮
    expect(screen.getByText("展开")).toBeInTheDocument();
    // 不应显示完整文本
    expect(screen.queryByText(LONG_TEXT)).toBeNull();
  });

  it("点击展开后显示完整文本，按钮变为收起", async () => {
    vi.mocked(getHistory).mockResolvedValue({
      items: [
        {
          id: 1,
          question: "Q",
          answer: "A",
          sources: [LONG_TEXT],
          created_at: "2026-07-19",
        },
      ],
      total: 1,
    });
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Q")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText(/来源/));
    fireEvent.click(screen.getByText("展开"));
    // 展开后应显示完整文本
    expect(screen.getByText(LONG_TEXT)).toBeInTheDocument();
    expect(screen.getByText("收起")).toBeInTheDocument();
  });
});
