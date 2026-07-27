import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import ResumeListPage from "../ResumeListPage";

// 默认 mock：所有 API 调用成功
vi.mock("../../api/resumes", () => ({
  listResumes: vi.fn(async () => ({ items: [], total: 0 })),
  uploadResume: vi.fn(async () => ({
    id: 1,
    filename: "test.pdf",
    status: "processing",
  })),
  deleteResume: vi.fn(async () => undefined),
  getResume: vi.fn(async () => ({
    id: 1,
    filename: "test.pdf",
    parsed_text: "",
    chunk_count: 0,
    status: "ready",
    status_message: "",
    created_at: "2026-07-26",
  })),
  retryResume: vi.fn(async () => ({
    id: 1,
    filename: "test.pdf",
    status: "processing",
  })),
  generateIdempotencyKey: vi.fn(async () => "mock-hash-key-aaaa"),
}));

vi.mock("../../components/AnalysisModal", () => ({
  default: () => <div data-testid="analysis-modal" />,
}));

vi.mock("../../components/ChunksModal", () => ({
  default: () => <div data-testid="chunks-modal" />,
}));

vi.mock("../../components/ResumeViewer", () => ({
  default: () => <div data-testid="resume-viewer" />,
}));

vi.mock("../../components/MatchJDModal", () => ({
  default: () => <div data-testid="match-jd-modal" />,
}));

vi.mock("../../components/MoreMenu", () => ({
  default: () => null,
}));

vi.mock("../../components/Toast", () => ({
  useToast: () => ({
    success: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
    warning: vi.fn(),
  }),
}));

import {
  listResumes,
  uploadResume,
  generateIdempotencyKey,
  deleteResume,
} from "../../api/resumes";

function renderPage() {
  return render(
    <MemoryRouter>
      <ResumeListPage />
    </MemoryRouter>
  );
}

function makeFile(name = "test.pdf", size = 1024) {
  const file = new File(["content"], name, { type: "application/pdf" });
  Object.defineProperty(file, "size", { value: size });
  Object.defineProperty(file, "lastModified", { value: 1700000000000 });
  return file;
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(listResumes).mockResolvedValue({ items: [], total: 0 });
  vi.mocked(uploadResume).mockResolvedValue({
    id: 1,
    filename: "test.pdf",
    status: "processing",
  });
  vi.mocked(generateIdempotencyKey).mockResolvedValue("mock-hash-key-aaaa");
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("ResumeListPage Task 2.6 Idempotency-Key 重试复用", () => {
  it("上传失败时显示「重试上传」按钮", async () => {
    vi.mocked(uploadResume).mockRejectedValueOnce(new Error("网络错误"));
    renderPage();
    await waitFor(() => expect(listResumes).toHaveBeenCalled());

    // 触发上传
    const input = document.querySelector(
      'input[type="file"]'
    ) as HTMLInputElement;
    fireEvent.change(input, { target: { files: [makeFile()] } });

    await waitFor(() => {
      expect(screen.getByText("重试上传")).toBeInTheDocument();
    });
  });

  it("点击「重试上传」复用上次 lastUploadKey（显式传 overrideKey）", async () => {
    vi.mocked(uploadResume).mockRejectedValueOnce(new Error("网络错误"));
    renderPage();
    await waitFor(() => expect(listResumes).toHaveBeenCalled());

    const file = makeFile();
    const input = document.querySelector(
      'input[type="file"]'
    ) as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file] } });

    // 等待首次上传失败
    await waitFor(() => {
      expect(screen.getByText("重试上传")).toBeInTheDocument();
    });

    // 首次上传应调用 uploadResume(file, key)，key 来自 generateIdempotencyKey
    expect(uploadResume).toHaveBeenCalledTimes(1);
    const firstCallArgs = vi.mocked(uploadResume).mock.calls[0];
    expect(firstCallArgs[0]).toBe(file);
    expect(firstCallArgs[1]).toBe("mock-hash-key-aaaa"); // overrideKey

    // 点击重试
    fireEvent.click(screen.getByText("重试上传"));

    await waitFor(() => {
      expect(uploadResume).toHaveBeenCalledTimes(2);
    });

    // 重试应复用同 key（而非重新计算 hash）
    const retryCallArgs = vi.mocked(uploadResume).mock.calls[1];
    expect(retryCallArgs[1]).toBe("mock-hash-key-aaaa");
    // generateIdempotencyKey 应只被调用 1 次（首次），重试时不重新计算
    expect(generateIdempotencyKey).toHaveBeenCalledTimes(1);
  });

  it("上传成功后不显示「重试上传」按钮", async () => {
    renderPage();
    await waitFor(() => expect(listResumes).toHaveBeenCalled());

    const input = document.querySelector(
      'input[type="file"]'
    ) as HTMLInputElement;
    fireEvent.change(input, { target: { files: [makeFile()] } });

    // 等待上传成功
    await waitFor(() => {
      expect(uploadResume).toHaveBeenCalled();
    });

    // 成功时不应显示重试按钮
    expect(screen.queryByText("重试上传")).toBeNull();
  });

  it("首次上传前调用 generateIdempotencyKey 计算 key 并传给 uploadResume", async () => {
    renderPage();
    await waitFor(() => expect(listResumes).toHaveBeenCalled());

    const input = document.querySelector(
      'input[type="file"]'
    ) as HTMLInputElement;
    fireEvent.change(input, { target: { files: [makeFile()] } });

    await waitFor(() => {
      expect(uploadResume).toHaveBeenCalled();
    });

    expect(generateIdempotencyKey).toHaveBeenCalledTimes(1);
    const uploadArgs = vi.mocked(uploadResume).mock.calls[0];
    expect(uploadArgs[1]).toBe("mock-hash-key-aaaa");
  });
});

