import { describe, it, expect, vi, afterEach } from "vitest";
import { render, fireEvent, waitFor, screen, act } from "@testing-library/react";
import { ToastProvider, useToast, ToastContainer } from "./Toast";

function TestHarness() {
  const toast = useToast();
  return (
    <div>
      <button onClick={() => toast.success("操作成功")}>success</button>
      <button onClick={() => toast.error("操作失败")}>error</button>
      <button onClick={() => toast.info("提示信息")}>info</button>
      <button onClick={() => toast.success("带标题", { title: "标题" })}>with-title</button>
    </div>
  );
}

function renderToast() {
  return render(
    <ToastProvider>
      <TestHarness />
      <ToastContainer />
    </ToastProvider>
  );
}

describe("Toast 系统", () => {
  // 兜底：防止某个测试用 fake timers 后泄漏到后续测试
  afterEach(() => {
    vi.useRealTimers();
  });

  // ── 基础渲染 ──

  it("初始状态不渲染任何 Toast", () => {
    renderToast();
    expect(screen.queryByRole("status")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  // ── 三种类型（success/info 用 role=status，error 用 role=alert）──

  it("toast.success 显示成功 Toast（绿色 + role=status）", async () => {
    renderToast();
    await act(async () => {
      fireEvent.click(screen.getByText("success"));
    });
    await waitFor(() => {
      expect(screen.getByRole("status")).toHaveTextContent("操作成功");
    });
    expect(screen.getByRole("status")).toHaveClass("bg-emerald-500");
  });

  it("toast.error 显示错误 Toast（红色 + role=alert）", async () => {
    renderToast();
    await act(async () => {
      fireEvent.click(screen.getByText("error"));
    });
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("操作失败");
    });
    expect(screen.getByRole("alert")).toHaveClass("bg-red-500");
  });

  it("toast.info 显示信息 Toast（蓝色 + role=status）", async () => {
    renderToast();
    await act(async () => {
      fireEvent.click(screen.getByText("info"));
    });
    await waitFor(() => {
      expect(screen.getByRole("status")).toHaveTextContent("提示信息");
    });
    expect(screen.getByRole("status")).toHaveClass("bg-blue-500");
  });

  // ── aria-live 无障碍 ──

  it("success Toast 有 aria-live='polite'（不打断用户）", async () => {
    renderToast();
    await act(async () => {
      fireEvent.click(screen.getByText("success"));
    });
    await waitFor(() => {
      expect(screen.getByRole("status")).toHaveAttribute("aria-live", "polite");
    });
  });

  it("error Toast 有 aria-live='assertive'（立即播报）", async () => {
    renderToast();
    await act(async () => {
      fireEvent.click(screen.getByText("error"));
    });
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveAttribute("aria-live", "assertive");
    });
  });

  // ── 进度条（success 有，error 无）──

  it("success Toast 有进度条显示剩余时间", async () => {
    renderToast();
    await act(async () => {
      fireEvent.click(screen.getByText("success"));
    });
    await waitFor(() => {
      const toast = screen.getByRole("status");
      const progressBar = toast.querySelector("[data-testid='toast-progress']");
      expect(progressBar).not.toBeNull();
    });
  });

  it("error Toast 无进度条（不自动消失）", async () => {
    renderToast();
    await act(async () => {
      fireEvent.click(screen.getByText("error"));
    });
    await waitFor(() => {
      const toast = screen.getByRole("alert");
      const progressBar = toast.querySelector("[data-testid='toast-progress']");
      expect(progressBar).toBeNull();
    });
  });

  // ── 自动消失 ──

  it("success 3 秒后自动消失", async () => {
    renderToast();
    await act(async () => {
      fireEvent.click(screen.getByText("success"));
    });
    await waitFor(() => expect(screen.getByRole("status")).toBeInTheDocument());

    await act(async () => {
      await new Promise((r) => setTimeout(r, 3500));
    });

    await waitFor(() => {
      expect(screen.queryByRole("status")).toBeNull();
    });
  });

  it("error Toast 不自动消失（6秒后仍存在）", async () => {
    renderToast();
    await act(async () => {
      fireEvent.click(screen.getByText("error"));
    });
    // 在 real timers 下确认 Toast 渲染（waitFor 依赖 setTimeout）
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());

    // 切到 fake timers 推进 6 秒，确认 error Toast 仍在
    // error 的 AUTO_DISMISS_MS=null，useEffect 不注册 setTimeout，advanceTimersByTime 不会触发消失
    vi.useFakeTimers();
    try {
      await act(async () => {
        vi.advanceTimersByTime(6000);
      });
      expect(screen.getByRole("alert")).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  // ── 手动关闭 ──

  it("点 X 按钮立即关闭", async () => {
    renderToast();
    await act(async () => {
      fireEvent.click(screen.getByText("success"));
    });
    await waitFor(() => expect(screen.getByRole("status")).toBeInTheDocument());

    const closeBtn = screen.getByRole("button", { name: /关闭/ });
    await act(async () => {
      fireEvent.click(closeBtn);
    });

    await waitFor(() => {
      expect(screen.queryByRole("status")).toBeNull();
    });
  });

  // ── 可选标题 ──

  it("支持可选 title", async () => {
    renderToast();
    await act(async () => {
      fireEvent.click(screen.getByText("with-title"));
    });
    await waitFor(() => {
      expect(screen.getByText("标题")).toBeInTheDocument();
      expect(screen.getByText("带标题")).toBeInTheDocument();
    });
  });

  // ── 队列管理 ──

  it("多个 Toast 同时显示时队列排列（最多 3 个）", async () => {
    renderToast();
    await act(async () => {
      fireEvent.click(screen.getByText("success"));
      fireEvent.click(screen.getByText("error"));
      fireEvent.click(screen.getByText("info"));
      fireEvent.click(screen.getByText("success")); // 第 4 个
    });

    await waitFor(() => {
      const all = screen.queryAllByRole("status").concat(screen.queryAllByRole("alert"));
      expect(all.length).toBe(3); // 最多 3 个
    });
  });

  // ── 移动端底部响应式 ──

  it("ToastContainer 移动端底部 + 桌面端 top-right（响应式类）", async () => {
    renderToast();
    await act(async () => {
      fireEvent.click(screen.getByText("success"));
    });
    await waitFor(() => expect(screen.getByRole("status")).toBeInTheDocument());

    const container = screen.getByRole("status").parentElement;
    expect(container).not.toBeNull();
    // 移动端底部居中
    expect(container!.className).toMatch(/bottom-4/);
    expect(container!.className).toMatch(/left-1\/2/);
    // 桌面端 top-right
    expect(container!.className).toMatch(/md:top-4/);
    expect(container!.className).toMatch(/md:right-4/);
  });
});
