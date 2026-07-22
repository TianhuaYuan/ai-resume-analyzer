import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
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
  // ── 基础渲染 ──

  it("初始状态不渲染任何 Toast", () => {
    renderToast();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  // ── 三种类型 ──

  it("toast.success 显示成功 Toast（绿色）", async () => {
    renderToast();
    await act(async () => {
      fireEvent.click(screen.getByText("success"));
    });
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("操作成功");
    });
    expect(screen.getByRole("alert")).toHaveClass("bg-emerald-500");
  });

  it("toast.error 显示错误 Toast（红色）", async () => {
    renderToast();
    await act(async () => {
      fireEvent.click(screen.getByText("error"));
    });
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("操作失败");
    });
    expect(screen.getByRole("alert")).toHaveClass("bg-red-500");
  });

  it("toast.info 显示信息 Toast（蓝色）", async () => {
    renderToast();
    await act(async () => {
      fireEvent.click(screen.getByText("info"));
    });
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("提示信息");
    });
    expect(screen.getByRole("alert")).toHaveClass("bg-blue-500");
  });

  // ── 自动消失 ──

  it("success 3 秒后自动消失", async () => {
    renderToast();
    await act(async () => {
      fireEvent.click(screen.getByText("success"));
    });
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());

    // 等待 3s + 缓冲
    await act(async () => {
      await new Promise((r) => setTimeout(r, 3500));
    });

    await waitFor(() => {
      expect(screen.queryByRole("alert")).toBeNull();
    });
  });

  // ── 手动关闭 ──

  it("点 X 按钮立即关闭", async () => {
    renderToast();
    await act(async () => {
      fireEvent.click(screen.getByText("success"));
    });
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());

    const closeBtn = screen.getByRole("button", { name: /关闭/ });
    await act(async () => {
      fireEvent.click(closeBtn);
    });

    await waitFor(() => {
      expect(screen.queryByRole("alert")).toBeNull();
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
      const toasts = screen.getAllByRole("alert");
      expect(toasts.length).toBe(3); // 最多 3 个
    });
  });
});