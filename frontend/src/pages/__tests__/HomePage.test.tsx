import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import HomePage from "../HomePage";
import {
  listResumes,
  uploadResume,
  generateIdempotencyKey,
} from "../../api/resumes";
import { createBuilderResume } from "../../api/builder";

const mockNavigate = vi.fn();

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return { ...actual, useNavigate: () => mockNavigate };
});

vi.mock("../../api/resumes", () => ({
  listResumes: vi.fn(),
  uploadResume: vi.fn(),
  generateIdempotencyKey: vi.fn(),
}));

vi.mock("../../api/builder", () => ({
  createBuilderResume: vi.fn(),
}));

vi.mock("../../api/analytics", () => ({
  trackEvent: vi.fn(),
  getCtaSource: vi.fn(),
}));

vi.mock("../../components/Toast", () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn() }),
}));

function makeResume(id: number) {
  return {
    id,
    filename: `resume-${id}.pdf`,
    parsed_text: "",
    chunk_count: 3,
    status: "ready",
    status_message: "",
    created_at: "",
  };
}

describe("HomePage 智能分流", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("无简历时渲染引导入口", async () => {
    vi.mocked(listResumes).mockResolvedValue({ items: [], total: 0 });
    render(<HomePage />);

    expect(await screen.findByText(/开始你的/)).toBeInTheDocument();
    expect(screen.getByText("新建简历 →")).toBeInTheDocument();
    expect(screen.getByText("上传简历")).toBeInTheDocument();
    expect(mockNavigate).not.toHaveBeenCalled();
  });

  it("有简历时 replace 重定向到最近一份", async () => {
    vi.mocked(listResumes).mockResolvedValue({
      items: [makeResume(5)],
      total: 1,
    });
    render(<HomePage />);

    await waitFor(() =>
      expect(mockNavigate).toHaveBeenCalledWith("/resumes/5", { replace: true })
    );
    // 引导页不应出现
    expect(screen.queryByText("新建简历 →")).not.toBeInTheDocument();
  });

  it("listResumes 失败时兜底渲染引导页", async () => {
    vi.mocked(listResumes).mockRejectedValue(new Error("网络错误"));
    render(<HomePage />);

    expect(await screen.findByText(/开始你的/)).toBeInTheDocument();
  });

  it("点击新建简历 → 直达编辑页 ?tab=edit", async () => {
    vi.mocked(listResumes).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(createBuilderResume).mockResolvedValue({
      id: 7,
      filename: "未命名简历",
      status: "draft",
      source: "builder",
      style: null,
      version: 1,
      created_at: "",
      modules: [],
    });
    render(<HomePage />);

    const createBtn = await screen.findByText("新建简历 →");
    fireEvent.click(createBtn);

    await waitFor(() =>
      expect(mockNavigate).toHaveBeenCalledWith("/resumes/7?tab=edit")
    );
  });

  it("上传文件成功 → 跳转新简历问答页", async () => {
    vi.mocked(listResumes).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(generateIdempotencyKey).mockResolvedValue("mock-key");
    const file = new File(["%PDF-1.4"], "resume.pdf", { type: "application/pdf" });
    vi.mocked(uploadResume).mockResolvedValue({
      id: 9,
      filename: "resume.pdf",
      status: "processing",
    });

    const { container } = render(<HomePage />);
    await screen.findByText(/开始你的/);

    const input = container.querySelector('input[type="file"]');
    expect(input).not.toBeNull();
    fireEvent.change(input!, { target: { files: [file] } });

    await waitFor(() => {
      expect(uploadResume).toHaveBeenCalledWith(file, "mock-key");
      expect(mockNavigate).toHaveBeenCalledWith("/resumes/9");
    });
  });

  it("上传非法文件类型 → 提示错误且不跳转", async () => {
    vi.mocked(listResumes).mockResolvedValue({ items: [], total: 0 });
    const badFile = new File(["hello"], "note.txt", { type: "text/plain" });

    const { container } = render(<HomePage />);
    await screen.findByText(/开始你的/);

    const input = container.querySelector('input[type="file"]');
    fireEvent.change(input!, { target: { files: [badFile] } });

    expect(await screen.findByText(/仅支持 PDF \/ DOCX/)).toBeInTheDocument();
    expect(uploadResume).not.toHaveBeenCalled();
    expect(mockNavigate).not.toHaveBeenCalled();
  });
});
