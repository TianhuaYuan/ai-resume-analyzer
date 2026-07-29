import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { MemoryRouter, useNavigate } from "react-router-dom";
import ResumeListPage from "../ResumeListPage";

const mockNavigate = vi.fn();
vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

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
  compareResumes: vi.fn(async () => ({ resumes: [], dimensions: {} })),
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

  it("列表中删除按钮为红色 danger 样式，与操作按钮区分", async () => {
    renderPage();
    await screen.findByText("test-resume.pdf");

    const card = screen.getByText("test-resume.pdf").closest("[class*='block']");
    const deleteBtn = within(card as HTMLElement).getByText("删除");
    expect(deleteBtn.className).toMatch(/text-red-300/);
    // 危险按钮有明显的红色背景
    expect(deleteBtn.className).toMatch(/bg-red-500\/10/);
  });

  it("操作按钮（预览/分块/分析/JD匹配）与删除按钮分组包裹", async () => {
    renderPage();
    await screen.findByText("test-resume.pdf");

    const card = screen.getByText("test-resume.pdf").closest("[class*='block']");
    // 操作按钮组在一个容器中
    const actionGroup = within(card as HTMLElement).getByTestId("resume-action-group");
    expect(actionGroup).toBeInTheDocument();
    // 删除按钮在单独的容器中
    const deleteGroup = within(card as HTMLElement).getByTestId("resume-delete-group");
    expect(deleteGroup).toBeInTheDocument();
  });

  it("删除按钮带半透明红色背景色（hover/常态都有）", async () => {
    renderPage();
    await screen.findByText("test-resume.pdf");

    const card = screen.getByText("test-resume.pdf").closest("[class*='block']");
    const deleteBtn = within(card as HTMLElement).getByText("删除");
    // 常态有 red-500/10 背景
    expect(deleteBtn.className).toMatch(/bg-red-500\/10/);
  });

  it("就绪状态徽章与功能键区域分离（用容器包裹）", async () => {
    renderPage();
    await screen.findByText("test-resume.pdf");

    const card = screen.getByText("test-resume.pdf").closest("[class*='block']");
    // 状态徽章在独立容器中
    const statusGroup = within(card as HTMLElement).getByTestId("resume-status-group");
    expect(statusGroup).toBeInTheDocument();
  });

  it("就绪状态徽章带绿色背景", async () => {
    renderPage();
    await screen.findByText("test-resume.pdf");

    const badge = screen.getByText("就绪");
    expect(badge.className).toMatch(/bg-emerald-500\/10/);
    expect(badge.className).toMatch(/border-emerald-500\/25/);
    expect(badge.className).toMatch(/text-emerald-400/);
  });

  it("处理中状态徽章带蓝色背景", async () => {
    vi.mocked(listResumes).mockResolvedValueOnce({
      items: [{
        id: 2,
        filename: "processing.pdf",
        parsed_text: "",
        chunk_count: 0,
        status: "processing",
        status_message: "",
        created_at: "2026-07-27T00:00:00Z",
      }],
      total: 1,
    });
    renderPage();
    await screen.findByText("processing.pdf");

    const badge = screen.getByText("处理中");
    expect(badge.className).toMatch(/bg-sky-500\/10/);
    expect(badge.className).toMatch(/border-sky-500\/25/);
    expect(badge.className).toMatch(/text-sky-400/);
  });

  it("失败状态徽章带红色背景", async () => {
    vi.mocked(listResumes).mockResolvedValueOnce({
      items: [{
        id: 3,
        filename: "failed.pdf",
        parsed_text: "",
        chunk_count: 0,
        status: "failed",
        status_message: "解析失败",
        created_at: "2026-07-27T00:00:00Z",
      }],
      total: 1,
    });
    renderPage();
    await screen.findByText("failed.pdf");

    const badge = screen.getByText("失败");
    expect(badge.className).toMatch(/bg-red-500\/10/);
    expect(badge.className).toMatch(/border-red-500\/25/);
    expect(badge.className).toMatch(/text-red-400/);
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

// ── Task 5.3: 多简历对比按钮 ──

const compareResumeList = [
  { id: 1, filename: "resume-a.pdf", parsed_text: "a", chunk_count: 3, status: "ready", status_message: "", created_at: "2026-07-27T00:00:00Z" },
  { id: 2, filename: "resume-b.pdf", parsed_text: "b", chunk_count: 5, status: "ready", status_message: "", created_at: "2026-07-27T01:00:00Z" },
  { id: 3, filename: "resume-c.pdf", parsed_text: "c", chunk_count: 2, status: "ready", status_message: "", created_at: "2026-07-27T02:00:00Z" },
];

describe("Task 5.3: 多简历对比按钮", () => {
  beforeEach(() => {
    vi.mocked(listResumes).mockResolvedValue({ items: compareResumeList, total: 3 });
    mockNavigate.mockClear();
  });

  it("选择模式下选中 2 份简历时，顶部栏显示「对比」按钮", async () => {
    renderPage();
    await screen.findByText("resume-a.pdf");

    // 进入选择模式
    fireEvent.click(screen.getByRole("button", { name: /管理/ }));

    // 勾选 2 份简历
    const checkboxes = screen.getAllByRole("checkbox", { name: /选择/ });
    fireEvent.click(checkboxes[0]);
    fireEvent.click(checkboxes[1]);

    // 「对比」按钮应出现
    expect(screen.getByRole("button", { name: /对比/ })).toBeInTheDocument();
  });

  it("选择模式下选中 < 2 份简历时，「对比」按钮不可点击", async () => {
    renderPage();
    await screen.findByText("resume-a.pdf");

    fireEvent.click(screen.getByRole("button", { name: /管理/ }));

    // 仅勾选 1 份
    const checkboxes = screen.getAllByRole("checkbox", { name: /选择/ });
    fireEvent.click(checkboxes[0]);

    const compareBtn = screen.getByRole("button", { name: /对比/ });
    expect(compareBtn).toBeDisabled();
  });

  it("选择模式下未选中任何简历时，「对比」按钮不可点击", async () => {
    renderPage();
    await screen.findByText("resume-a.pdf");

    fireEvent.click(screen.getByRole("button", { name: /管理/ }));

    const compareBtn = screen.getByRole("button", { name: /对比/ });
    expect(compareBtn).toBeDisabled();
  });

  it("点击「对比」按钮导航到 /compare?ids=1,2", async () => {
    renderPage();
    await screen.findByText("resume-a.pdf");

    fireEvent.click(screen.getByRole("button", { name: /管理/ }));

    const checkboxes = screen.getAllByRole("checkbox", { name: /选择/ });
    fireEvent.click(checkboxes[0]);
    fireEvent.click(checkboxes[1]);

    fireEvent.click(screen.getByRole("button", { name: /对比/ }));

    expect(mockNavigate).toHaveBeenCalledWith("/compare?ids=1,2");
  });

  it("点击「对比」按钮后退出选择模式", async () => {
    renderPage();
    await screen.findByText("resume-a.pdf");

    fireEvent.click(screen.getByRole("button", { name: /管理/ }));

    const checkboxes = screen.getAllByRole("checkbox", { name: /选择/ });
    fireEvent.click(checkboxes[0]);
    fireEvent.click(checkboxes[1]);

    fireEvent.click(screen.getByRole("button", { name: /对比/ }));

    // 选择模式应退出，复选框消失
    await waitFor(() => {
      expect(screen.queryByRole("checkbox", { name: /选择/ })).toBeNull();
    });
  });

  it("「对比」按钮在 resumeIds 超过 5 时仍然可用（服务端校验）", async () => {
    // 添加更多简历（共 6 份）
    const manyResumes = [
      ...compareResumeList,
      { id: 4, filename: "d.pdf", parsed_text: "d", chunk_count: 1, status: "ready", status_message: "", created_at: "2026-07-27T03:00:00Z" },
      { id: 5, filename: "e.pdf", parsed_text: "e", chunk_count: 1, status: "ready", status_message: "", created_at: "2026-07-27T04:00:00Z" },
      { id: 6, filename: "f.pdf", parsed_text: "f", chunk_count: 1, status: "ready", status_message: "", created_at: "2026-07-27T05:00:00Z" },
    ];
    vi.mocked(listResumes).mockResolvedValueOnce({ items: manyResumes, total: 6 });

    renderPage();
    await screen.findByText("resume-a.pdf");

    fireEvent.click(screen.getByRole("button", { name: /管理/ }));

    // 勾选所有 6 份
    fireEvent.click(screen.getByRole("checkbox", { name: /全选/ }));

    const compareBtn = screen.getByRole("button", { name: /对比/ });
    expect(compareBtn).not.toBeDisabled();
  });

  it("非选择模式下，有 ≥2 份就绪简历时直接显示「对比分析」入口按钮", async () => {
    vi.mocked(listResumes).mockResolvedValue({ items: compareResumeList, total: 3 });
    renderPage();
    await screen.findByText("resume-a.pdf");

    // 非选择模式下应看到"对比分析"按钮
    const hintBtn = screen.getByRole("button", { name: /对比分析/ });
    expect(hintBtn).toBeInTheDocument();
    // 点击后进入选择模式 →「对比分析」按钮应消失
    fireEvent.click(hintBtn);
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: /对比分析/ })).toBeNull();
    });
  });

  it("仅有 1 份就绪简历时，不显示「对比分析」入口按钮", async () => {
    vi.mocked(listResumes).mockResolvedValue({
      items: [compareResumeList[0]],
      total: 1,
    });
    renderPage();
    await screen.findByText("resume-a.pdf");

    expect(screen.queryByRole("button", { name: /对比分析/ })).toBeNull();
  });

  it("所有简历都未就绪时，不显示「对比分析」入口按钮", async () => {
    vi.mocked(listResumes).mockResolvedValue({
      items: [
        { ...compareResumeList[0], status: "processing" },
        { ...compareResumeList[1], status: "failed" },
      ],
      total: 2,
    });
    renderPage();
    await screen.findByText("resume-a.pdf");

    expect(screen.queryByRole("button", { name: /对比分析/ })).toBeNull();
  });
});