// ── Task 5.6: 删除确认弹窗使用共享 ConfirmDialog（原生 <dialog> + focus trap） ──

const mockReadyResume = {
  id: 1,
  filename: "test-resume.pdf",
  parsed_text: "test content",
  chunk_count: 5,
  status: "ready",
  status_message: "",
  created_at: "2026-07-27T00:00:00Z",
};

describe("Task 5.6: ResumeListPage 删除确认弹窗重构", () => {
  beforeEach(() => {
    vi.mocked(listResumes).mockResolvedValue({
      items: [mockReadyResume],
      total: 1,
    });
    vi.mocked(deleteResume).mockResolvedValue(undefined);
  });

  it("点击删除按钮后，弹窗使用原生 <dialog> 元素（非普通 <div>）", async () => {
    renderPage();
    await screen.findByText("test-resume.pdf");

    const deleteBtns = screen.getAllByText("删除");
    fireEvent.click(deleteBtns[0]);

    // 共享 ConfirmDialog 使用 <dialog>，内联版用 <div>
    const dialog = document.querySelector("dialog");
    expect(dialog).not.toBeNull();
    expect(dialog!.hasAttribute("open")).toBe(true);
  });

  it("删除确认弹窗显示正确的标题和描述", async () => {
    renderPage();
    await screen.findByText("test-resume.pdf");

    const deleteBtns = screen.getAllByText("删除");
    fireEvent.click(deleteBtns[0]);

    const dialog = document.querySelector("dialog")!;
    const dialogContent = within(dialog as HTMLElement);

    expect(dialogContent.getByText("确认删除")).toBeInTheDocument();
    expect(dialogContent.getByText(/test-resume\.pdf/)).toBeInTheDocument();
  });

  it("弹窗具有 aria-modal 和 role=dialog 属性（无障碍 focus trap 标识）", async () => {
    renderPage();
    await screen.findByText("test-resume.pdf");

    const deleteBtns = screen.getAllByText("删除");
    fireEvent.click(deleteBtns[0]);

    const dialog = document.querySelector("dialog")!;
    expect(dialog.getAttribute("aria-modal")).toBe("true");
    expect(dialog.getAttribute("role")).toBe("dialog");
  });

  it("按 Esc 关闭弹窗（调用 onCancel），不执行删除", async () => {
    renderPage();
    await screen.findByText("test-resume.pdf");

    const deleteBtns = screen.getAllByText("删除");
    fireEvent.click(deleteBtns[0]);

    const dialog = document.querySelector("dialog")!;
    dialog.dispatchEvent(new Event("cancel", { cancelable: true }));

    expect(deleteResume).not.toHaveBeenCalled();
    await waitFor(() => {
      expect(document.querySelector("dialog[open]")).toBeNull();
    });
  });

  it("点确认按钮执行删除", async () => {
    renderPage();
    await screen.findByText("test-resume.pdf");

    const deleteBtns = screen.getAllByText("删除");
    fireEvent.click(deleteBtns[0]);

    const dialog = document.querySelector("dialog")!;
    const dialogContent = within(dialog as HTMLElement);
    fireEvent.click(dialogContent.getByRole("button", { name: "删除" }));

    expect(deleteResume).toHaveBeenCalledWith(1);
  });

  it("弹窗确认按钮为 danger 红色主题", async () => {
    renderPage();
    await screen.findByText("test-resume.pdf");

    const deleteBtns = screen.getAllByText("删除");
    fireEvent.click(deleteBtns[0]);

    const dialog = document.querySelector("dialog")!;
    const dialogContent = within(dialog as HTMLElement);

    const confirmBtn = dialogContent.getByRole("button", { name: "删除" });
    expect(confirmBtn.className).toMatch(/bg-red-500/);
  });
});

