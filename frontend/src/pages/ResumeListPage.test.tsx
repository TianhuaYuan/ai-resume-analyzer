import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, fireEvent, act } from "@testing-library/react";
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
