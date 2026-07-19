import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, fireEvent, act, waitFor, screen } from "@testing-library/react";

vi.mock("../api/resumes", () => ({
  analyzeResume: vi.fn(),
}));

import AnalysisModal from "./AnalysisModal";
import { analyzeResume } from "../api/resumes";

const mockAnalyze = vi.mocked(analyzeResume);

beforeEach(() => {
  mockAnalyze.mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
});

function renderModal(props: Partial<React.ComponentProps<typeof AnalysisModal>> = {}) {
  const defaultProps = {
    resumeId: 42,
    resumeFilename: "test-resume.pdf",
    open: true,
    onClose: vi.fn(),
  };
  return render(<AnalysisModal {...defaultProps} {...props} />);
}

describe("AnalysisModal (Task 2 前端)", () => {
  it("open=false 时不渲染", () => {
    renderModal({ open: false });
    expect(screen.queryByText(/test-resume\.pdf/)).toBeNull();
  });

  it("open=true 时显示标题（含 filename）和三个 Tab", async () => {
    mockAnalyze.mockResolvedValue({
      resume_id: 42,
      analysis_type: "summary",
      analysis: "结果",
    });
    renderModal();

    // 等待 useEffect 触发的异步加载完成，避免 act 警告
    await waitFor(() => expect(mockAnalyze).toHaveBeenCalled());

    expect(screen.getByText(/test-resume\.pdf/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /总结/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /技能/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /经历/ })).toBeInTheDocument();
  });

  it("open=true 自动调 analyzeResume(id, summary)", async () => {
    mockAnalyze.mockResolvedValue({
      resume_id: 42,
      analysis_type: "summary",
      analysis: "候选人精通 Python。",
    });
    renderModal();

    await waitFor(() => {
      expect(mockAnalyze).toHaveBeenCalledWith(42, "summary");
    });
  });

  it("Loading 态显示 skeleton（结果未到时）", async () => {
    // 用永不 resolve 的 promise 锁定 loading 态
    mockAnalyze.mockReturnValue(new Promise(() => {}));
    renderModal();

    // skeleton 容器存在
    await waitFor(() => {
      expect(mockAnalyze).toHaveBeenCalled();
    });
    // 用 animate-skeleton class 检测
    const skeletons = document.querySelectorAll(".animate-skeleton");
    expect(skeletons.length).toBeGreaterThanOrEqual(3);
  });

  it("Error 态显示错误信息 + 重试按钮，点重试重新调用", async () => {
    mockAnalyze.mockRejectedValueOnce(new Error("LLM 调用失败"));
    mockAnalyze.mockResolvedValueOnce({
      resume_id: 42,
      analysis_type: "summary",
      analysis: "重试成功",
    });
    renderModal();

    await waitFor(() => {
      expect(screen.getByText(/LLM 调用失败/)).toBeInTheDocument();
    });

    const retryBtn = screen.getByRole("button", { name: /重试/ });
    await act(async () => {
      fireEvent.click(retryBtn);
    });

    await waitFor(() => {
      expect(mockAnalyze).toHaveBeenCalledTimes(2);
      expect(screen.getByText(/重试成功/)).toBeInTheDocument();
    });
  });

  it("Success 态显示分析结果", async () => {
    mockAnalyze.mockResolvedValue({
      resume_id: 42,
      analysis_type: "summary",
      analysis: "候选人精通 Python 和 FastAPI，3 年后端经验。",
    });
    renderModal();

    await waitFor(() => {
      expect(screen.getByText(/候选人精通 Python/)).toBeInTheDocument();
    });
  });

  it("切换 Tab 触发对应类型的 analyzeResume 调用", async () => {
    mockAnalyze.mockResolvedValue({
      resume_id: 42,
      analysis_type: "summary",
      analysis: "结果",
    });
    renderModal();

    await waitFor(() => {
      expect(mockAnalyze).toHaveBeenCalledWith(42, "summary");
    });

    mockAnalyze.mockClear();
    mockAnalyze.mockResolvedValue({
      resume_id: 42,
      analysis_type: "skills",
      analysis: "Python, FastAPI",
    });

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /技能/ }));
    });

    await waitFor(() => {
      expect(mockAnalyze).toHaveBeenCalledWith(42, "skills");
    });
  });

  it("点 X 按钮调用 onClose", async () => {
    mockAnalyze.mockResolvedValue({
      resume_id: 42,
      analysis_type: "summary",
      analysis: "x",
    });
    const onClose = vi.fn();
    renderModal({ onClose });

    const closeBtn = screen.getByLabelText(/关闭/);
    await act(async () => {
      fireEvent.click(closeBtn);
    });

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("按 Esc 调用 onClose", async () => {
    mockAnalyze.mockResolvedValue({
      resume_id: 42,
      analysis_type: "summary",
      analysis: "x",
    });
    const onClose = vi.fn();
    renderModal({ onClose });

    await act(async () => {
      fireEvent.keyDown(document.body, { key: "Escape" });
    });

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("点 overlay 遮罩调用 onClose", async () => {
    mockAnalyze.mockResolvedValue({
      resume_id: 42,
      analysis_type: "summary",
      analysis: "x",
    });
    const onClose = vi.fn();
    const { container } = renderModal({ onClose });

    // overlay 是最外层 fixed inset-0 的 div
    const overlay = container.firstElementChild as HTMLElement;
    await act(async () => {
      fireEvent.click(overlay);
    });

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("点卡片本体不关闭（事件不冒泡到 overlay）", async () => {
    mockAnalyze.mockResolvedValue({
      resume_id: 42,
      analysis_type: "summary",
      analysis: "x",
    });
    const onClose = vi.fn();
    renderModal({ onClose });

    // 点标题（卡片内部元素）不应触发 onClose
    await act(async () => {
      fireEvent.click(screen.getByText(/test-resume\.pdf/));
    });

    expect(onClose).not.toHaveBeenCalled();
  });
});