// ── Task 5.5: 批量上传 + 批量删除 ──

const mockResumeList = [
  { id: 1, filename: "resume-a.pdf", parsed_text: "a", chunk_count: 3, status: "ready", status_message: "", created_at: "2026-07-27T00:00:00Z" },
  { id: 2, filename: "resume-b.pdf", parsed_text: "b", chunk_count: 5, status: "ready", status_message: "", created_at: "2026-07-27T01:00:00Z" },
  { id: 3, filename: "resume-c.pdf", parsed_text: "c", chunk_count: 2, status: "failed", status_message: "解析失败", created_at: "2026-07-27T02:00:00Z" },
];

describe("Task 5.5: 批量上传", () => {
  it("文件输入支持 multiple 属性，可选择多个文件", async () => {
    vi.mocked(listResumes).mockResolvedValue({ items: [], total: 0 });
    renderPage();
    await waitFor(() => expect(listResumes).toHaveBeenCalled());

    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    expect(input.hasAttribute("multiple")).toBe(true);
  });

  it("选择多个文件时，逐个上传每个文件", async () => {
    vi.mocked(listResumes).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(uploadResume)
      .mockResolvedValueOnce({ id: 1, filename: "a.pdf", status: "processing" })
      .mockResolvedValueOnce({ id: 2, filename: "b.pdf", status: "processing" });

    renderPage();
    await waitFor(() => expect(listResumes).toHaveBeenCalled());

    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const fileA = makeFile("a.pdf");
    const fileB = makeFile("b.pdf");
    fireEvent.change(input, { target: { files: [fileA, fileB] } });

    await waitFor(() => {
      expect(uploadResume).toHaveBeenCalledTimes(2);
    });
  });

  it("多文件上传中部分失败时，显示失败数量提示", async () => {
    vi.mocked(listResumes).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(uploadResume)
      .mockResolvedValueOnce({ id: 1, filename: "a.pdf", status: "processing" })
      .mockRejectedValueOnce(new Error("网络错误"));

    renderPage();
    await waitFor(() => expect(listResumes).toHaveBeenCalled());

    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const fileA = makeFile("a.pdf");
    const fileB = makeFile("b.pdf");
    fireEvent.change(input, { target: { files: [fileA, fileB] } });

    await waitFor(() => {
      // 应该显示失败提示（包含失败数量）
      expect(screen.getByText(/1.*失败|失败.*1/)).toBeInTheDocument();
    });
  });
});

