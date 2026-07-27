import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, fireEvent, screen, waitFor } from "@testing-library/react";
import ResumeViewer from "./ResumeViewer";

vi.mock("../api/resumes", () => ({
  getResume: vi.fn(),
}));

import { getResume } from "../api/resumes";

const mockResume = {
  id: 1,
  filename: "张三_后端工程师.pdf",
  parsed_text: "张三\nPython后端工程师\n3年FastAPI开发经验\n熟悉Docker和CI/CD",
  chunk_count: 5,
  status: "ready",
  status_message: "",
  created_at: "2026-07-22T10:00:00Z",
};

describe("ResumeViewer", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("open=false 时不渲染", () => {
    render(
      <ResumeViewer
        resumeId={1}
        resumeFilename="test.pdf"
        open={false}
        onClose={() => {}}
      />
    );
    expect(screen.queryByText("简历预览")).toBeNull();
  });

  it("open=true 时加载并显示简历原文", async () => {
    vi.mocked(getResume).mockResolvedValueOnce(mockResume);
    render(
      <ResumeViewer
        resumeId={1}
        resumeFilename="张三_后端工程师.pdf"
        open={true}
        onClose={() => {}}
      />
    );
    expect(getResume).toHaveBeenCalledWith(1);
    await waitFor(() => {
      expect(screen.getByText(/Python后端工程师/)).toBeInTheDocument();
      expect(screen.getByText(/3年FastAPI开发经验/)).toBeInTheDocument();
    });
  });

  it("加载中显示骨架屏", () => {
    vi.mocked(getResume).mockReturnValueOnce(new Promise(() => {}));
    render(
      <ResumeViewer
        resumeId={1}
        resumeFilename="test.pdf"
        open={true}
        onClose={() => {}}
      />
    );
    expect(screen.getByText("简历预览")).toBeInTheDocument();
    expect(document.querySelector(".animate-skeleton")).toBeTruthy();
  });

  it("加载失败显示错误信息和重试按钮", async () => {
    vi.mocked(getResume).mockRejectedValueOnce(new Error("网络错误"));
    render(
      <ResumeViewer
        resumeId={1}
        resumeFilename="test.pdf"
        open={true}
        onClose={() => {}}
      />
    );
    await waitFor(() => {
      expect(screen.getByText("网络错误")).toBeInTheDocument();
      expect(screen.getByText("重试")).toBeInTheDocument();
    });
  });

  it("点击关闭按钮调用 onClose", async () => {
    vi.mocked(getResume).mockResolvedValueOnce(mockResume);
    const onClose = vi.fn();
    render(
      <ResumeViewer
        resumeId={1}
        resumeFilename="test.pdf"
        open={true}
        onClose={onClose}
      />
    );
    await waitFor(() => {
      expect(screen.getByText(/Python后端工程师/)).toBeInTheDocument();
    });
    const closeBtn = screen.getByLabelText("关闭");
    fireEvent.click(closeBtn);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("点击遮罩层关闭弹窗", async () => {
    vi.mocked(getResume).mockResolvedValueOnce(mockResume);
    const onClose = vi.fn();
    render(
      <ResumeViewer
        resumeId={1}
        resumeFilename="test.pdf"
        open={true}
        onClose={onClose}
      />
    );
    await waitFor(() => {
      expect(screen.getByText(/Python后端工程师/)).toBeInTheDocument();
    });
    const dialog = document.querySelector("dialog");
    expect(dialog).not.toBeNull();
    dialog!.dispatchEvent(new Event("close"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("按 Esc 关闭弹窗", async () => {
    vi.mocked(getResume).mockResolvedValueOnce(mockResume);
    const onClose = vi.fn();
    render(
      <ResumeViewer
        resumeId={1}
        resumeFilename="test.pdf"
        open={true}
        onClose={onClose}
      />
    );
    await waitFor(() => {
      expect(screen.getByText(/Python后端工程师/)).toBeInTheDocument();
    });
    const dialog = document.querySelector("dialog");
    expect(dialog).not.toBeNull();
    dialog!.dispatchEvent(new Event("cancel", { cancelable: true }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  // ── Task 2.7: 空 parsed_text 按 status 显示不同文案 ──

  it("Task 2.7: processing 状态显示「正在解析中」+ 刷新按钮", async () => {
    vi.mocked(getResume).mockResolvedValueOnce({
      ...mockResume,
      parsed_text: "",
      status: "processing",
    });
    render(
      <ResumeViewer
        resumeId={1}
        resumeFilename="test.pdf"
        open={true}
        onClose={() => {}}
      />
    );
    await waitFor(() => {
      expect(screen.getByText(/正在解析中/)).toBeInTheDocument();
    });
    // processing 提供刷新按钮
    const refreshBtn = screen.getByRole("button", { name: /刷新/ });
    expect(refreshBtn).toBeInTheDocument();
  });

  it("Task 2.7: 点击刷新按钮重新调用 getResume", async () => {
    vi.mocked(getResume).mockResolvedValueOnce({
      ...mockResume,
      parsed_text: "",
      status: "processing",
    });
    render(
      <ResumeViewer
        resumeId={1}
        resumeFilename="test.pdf"
        open={true}
        onClose={() => {}}
      />
    );
    await waitFor(() => {
      expect(screen.getByText(/正在解析中/)).toBeInTheDocument();
    });

    vi.mocked(getResume).mockResolvedValueOnce(mockResume);
    fireEvent.click(screen.getByRole("button", { name: /刷新/ }));

    await waitFor(() => {
      expect(screen.getByText(/Python后端工程师/)).toBeInTheDocument();
    });
    expect(getResume).toHaveBeenCalledTimes(2);
  });

  it("Task 2.7: failed 状态显示失败原因（status_message）+ 不显示「可能还在解析」", async () => {
    vi.mocked(getResume).mockResolvedValueOnce({
      ...mockResume,
      parsed_text: "",
      status: "failed",
      status_message: "文件格式不支持",
    });
    render(
      <ResumeViewer
        resumeId={1}
        resumeFilename="test.pdf"
        open={true}
        onClose={() => {}}
      />
    );
    await waitFor(() => {
      expect(screen.getByText(/文件格式不支持/)).toBeInTheDocument();
    });
    // 不应显示误导性的「可能还在解析中」
    expect(screen.queryByText(/可能还在解析/)).toBeNull();
  });

  it("Task 2.7: ready 但空 parsed_text 显示「未提取到文本内容」", async () => {
    vi.mocked(getResume).mockResolvedValueOnce({
      ...mockResume,
      parsed_text: "",
      status: "ready",
    });
    render(
      <ResumeViewer
        resumeId={1}
        resumeFilename="test.pdf"
        open={true}
        onClose={() => {}}
      />
    );
    await waitFor(() => {
      expect(screen.getByText(/未提取到文本内容/)).toBeInTheDocument();
    });
    // 不应显示误导性的「可能还在解析中」
    expect(screen.queryByText(/可能还在解析/)).toBeNull();
  });

  it("重试按钮重新加载数据", async () => {
    vi.mocked(getResume).mockRejectedValueOnce(new Error("失败"));
    render(
      <ResumeViewer
        resumeId={1}
        resumeFilename="test.pdf"
        open={true}
        onClose={() => {}}
      />
    );
    await waitFor(() => {
      expect(screen.getByText("重试")).toBeInTheDocument();
    });

    vi.mocked(getResume).mockResolvedValueOnce(mockResume);
    fireEvent.click(screen.getByText("重试"));
    await waitFor(() => {
      expect(screen.getByText(/Python后端工程师/)).toBeInTheDocument();
    });
    expect(getResume).toHaveBeenCalledTimes(2);
  });

  it("标题栏显示文件名", async () => {
    vi.mocked(getResume).mockResolvedValueOnce(mockResume);
    render(
      <ResumeViewer
        resumeId={1}
        resumeFilename="张三_后端工程师.pdf"
        open={true}
        onClose={() => {}}
      />
    );
    await waitFor(() => {
      expect(screen.getByText("张三_后端工程师.pdf")).toBeInTheDocument();
    });
  });
});
