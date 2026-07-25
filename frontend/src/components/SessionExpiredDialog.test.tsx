import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, fireEvent, screen, act } from "@testing-library/react";
import SessionExpiredDialog from "./SessionExpiredDialog";

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

function renderExpired(props: Partial<React.ComponentProps<typeof SessionExpiredDialog>> = {}) {
  const defaultProps = {
    open: true,
    mode: "expired" as const,
    onPrimary: vi.fn(),
    onIgnore: vi.fn(),
  };
  return render(<SessionExpiredDialog {...defaultProps} {...props} />);
}

function renderWarning(props: Partial<React.ComponentProps<typeof SessionExpiredDialog>> = {}) {
  const defaultProps = {
    open: true,
    mode: "warning" as const,
    remainingSeconds: 300,
    onPrimary: vi.fn(),
    onIgnore: vi.fn(),
  };
  return render(<SessionExpiredDialog {...defaultProps} {...props} />);
}

describe("SessionExpiredDialog - expired 模式", () => {
  it("open=false 时不渲染", () => {
    renderExpired({ open: false });
    expect(screen.queryByText("登录已过期")).toBeNull();
  });

  it("显示「登录已过期」标题和描述", () => {
    renderExpired();
    expect(screen.getByText("登录已过期")).toBeInTheDocument();
    expect(screen.getByText(/登录状态已失效/)).toBeInTheDocument();
  });

  it("只有「去登录」按钮，没有「忽略」按钮", () => {
    renderExpired();
    expect(screen.getByRole("button", { name: "去登录" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "忽略" })).toBeNull();
  });

  it("点「去登录」调用 onPrimary", () => {
    const onPrimary = vi.fn();
    renderExpired({ onPrimary });
    fireEvent.click(screen.getByRole("button", { name: "去登录" }));
    expect(onPrimary).toHaveBeenCalledTimes(1);
  });

  it("expired 模式下按 Esc 不触发 onIgnore（不能关闭）", () => {
    const onIgnore = vi.fn();
    renderExpired({ onIgnore });
    const dialog = document.querySelector("dialog");
    expect(dialog).not.toBeNull();
    dialog!.dispatchEvent(new Event("cancel", { cancelable: true }));
    expect(onIgnore).not.toHaveBeenCalled();
  });

  it("expired 模式下点 backdrop 不触发 onIgnore（不能关闭）", () => {
    const onIgnore = vi.fn();
    renderExpired({ onIgnore });
    const dialog = document.querySelector("dialog");
    expect(dialog).not.toBeNull();
    dialog!.dispatchEvent(new Event("close"));
    expect(onIgnore).not.toHaveBeenCalled();
  });

  it("loading=true 时「去登录」按钮禁用且显示 spinner", () => {
    const onPrimary = vi.fn();
    renderExpired({ loading: true, onPrimary });
    const btn = screen.getByRole("button", { name: "去登录" });
    expect(btn).toBeDisabled();
    // 有 spinner：一个带 animate-spin 的 span
    expect(btn.querySelector("span.animate-spin")).not.toBeNull();
    fireEvent.click(btn);
    expect(onPrimary).not.toHaveBeenCalled();
  });
});

describe("SessionExpiredDialog - warning 模式", () => {
  it("显示「登录即将过期」标题和倒计时", () => {
    renderWarning({ remainingSeconds: 300 });
    expect(screen.getByText("登录即将过期")).toBeInTheDocument();
    expect(screen.getByText(/还有 5分00秒/)).toBeInTheDocument();
  });

  it("有「延长登录」和「忽略」两个按钮", () => {
    renderWarning();
    expect(screen.getByRole("button", { name: "延长登录" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "忽略" })).toBeInTheDocument();
  });

  it("点「延长登录」调用 onPrimary", () => {
    const onPrimary = vi.fn();
    renderWarning({ onPrimary });
    fireEvent.click(screen.getByRole("button", { name: "延长登录" }));
    expect(onPrimary).toHaveBeenCalledTimes(1);
  });

  it("点「忽略」调用 onIgnore", () => {
    const onIgnore = vi.fn();
    renderWarning({ onIgnore });
    fireEvent.click(screen.getByRole("button", { name: "忽略" }));
    expect(onIgnore).toHaveBeenCalledTimes(1);
  });

  it("按 Esc 调用 onIgnore", () => {
    const onIgnore = vi.fn();
    renderWarning({ onIgnore });
    const dialog = document.querySelector("dialog");
    expect(dialog).not.toBeNull();
    dialog!.dispatchEvent(new Event("cancel", { cancelable: true }));
    expect(onIgnore).toHaveBeenCalledTimes(1);
  });

  it("点 backdrop 调用 onIgnore", () => {
    const onIgnore = vi.fn();
    renderWarning({ onIgnore });
    const dialog = document.querySelector("dialog");
    expect(dialog).not.toBeNull();
    dialog!.dispatchEvent(new Event("close"));
    expect(onIgnore).toHaveBeenCalledTimes(1);
  });

  it("倒计时每秒递减", () => {
    renderWarning({ remainingSeconds: 300 });
    expect(screen.getByText(/5分00秒/)).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(screen.getByText(/4分59秒/)).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(2000);
    });
    expect(screen.getByText(/4分57秒/)).toBeInTheDocument();
  });

  it("loading=true 时两个按钮都禁用", () => {
    const onPrimary = vi.fn();
    const onIgnore = vi.fn();
    renderWarning({ loading: true, onPrimary, onIgnore });
    const extendBtn = screen.getByRole("button", { name: "延长登录" });
    const ignoreBtn = screen.getByRole("button", { name: "忽略" });
    expect(extendBtn).toBeDisabled();
    expect(ignoreBtn).toBeDisabled();
    fireEvent.click(extendBtn);
    fireEvent.click(ignoreBtn);
    expect(onPrimary).not.toHaveBeenCalled();
    expect(onIgnore).not.toHaveBeenCalled();
  });
});
