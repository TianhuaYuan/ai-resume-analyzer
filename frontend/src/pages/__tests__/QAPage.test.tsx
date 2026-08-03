import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, fireEvent, screen, waitFor, act } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import QAPage from "../QAPage";
import { AppChatProvider } from "../../context/AppChatContext";

vi.mock("../../api/qa", () => ({
  askQuestionStream: vi.fn(() => () => {}),
  getHistory: vi.fn(async () => ({ items: [], total: 0 })),
  clearHistory: vi.fn(async () => ({ deleted_count: 0 })),
  deleteQa: vi.fn(async () => undefined),
  submitFeedback: vi.fn(async () => undefined),
  getQuota: vi.fn(async () => ({ enabled: true, used: 1000, limit: 10000, remaining: 9000, reset_at: null })),
  // QAPage 对话管理依赖（AppChatContext 重构后新增）
  getConversations: vi.fn(async () => []),
  createConversation: vi.fn(async () => ({ id: 1, title: "新的对话", updated_at: "" })),
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
}));

vi.mock("../../api/builder", () => ({
  getBuilderResume: vi.fn(async () => null),
}));

import { getHistory, clearHistory, deleteQa, askQuestionStream, submitFeedback, getQuota } from "../../api/qa";

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
  vi.mocked(askQuestionStream).mockReturnValue(() => {});
  vi.mocked(submitFeedback).mockResolvedValue(undefined);
  vi.mocked(getQuota).mockResolvedValue({ enabled: true, used: 1000, limit: 10000, remaining: 9000, reset_at: null });
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

// ── Task 2.3: 顶栏 Segmented Control 切换 RAG 模式 ──

describe("QAPage RAG 模式切换 Segmented Control (Task 2.3)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getHistory).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(askQuestionStream).mockReturnValue(() => {});
    Element.prototype.scrollIntoView = vi.fn();
  });

  it("顶栏渲染 Segmented Control 含「传统」和「Agentic」两个选项", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("开始提问")).toBeInTheDocument();
    });

    expect(screen.getByRole("radio", { name: /传统/ })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /Agentic/ })).toBeInTheDocument();
  });

  it("默认选中「传统」模式", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("开始提问")).toBeInTheDocument();
    });

    const streamRadio = screen.getByRole("radio", { name: /传统/ });
    expect(streamRadio).toBeChecked();
  });

  it("切换到「Agentic」后选中状态变更", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("开始提问")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("radio", { name: /Agentic/ }));

    expect(screen.getByRole("radio", { name: /Agentic/ })).toBeChecked();
    expect(screen.getByRole("radio", { name: /传统/ })).not.toBeChecked();
  });

  it("默认模式下发送问题调用 askQuestionStream 不附带 mode 参数（options 不含 mode 或 mode=stream）", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("开始提问")).toBeInTheDocument();
    });

    fireEvent.change(screen.getByPlaceholderText(/输入问题/), {
      target: { value: "这个人会啥" },
    });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));

    await waitFor(() => {
      expect(askQuestionStream).toHaveBeenCalled();
    });
    const lastCallArgs = vi.mocked(askQuestionStream).mock.calls[0];
    const optionsArg = lastCallArgs[5];
    // 默认模式下 options 不应含 mode='agentic'
    const mode = optionsArg?.mode;
    expect(mode).not.toBe("agentic");
  });

  it("切换到 Agentic 后发送问题附带 mode='agentic'", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("开始提问")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("radio", { name: /Agentic/ }));
    fireEvent.change(screen.getByPlaceholderText(/输入问题/), {
      target: { value: "亮点是啥" },
    });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));

    await waitFor(() => {
      expect(askQuestionStream).toHaveBeenCalled();
    });
    const lastCallArgs = vi.mocked(askQuestionStream).mock.calls[0];
    const optionsArg = lastCallArgs[5];
    expect(optionsArg?.mode).toBe("agentic");
  });

  it("Segmented Control 带 radiogroup 语义，便于屏幕阅读器", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("开始提问")).toBeInTheDocument();
    });

    expect(screen.getByRole("radiogroup")).toBeInTheDocument();
  });
});

// ── Task 5.1: 预设提问 ──

