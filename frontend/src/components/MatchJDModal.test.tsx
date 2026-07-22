import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, fireEvent, screen, waitFor } from "@testing-library/react";
import MatchJDModal from "./MatchJDModal";

vi.mock("../api/resumes", () => ({
  matchJD: vi.fn(),
}));

import { matchJD } from "../api/resumes";

const mockResult = {
  resume_id: 1,
  analysis:
    "## 匹配分数\n85/100\n\n## 匹配点\n1. Python 开发经验匹配\n2. FastAPI 框架经验匹配\n\n## 差距分析\n1. 缺少 Kubernetes 经验\n\n## 改进建议\n建议补充容器编排经验。",
};

describe("MatchJDModal", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("open=false 时不渲染", () => {
    render(
      <MatchJDModal
        resumeId={1}
        resumeFilename="test.pdf"
        open={false}
        onClose={() => {}}
      />
    );
    expect(screen.queryByText("JD 匹配分析")).toBeNull();
  });

  it("open=true 时显示标题和 JD 输入框", () => {
    render(
      <MatchJDModal
        resumeId={1}
        resumeFilename="test.pdf"
        open={true}
        onClose={() => {}}
      />
    );
    expect(screen.getByText("JD 匹配分析")).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/粘贴职位描述/)).toBeInTheDocument();
  });

  it("JD 为空时点击分析按钮不发送请求", () => {
    render(
      <MatchJDModal
        resumeId={1}
        resumeFilename="test.pdf"
        open={true}
        onClose={() => {}}
      />
    );
    const btn = screen.getByText("开始匹配");
    fireEvent.click(btn);
    expect(matchJD).not.toHaveBeenCalled();
  });

  it("输入 JD 后点击分析按钮发送请求并显示结果", async () => {
    vi.mocked(matchJD).mockResolvedValueOnce(mockResult);
    render(
      <MatchJDModal
        resumeId={1}
        resumeFilename="test.pdf"
        open={true}
        onClose={() => {}}
      />
    );
    const textarea = screen.getByPlaceholderText(/粘贴职位描述/);
    fireEvent.change(textarea, { target: { value: "Python 后端工程师，3年经验" } });

    const btn = screen.getByText("开始匹配");
    fireEvent.click(btn);

    expect(matchJD).toHaveBeenCalledWith(1, "Python 后端工程师，3年经验");

    await waitFor(() => {
      expect(screen.getByText(/匹配分数/)).toBeInTheDocument();
      expect(screen.getByText(/85\/100/)).toBeInTheDocument();
    });
  });

  it("加载中显示加载状态", () => {
    vi.mocked(matchJD).mockReturnValueOnce(new Promise(() => {}));
    render(
      <MatchJDModal
        resumeId={1}
        resumeFilename="test.pdf"
        open={true}
        onClose={() => {}}
      />
    );
    const textarea = screen.getByPlaceholderText(/粘贴职位描述/);
    fireEvent.change(textarea, { target: { value: "Python 工程师" } });
    fireEvent.click(screen.getByText("开始匹配"));
    expect(screen.getByText("分析中...")).toBeInTheDocument();
  });

  it("请求失败显示错误信息和重试按钮", async () => {
    vi.mocked(matchJD).mockRejectedValueOnce(new Error("网络错误"));
    render(
      <MatchJDModal
        resumeId={1}
        resumeFilename="test.pdf"
        open={true}
        onClose={() => {}}
      />
    );
    const textarea = screen.getByPlaceholderText(/粘贴职位描述/);
    fireEvent.change(textarea, { target: { value: "Python 工程师" } });
    fireEvent.click(screen.getByText("开始匹配"));

    await waitFor(() => {
      expect(screen.getByText("网络错误")).toBeInTheDocument();
      expect(screen.getByText("重试")).toBeInTheDocument();
    });
  });

  it("点击关闭按钮调用 onClose", () => {
    const onClose = vi.fn();
    render(
      <MatchJDModal
        resumeId={1}
        resumeFilename="test.pdf"
        open={true}
        onClose={onClose}
      />
    );
    fireEvent.click(screen.getByLabelText("关闭"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("点击遮罩层关闭弹窗", () => {
    const onClose = vi.fn();
    const { container } = render(
      <MatchJDModal
        resumeId={1}
        resumeFilename="test.pdf"
        open={true}
        onClose={onClose}
      />
    );
    const overlay = container.querySelector(".fixed.inset-0");
    fireEvent.click(overlay!);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("按 Esc 关闭弹窗", () => {
    const onClose = vi.fn();
    render(
      <MatchJDModal
        resumeId={1}
        resumeFilename="test.pdf"
        open={true}
        onClose={onClose}
      />
    );
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("重试按钮重新发送请求", async () => {
    vi.mocked(matchJD).mockRejectedValueOnce(new Error("失败"));
    render(
      <MatchJDModal
        resumeId={1}
        resumeFilename="test.pdf"
        open={true}
        onClose={() => {}}
      />
    );
    const textarea = screen.getByPlaceholderText(/粘贴职位描述/);
    fireEvent.change(textarea, { target: { value: "Python 工程师" } });
    fireEvent.click(screen.getByText("开始匹配"));

    await waitFor(() => {
      expect(screen.getByText("重试")).toBeInTheDocument();
    });

    vi.mocked(matchJD).mockResolvedValueOnce(mockResult);
    fireEvent.click(screen.getByText("重试"));
    await waitFor(() => {
      expect(screen.getByText(/85\/100/)).toBeInTheDocument();
    });
    expect(matchJD).toHaveBeenCalledTimes(2);
  });

  it("标题栏显示文件名", () => {
    render(
      <MatchJDModal
        resumeId={1}
        resumeFilename="张三_后端.pdf"
        open={true}
        onClose={() => {}}
      />
    );
    expect(screen.getByText("张三_后端.pdf")).toBeInTheDocument();
  });
});
