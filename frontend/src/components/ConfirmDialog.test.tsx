import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, fireEvent, screen } from "@testing-library/react";
import ConfirmDialog from "./ConfirmDialog";

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

function renderDialog(props: Partial<React.ComponentProps<typeof ConfirmDialog>> = {}) {
  const defaultProps = {
    open: true,
    title: "确认操作",
    description: "这个操作不可逆，确定继续吗？",
    onConfirm: vi.fn(),
    onCancel: vi.fn(),
  };
  return render(<ConfirmDialog {...defaultProps} {...props} />);
}

describe("ConfirmDialog (Task 4 通用确认弹窗)", () => {
  it("open=false 时不渲染", () => {
    renderDialog({ open: false });
    expect(screen.queryByText("确认操作")).toBeNull();
  });

  it("open=true 显示标题和描述", () => {
    renderDialog();
    expect(screen.getByText("确认操作")).toBeInTheDocument();
    expect(screen.getByText(/这个操作不可逆/)).toBeInTheDocument();
  });

  it("显示默认按钮文字（确认/取消）", () => {
    renderDialog();
    expect(screen.getByRole("button", { name: "确认" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "取消" })).toBeInTheDocument();
  });

  it("支持自定义按钮文字", () => {
    renderDialog({ confirmText: "清空", cancelText: "算了" });
    expect(screen.getByRole("button", { name: "清空" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "算了" })).toBeInTheDocument();
  });

  it("点确认按钮调用 onConfirm", () => {
    const onConfirm = vi.fn();
    renderDialog({ onConfirm });
    fireEvent.click(screen.getByRole("button", { name: "确认" }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("点取消按钮调用 onCancel", () => {
    const onCancel = vi.fn();
    renderDialog({ onCancel });
    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("点 X 按钮调用 onCancel", () => {
    const onCancel = vi.fn();
    renderDialog({ onCancel });
    fireEvent.click(screen.getByLabelText("关闭"));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("按 Esc 调用 onCancel", () => {
    const onCancel = vi.fn();
    renderDialog({ onCancel });
    fireEvent.keyDown(document.body, { key: "Escape" });
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("点 overlay 遮罩调用 onCancel", () => {
    const onCancel = vi.fn();
    const { container } = renderDialog({ onCancel });
    const overlay = container.firstElementChild as HTMLElement;
    fireEvent.click(overlay);
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("点弹窗本体不关闭（事件不冒泡到 overlay）", () => {
    const onCancel = vi.fn();
    renderDialog({ onCancel });
    fireEvent.click(screen.getByText("确认操作"));
    expect(onCancel).not.toHaveBeenCalled();
  });

  it("loading=true 时所有关闭方式都禁用（包括确认按钮）", () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    renderDialog({ loading: true, onConfirm, onCancel });

    // 确认按钮禁用（disabled + onClick 不触发）
    fireEvent.click(screen.getByRole("button", { name: "确认" }));
    expect(onConfirm).not.toHaveBeenCalled();

    // 取消按钮禁用
    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    expect(onCancel).not.toHaveBeenCalled();

    // Esc 禁用
    fireEvent.keyDown(document.body, { key: "Escape" });
    expect(onCancel).not.toHaveBeenCalled();
  });

  it("danger=true 时确认按钮用红色主题", () => {
    renderDialog({ danger: true });
    const confirmBtn = screen.getByRole("button", { name: "确认" });
    // 危险态确认按钮带红色背景类
    expect(confirmBtn.className).toMatch(/bg-red-500/);
  });

  it("loading=true 时确认按钮显示 spinner", () => {
    renderDialog({ loading: true });
    const spinner = document.querySelector(".animate-spin");
    expect(spinner).toBeInTheDocument();
  });
});