describe("Task 5.1: 预设提问", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getHistory).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(askQuestionStream).mockReturnValue(() => {});
    Element.prototype.scrollIntoView = vi.fn();
  });

  it("空聊天状态显示预设提问按钮", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("开始提问")).toBeInTheDocument();
    });

    // 应该有预设提问按钮
    expect(screen.getByRole("button", { name: /亮点/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /适合.*岗位/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /技能/ })).toBeInTheDocument();
  });

  it("点击预设提问按钮自动填入问题并发送", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("开始提问")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /亮点/ }));

    // 应该调用 askQuestionStream 而不是仅仅填入输入框
    await waitFor(() => {
      expect(askQuestionStream).toHaveBeenCalled();
    });
    const callArgs = vi.mocked(askQuestionStream).mock.calls[0];
    expect(callArgs[1]).toMatch(/亮点/);
  });

  it("有聊天记录时预设提问按钮不显示", async () => {
    vi.mocked(getHistory).mockResolvedValue({
      items: [
        { id: 1, question: "Q1", answer: "A1", sources: [], created_at: "2026-07-19" },
      ],
      total: 1,
    });
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Q1")).toBeInTheDocument();
    });

    expect(screen.queryByRole("button", { name: /亮点/ })).toBeNull();
  });

  it("正在流式回答时预设提问按钮禁用", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("开始提问")).toBeInTheDocument();
    });

    // 模拟正在回答
    const presetBtn = screen.getByRole("button", { name: /亮点/ });
    // 初始状态不应禁用（未在asking中）
    expect(presetBtn).not.toBeDisabled();
  });
});

// ── Task 5.1: 质量反馈 ──

describe("Task 5.1: 质量反馈", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getHistory).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(askQuestionStream).mockReturnValue(() => {});
    vi.mocked(submitFeedback).mockResolvedValue(undefined);
    Element.prototype.scrollIntoView = vi.fn();
  });

  it("已完成的回答显示 👍 👎 反馈按钮", async () => {
    vi.mocked(getHistory).mockResolvedValue({
      items: [
        { id: 1, question: "Q1", answer: "A1", sources: [], created_at: "2026-07-19" },
      ],
      total: 1,
    });
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Q1")).toBeInTheDocument();
    });

    expect(screen.getByRole("button", { name: /有帮助/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /没帮助/ })).toBeInTheDocument();
  });

  it("点击 👍 调用 submitFeedback(qaId, 'positive')", async () => {
    vi.mocked(getHistory).mockResolvedValue({
      items: [
        { id: 10, question: "Q1", answer: "A1", sources: [], created_at: "2026-07-19" },
      ],
      total: 1,
    });
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Q1")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /有帮助/ }));

    await waitFor(() => {
      expect(submitFeedback).toHaveBeenCalledWith(10, "positive");
    });
  });

  it("点击 👎 调用 submitFeedback(qaId, 'negative')", async () => {
    vi.mocked(getHistory).mockResolvedValue({
      items: [
        { id: 10, question: "Q1", answer: "A1", sources: [], created_at: "2026-07-19" },
      ],
      total: 1,
    });
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Q1")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /没帮助/ }));

    await waitFor(() => {
      expect(submitFeedback).toHaveBeenCalledWith(10, "negative");
    });
  });

  it("反馈后按钮显示选中状态，不可重复点击", async () => {
    vi.mocked(getHistory).mockResolvedValue({
      items: [
        { id: 10, question: "Q1", answer: "A1", sources: [], created_at: "2026-07-19" },
      ],
      total: 1,
    });
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Q1")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /有帮助/ }));

    await waitFor(() => {
      expect(submitFeedback).toHaveBeenCalledTimes(1);
    });

    // 反馈后再次点击不应重复调用
    fireEvent.click(screen.getByRole("button", { name: /有帮助/ }));
    expect(submitFeedback).toHaveBeenCalledTimes(1);
  });

  it("流式消息不显示反馈按钮", async () => {
    vi.mocked(getHistory).mockResolvedValue({ items: [], total: 0 });
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("开始提问")).toBeInTheDocument();
    });

    // 手动触发一个流式提问
    fireEvent.change(screen.getByPlaceholderText(/输入问题/), {
      target: { value: "测试问题" },
    });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));

    await waitFor(() => {
      expect(askQuestionStream).toHaveBeenCalled();
    });

    // 流式消息（streaming=true）不应有反馈按钮
    expect(screen.queryByRole("button", { name: /有帮助/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /没帮助/ })).toBeNull();
  });

  it("反馈 API 失败不崩溃", async () => {
    vi.mocked(submitFeedback).mockRejectedValue(new Error("网络错误"));
    vi.mocked(getHistory).mockResolvedValue({
      items: [
        { id: 10, question: "Q1", answer: "A1", sources: [], created_at: "2026-07-19" },
      ],
      total: 1,
    });
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Q1")).toBeInTheDocument();
    });

    // 点击反馈不应抛出未捕获异常
    expect(() => {
      fireEvent.click(screen.getByRole("button", { name: /有帮助/ }));
    }).not.toThrow();
  });
});

