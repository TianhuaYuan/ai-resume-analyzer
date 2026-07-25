import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, fireEvent, act, waitFor, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import ResumeListPage from "./ResumeListPage";

vi.mock("../api/resumes", () => ({
  listResumes: vi.fn(async () => ({ items: [], total: 0 })),
  uploadResume: vi.fn(async (file: File) => ({
    id: Math.random(),
    filename: file.name,
    status: "processing",
  })),
  getResume: vi.fn(), // 不 resolve，轮询定时器保持存活
  deleteResume: vi.fn(),
}));

// P2-13: mock 掉依赖 useToast 的 Modal 组件，让测试聚焦上传逻辑
vi.mock("../components/AnalysisModal", () => ({
  default: () => null,
}));
vi.mock("../components/ChunksModal", () => ({
  default: () => null,
}));
vi.mock("../components/ResumeViewer", () => ({
  default: () => null,
}));
vi.mock("../components/MatchJDModal", () => ({
  default: () => null,
}));

import { uploadResume } from "../api/resumes";

describe("ResumeListPage 轮询定时器 (H8)", () => {
  // eslint 之外用 any 仅用于测试桩，避免 vitest 重载类型推断问题
  let setIntervalSpy: any;
  let clearIntervalSpy: any;

  beforeEach(() => {
    vi.useFakeTimers();
    setIntervalSpy = vi.spyOn(global, "setInterval");
    clearIntervalSpy = vi.spyOn(global, "clearInterval");
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("连续上传两次只保留一个轮询定时器，旧的不泄漏", async () => {
    const { container } = render(
      <MemoryRouter>
        <ResumeListPage />
      </MemoryRouter>
    );

    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    const file1 = new File(["x"], "a.pdf", { type: "application/pdf" });
    const file2 = new File(["y"], "b.pdf", { type: "application/pdf" });

    // 第一次上传 → 启动轮询 #1
    await act(async () => {
      fireEvent.change(input, { target: { files: [file1] } });
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(uploadResume).toHaveBeenCalledTimes(1);
    expect(setIntervalSpy).toHaveBeenCalledTimes(1);
    expect(clearIntervalSpy).toHaveBeenCalledTimes(0);

    // 第二次上传（第一份仍在 processing）→ startPoll 应先清掉 #1 再启动 #2
    await act(async () => {
      fireEvent.change(input, { target: { files: [file2] } });
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(uploadResume).toHaveBeenCalledTimes(2);
    expect(setIntervalSpy).toHaveBeenCalledTimes(2);
    // 修复后：第二次 startPoll 先 clearInterval 旧的，避免定时器泄漏
    expect(clearIntervalSpy).toHaveBeenCalledTimes(1);
  });
});

// ── B2 拖拽上传测试 ──

describe("ResumeListPage 拖拽上传 (B2)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("拖拽文件到页面触发上传", async () => {
    const { container } = render(
      <MemoryRouter>
        <ResumeListPage />
      </MemoryRouter>
    );

    const dropZone = container.querySelector(".drop-zone") as HTMLElement;
    const file = new File(["test"], "test.pdf", { type: "application/pdf" });

    // 模拟 dragover + drop
    await act(async () => {
      fireEvent.dragOver(dropZone);
    });

    await act(async () => {
      const dataTransfer = { files: [file] };
      fireEvent.drop(dropZone, { dataTransfer });
    });

    await waitFor(() => {
      expect(uploadResume).toHaveBeenCalled();
    });
  });

  it("拖拽时显示高亮样式", async () => {
    const { container } = render(
      <MemoryRouter>
        <ResumeListPage />
      </MemoryRouter>
    );

    const dropZone = container.querySelector(".drop-zone") as HTMLElement;

    // 初始无高亮
    expect(dropZone.classList.contains("ring-indigo-500")).toBe(false);

    await act(async () => {
      fireEvent.dragOver(dropZone);
    });

    await waitFor(() => {
      expect(dropZone.classList.contains("ring-indigo-500")).toBe(true);
    });

    await act(async () => {
      fireEvent.dragLeave(dropZone);
    });

    await waitFor(() => {
      expect(dropZone.classList.contains("ring-indigo-500")).toBe(false);
    });
  });
});

// ── P2-13: 统一类型校验测试 ──

describe("ResumeListPage 上传类型校验 (P2-13)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("点击上传非 PDF/DOCX 文件时不调用 uploadResume", async () => {
    const { container } = render(
      <MemoryRouter>
        <ResumeListPage />
      </MemoryRouter>
    );

    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    // .txt 文件不在白名单内
    const txtFile = new File(["x"], "a.txt", { type: "text/plain" });

    await act(async () => {
      fireEvent.change(input, { target: { files: [txtFile] } });
    });

    // 修复前：handleUpload 无类型校验，会直接调 uploadResume
    // 修复后：doUpload 统一校验，拒绝非 PDF/DOCX
    expect(uploadResume).not.toHaveBeenCalled();
  });

  it("拖拽上传非 PDF/DOCX 文件时不调用 uploadResume", async () => {
    const { container } = render(
      <MemoryRouter>
        <ResumeListPage />
      </MemoryRouter>
    );

    const dropZone = container.querySelector(".drop-zone") as HTMLElement;
    const exeFile = new File(["x"], "malicious.exe", { type: "application/octet-stream" });

    await act(async () => {
      fireEvent.drop(dropZone, { dataTransfer: { files: [exeFile] } });
    });

    expect(uploadResume).not.toHaveBeenCalled();
  });

  it("P3-4: 超过 10MB 的文件不调用 uploadResume", async () => {
    const { container } = render(
      <MemoryRouter>
        <ResumeListPage />
      </MemoryRouter>
    );

    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    // 构造 11MB 的文件（超过 10MB 限制）
    const largeFile = new File([new Uint8Array(11 * 1024 * 1024)], "big.pdf", {
      type: "application/pdf",
    });

    await act(async () => {
      fireEvent.change(input, { target: { files: [largeFile] } });
    });

    // 客户端预检拦截，不会调 uploadResume
    expect(uploadResume).not.toHaveBeenCalled();
  });
});
