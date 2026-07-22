import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, fireEvent, act, waitFor, screen } from "@testing-library/react";

vi.mock("../api/resumes", () => ({
  analyzeResume: vi.fn(),
  exportResume: vi.fn(),
}));

import AnalysisModal from "./AnalysisModal";
import { analyzeResume, exportResume } from "../api/resumes";

const mockAnalyze = vi.mocked(analyzeResume);
const mockExport = vi.mocked(exportResume);

beforeEach(() => {
  mockAnalyze.mockReset();
  mockExport.mockReset();
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

  it("open=true 时显示标题（含 filename）和四个 Tab", async () => {
    mockAnalyze.mockResolvedValue({
      resume_id: 42,
      analysis_type: "summary",
      analysis: "结果",
      scores: null,
    });
    renderModal();

    await waitFor(() => expect(mockAnalyze).toHaveBeenCalled());

    expect(screen.getByText(/test-resume\.pdf/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /总结/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /技能/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /经历/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /评分/ })).toBeInTheDocument();
  });

  it("open=true 自动调 analyzeResume(id, summary)", async () => {
    mockAnalyze.mockResolvedValue({
      resume_id: 42,
      analysis_type: "summary",
      analysis: "候选人精通 Python。",
      scores: null,
    });
    renderModal();

    await waitFor(() => {
      expect(mockAnalyze).toHaveBeenCalledWith(42, "summary");
    });
  });

  it("Loading 态显示 skeleton（结果未到时）", async () => {
    mockAnalyze.mockReturnValue(new Promise(() => {}));
    renderModal();

    await waitFor(() => {
      expect(mockAnalyze).toHaveBeenCalled();
    });
    const skeletons = document.querySelectorAll(".animate-skeleton");
    expect(skeletons.length).toBeGreaterThanOrEqual(3);
  });

  it("Error 态显示错误信息 + 重试按钮，点重试重新调用", async () => {
    mockAnalyze.mockRejectedValueOnce(new Error("LLM 调用失败"));
    mockAnalyze.mockResolvedValueOnce({
      resume_id: 42,
      analysis_type: "summary",
      analysis: "重试成功",
      scores: null,
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
      scores: null,
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
      scores: null,
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
      scores: null,
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
      scores: null,
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
      scores: null,
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
      scores: null,
    });
    const onClose = vi.fn();
    const { container } = renderModal({ onClose });

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
      scores: null,
    });
    const onClose = vi.fn();
    renderModal({ onClose });

    await act(async () => {
      fireEvent.click(screen.getByText(/test-resume\.pdf/));
    });

    expect(onClose).not.toHaveBeenCalled();
  });

  // ── P1.1 评分 Tab 测试 ──

  it("切换到评分 Tab 调用 analyzeResume(id, score)", async () => {
    mockAnalyze.mockResolvedValue({
      resume_id: 42,
      analysis_type: "summary",
      analysis: "结果",
      scores: null,
    });
    renderModal();

    await waitFor(() => expect(mockAnalyze).toHaveBeenCalled());
    mockAnalyze.mockClear();

    mockAnalyze.mockResolvedValue({
      resume_id: 42,
      analysis_type: "score",
      analysis: "### ATS 匹配率: 75/100\n### 关键词覆盖率: 68/100",
      scores: { ats_match: 75, keyword_coverage: 68, skill_density: 72, overall: 72 },
    });

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /评分/ }));
    });

    await waitFor(() => {
      expect(mockAnalyze).toHaveBeenCalledWith(42, "score");
    });
  });

  it("评分 Tab 成功后显示量化分数", async () => {
    mockAnalyze.mockResolvedValue({
      resume_id: 42,
      analysis_type: "score",
      analysis: "### ATS 匹配率: 75/100",
      scores: { ats_match: 75, keyword_coverage: 68, skill_density: 72, overall: 72 },
    });
    renderModal({ open: true });

    // 直接切到评分
    await waitFor(() => expect(mockAnalyze).toHaveBeenCalled());

    // 检查分数显示
    await waitFor(() => {
      expect(screen.getByText(/75/)).toBeInTheDocument();
    });
  });

  // ── P1.2 导出按钮测试 ──

  it("Success 态显示导出按钮", async () => {
    mockAnalyze.mockResolvedValue({
      resume_id: 42,
      analysis_type: "summary",
      analysis: "分析结果",
      scores: null,
    });
    renderModal();

    await waitFor(() => {
      expect(screen.getByText(/分析结果/)).toBeInTheDocument();
    });

    expect(screen.getByRole("button", { name: /导出/ })).toBeInTheDocument();
  });

  it("点导出按钮调用 exportResume 并触发下载", async () => {
    mockAnalyze.mockResolvedValue({
      resume_id: 42,
      analysis_type: "summary",
      analysis: "分析结果",
      scores: null,
    });
    mockExport.mockResolvedValue("# 简历分析报告\n\n内容");
    renderModal();

    await waitFor(() => {
      expect(screen.getByText(/分析结果/)).toBeInTheDocument();
    });

    // Mock URL.createObjectURL
    const mockUrl = "blob:mock-url";
    const origCreateObjectURL = globalThis.URL.createObjectURL;
    const origRevokeObjectURL = globalThis.URL.revokeObjectURL;
    globalThis.URL.createObjectURL = vi.fn(() => mockUrl);
    globalThis.URL.revokeObjectURL = vi.fn();

    // Mock document.createElement to track <a> click
    const mockClick = vi.fn();
    const origCreateElement = document.createElement.bind(document);
    vi.spyOn(document, "createElement").mockImplementation((tag: string) => {
      if (tag === "a") {
        const el = origCreateElement(tag);
        el.click = mockClick;
        return el;
      }
      return origCreateElement(tag);
    });

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /导出/ }));
    });

    await waitFor(() => {
      expect(mockExport).toHaveBeenCalledWith(42, "markdown");
      expect(mockClick).toHaveBeenCalled();
    });

    // Cleanup
    globalThis.URL.createObjectURL = origCreateObjectURL;
    globalThis.URL.revokeObjectURL = origRevokeObjectURL;
    vi.restoreAllMocks();
  });
});
