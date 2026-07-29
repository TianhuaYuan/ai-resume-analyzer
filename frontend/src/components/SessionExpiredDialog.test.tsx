import { describe, it, expect, vi, afterEach } from "vitest";
import { render, fireEvent, screen } from "@testing-library/react";
import SessionExpiredDialog from "./SessionExpiredDialog";

afterEach(() => {
  vi.restoreAllMocks();
});

function renderDialog(props: Partial<React.ComponentProps<typeof SessionExpiredDialog>> = {}) {
  const defaultProps = {
    open: true,
    onGoLogin: vi.fn(),
  };
  return render(<SessionExpiredDialog {...defaultProps} {...props} />);
}

describe("SessionExpiredDialog — 登录已过期", () => {
  it("open=false 时不渲染", () => {
    renderDialog({ open: false });
    expect(screen.queryByText("登录已过期")).toBeNull();
  });

  it("显示「登录已过期」标题和描述文案", () => {
    renderDialog();
    expect(screen.getByText("登录已过期")).toBeInTheDocument();
    expect(screen.getByText(/登录状态已失效/)).toBeInTheDocument();
  });

  it("显示「去登录」按钮", () => {
    renderDialog();
    expect(screen.getByRole("button", { name: "去登录" })).toBeInTheDocument();
  });

  it("点「去登录」调用 onGoLogin", () => {
    const onGoLogin = vi.fn();
    renderDialog({ onGoLogin });
    fireEvent.click(screen.getByRole("button", { name: "去登录" }));
    expect(onGoLogin).toHaveBeenCalledTimes(1);
  });

  it("按 Esc 不能关闭弹窗", () => {
    const onGoLogin = vi.fn();
    renderDialog({ onGoLogin });
    const dialog = document.querySelector("dialog");
    expect(dialog).not.toBeNull();
    dialog!.dispatchEvent(new Event("cancel", { cancelable: true }));
    // 弹窗仍在
    expect(screen.getByText("登录已过期")).toBeInTheDocument();
  });

  it("点 backdrop 遮罩不能关闭弹窗", () => {
    const onGoLogin = vi.fn();
    renderDialog({ onGoLogin });
    const dialog = document.querySelector("dialog");
    expect(dialog).not.toBeNull();
    dialog!.dispatchEvent(new Event("close"));
    expect(screen.getByText("登录已过期")).toBeInTheDocument();
  });
});