describe("Task 5.5: 批量删除", () => {
  beforeEach(() => {
    vi.mocked(listResumes).mockResolvedValue({ items: mockResumeList, total: 3 });
    vi.mocked(deleteResume).mockResolvedValue(undefined);
  });

  it("点击「管理」按钮进入选择模式，每行出现复选框", async () => {
    renderPage();
    await screen.findByText("resume-a.pdf");

    // 点击「管理」按钮进入选择模式
    fireEvent.click(screen.getByRole("button", { name: /管理/ }));

    // 每行简历出现复选框
    const checkboxes = screen.getAllByRole("checkbox", { name: /选择/ });
    expect(checkboxes.length).toBeGreaterThanOrEqual(3);
  });

  it("选择模式下顶部显示「全选」复选框和「删除所选」按钮", async () => {
    renderPage();
    await screen.findByText("resume-a.pdf");

    fireEvent.click(screen.getByRole("button", { name: /管理/ }));

    expect(screen.getByRole("checkbox", { name: /全选/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /删除所选/ })).toBeInTheDocument();
  });

  it("勾选简历后点「删除所选」弹出确认弹窗，显示所选数量", async () => {
    renderPage();
    await screen.findByText("resume-a.pdf");

    fireEvent.click(screen.getByRole("button", { name: /管理/ }));

    // 勾选前两个
    const checkboxes = screen.getAllByRole("checkbox", { name: /选择/ });
    fireEvent.click(checkboxes[0]);
    fireEvent.click(checkboxes[1]);

    // 点删除所选
    fireEvent.click(screen.getByRole("button", { name: /删除所选/ }));

    // 确认弹窗应显示数量
    const dialog = document.querySelector("dialog")!;
    const dialogContent = within(dialog as HTMLElement);
    expect(dialogContent.getByText(/2/)).toBeInTheDocument();
  });

  it("确认批量删除后，逐个调用 deleteResume", async () => {
    renderPage();
    await screen.findByText("resume-a.pdf");

    fireEvent.click(screen.getByRole("button", { name: /管理/ }));

    const checkboxes = screen.getAllByRole("checkbox", { name: /选择/ });
    fireEvent.click(checkboxes[0]);
    fireEvent.click(checkboxes[1]);

    fireEvent.click(screen.getByRole("button", { name: /删除所选/ }));

    const dialog = document.querySelector("dialog")!;
    const dialogContent = within(dialog as HTMLElement);
    fireEvent.click(dialogContent.getByRole("button", { name: "删除" }));

    await waitFor(() => {
      expect(deleteResume).toHaveBeenCalledTimes(2);
    });
  });

  it("全选后删除所有简历", async () => {
    renderPage();
    await screen.findByText("resume-a.pdf");

    fireEvent.click(screen.getByRole("button", { name: /管理/ }));

    fireEvent.click(screen.getByRole("checkbox", { name: /全选/ }));

    // 所有简历都被选中
    const checkboxes = screen.getAllByRole("checkbox", { name: /选择/ });
    checkboxes.forEach((cb) => expect(cb).toBeChecked());

    fireEvent.click(screen.getByRole("button", { name: /删除所选/ }));

    const dialog = document.querySelector("dialog")!;
    const dialogContent = within(dialog as HTMLElement);
    fireEvent.click(dialogContent.getByRole("button", { name: "删除" }));

    await waitFor(() => {
      expect(deleteResume).toHaveBeenCalledTimes(3);
    });
  });

  it("点「取消」退出选择模式，清除所有勾选", async () => {
    renderPage();
    await screen.findByText("resume-a.pdf");

    fireEvent.click(screen.getByRole("button", { name: /管理/ }));

    const checkboxes = screen.getAllByRole("checkbox", { name: /选择/ });
    fireEvent.click(checkboxes[0]);

    // 退出选择模式
    fireEvent.click(screen.getByRole("button", { name: /取消/ }));

    // 复选框应消失
    expect(screen.queryByRole("checkbox", { name: /选择/ })).toBeNull();
  });
});