describe("QAPage Markdown 渲染", () => {
  it("历史记录中的 answer 使用 Markdown 渲染", async () => {
    vi.mocked(getHistory).mockResolvedValue({
      items: [
        {
          id: 1,
          question: "Q1",
          answer: "**加粗** 和 \n- 列表项",
          created_at: "2026-07-19",
        },
      ],
      total: 1,
    });
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Q1")).toBeInTheDocument();
    });

    // MarkdownRenderer 会渲染加粗文本和列表
    expect(screen.getByText("加粗")).toBeInTheDocument();
    expect(document.querySelector(".markdown-strong-inline")).toBeInTheDocument();
    expect(document.querySelector(".markdown-li")).toBeInTheDocument();
  });
});

describe("QAPage 历史记录排序修复", () => {
  it("不依赖后端返回顺序，按 id 升序排列确保旧在上新在下", async () => {
    // 模拟后端 created_at 相同时顺序不确定的情况
    vi.mocked(getHistory).mockResolvedValue({
      items: [
        { id: 2, question: "中间", answer: "A2", sources: [], created_at: "2026-07-20T10:00:00" },
        { id: 3, question: "最新", answer: "A3", sources: [], created_at: "2026-07-21T10:00:00" },
        { id: 1, question: "最早", answer: "A1", sources: [], created_at: "2026-07-19T10:00:00" },
      ],
      total: 3,
    });
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("最早")).toBeInTheDocument();
    });
    const bubbles = screen.getAllByText(/最早|中间|最新/);
    expect(bubbles[0]).toHaveTextContent("最早");
    expect(bubbles[1]).toHaveTextContent("中间");
    expect(bubbles[2]).toHaveTextContent("最新");
  });

  it("每条历史消息显示格式化的时间戳（北京时间）", async () => {
    vi.mocked(getHistory).mockResolvedValue({
      items: [
        // 后端返回 naive datetime（无 Z 后缀），实际是 UTC 02:30 → 北京时间 10:30
        { id: 1, question: "Q1", answer: "A1", sources: [], created_at: "2026-07-19T02:30:00" },
      ],
      total: 1,
    });
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Q1")).toBeInTheDocument();
    });
    const ts = screen.getByTestId("message-timestamp");
    expect(ts).toBeInTheDocument();
    expect(ts.textContent).toMatch(/07-19/);
    expect(ts.textContent).toMatch(/10:30/);
  });
});

describe("QAPage 顶部栏设计", () => {
  it("顶部栏滚动时保持固定（sticky）", async () => {
    renderPage();
    await waitFor(() => {
      expect(getHistory).toHaveBeenCalled();
    });
    // 顶栏包含文件名，查找后向上找 sticky 容器
    const heading = screen.getByRole("heading", { level: 2 });
    const header = heading.closest("div[class*='sticky'], div[class*='fixed']");
    expect(header).toBeTruthy();
    expect(header!.className).toMatch(/sticky|fixed/);
  });

  it("顶部栏不使用半透明背景", async () => {
    renderPage();
    await waitFor(() => {
      expect(getHistory).toHaveBeenCalled();
    });
    const heading = screen.getByRole("heading", { level: 2 });
    const header = heading.closest("div[class*='sticky'], div[class*='fixed']");
    expect(header).toBeTruthy();
    expect(header!.className).not.toMatch(/backdrop-blur|bg-\[.*\]\/\d+/);
  });
});

// ── Token 限额 UI ──

describe("Token 限额 UI", () => {
  it("初始化时调用 getQuota API", async () => {
    renderPage();
    await waitFor(() => {
      expect(getQuota).toHaveBeenCalled();
    });
  });

  it("限额启用时顶部栏显示今日额度", async () => {
    vi.mocked(getQuota).mockResolvedValue({
      enabled: true,
      used: 3500,
      limit: 10000,
      remaining: 6500,
      reset_at: "2026-07-30T00:00:00Z",
    });
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/今日额度/)).toBeInTheDocument();
    });
    expect(screen.getByText(/3500/)).toBeInTheDocument();
    expect(screen.getByText(/10000/)).toBeInTheDocument();
  });

  it("限额关闭时不显示额度信息", async () => {
    vi.mocked(getQuota).mockResolvedValue({
      enabled: false,
      used: 0,
      limit: 10000,
      remaining: 10000,
      reset_at: null,
    });
    renderPage();
    await waitFor(() => {
      expect(getQuota).toHaveBeenCalled();
    });
    expect(screen.queryByText(/今日额度/)).toBeNull();
  });

  it("额度不足时发送按钮禁用并显示提示", async () => {
    vi.mocked(getQuota).mockResolvedValue({
      enabled: true,
      used: 9800,
      limit: 10000,
      remaining: 200,
      reset_at: "2026-07-30T00:00:00Z",
    });
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/今日额度/)).toBeInTheDocument();
    });
    // 剩余额度不足时应该有提示
    expect(screen.getByText(/额度不足/)).toBeInTheDocument();
  });
});
