import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, fireEvent, waitFor, screen, act } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import ForgotPasswordPage from "./ForgotPasswordPage";

// 默认 mock：forgotPassword 成功返回
const mockForgotPassword = vi.fn(async () => "若邮箱存在，重置链接已发送");

vi.mock("../api/auth", () => ({
  forgotPassword: (...args: unknown[]) => mockForgotPassword(...args),
}));

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
});

function renderPage() {
  return render(
    <MemoryRouter>
      <ForgotPasswordPage />
    </MemoryRouter>
  );
}

describe("ForgotPasswordPage (Task 1.2)", () => {
  it("渲染邮箱输入框、提交按钮、返回登录链接", () => {
    renderPage();
    expect(screen.getByPlaceholderText(/your@email.com|邮箱/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /发送|提交|重置/i })).toBeInTheDocument();
    expect(screen.getByText(/返回登录|回到登录/i)).toBeInTheDocument();
  });

  it("空邮箱提交时显示前端校验错误，不发请求", async () => {
    renderPage();
    const submitBtn = screen.getByRole("button", { name: /发送|提交|重置/i });
    await act(async () => {
      fireEvent.click(submitBtn);
    });
    await waitFor(() => {
      expect(screen.getByText(/请输入邮箱/i)).toBeInTheDocument();
    });
    expect(mockForgotPassword).not.toHaveBeenCalled();
  });

  it("非法邮箱格式前端拦截，不发请求", async () => {
    renderPage();
    const input = screen.getByPlaceholderText(/your@email.com|邮箱/i);
    const submitBtn = screen.getByRole("button", { name: /发送|提交|重置/i });

    await act(async () => {
      fireEvent.change(input, { target: { value: "not-an-email" } });
    });
    await act(async () => {
      fireEvent.click(submitBtn);
    });

    await waitFor(() => {
      expect(screen.getByText(/邮箱格式不合法|邮箱格式/i)).toBeInTheDocument();
    });
    expect(mockForgotPassword).not.toHaveBeenCalled();
  });

  it("合法邮箱提交后调用 forgotPassword 并显示成功提示", async () => {
    renderPage();
    const input = screen.getByPlaceholderText(/your@email.com|邮箱/i);
    const submitBtn = screen.getByRole("button", { name: /发送|提交|重置/i });

    await act(async () => {
      fireEvent.change(input, { target: { value: "user@example.com" } });
    });
    await act(async () => {
      fireEvent.click(submitBtn);
    });

    await waitFor(() => {
      expect(mockForgotPassword).toHaveBeenCalledWith("user@example.com");
    });
    await waitFor(() => {
      expect(screen.getByText(/若邮箱存在/i)).toBeInTheDocument();
    });
  });

  it("后端返回 422 时显示错误消息", async () => {
    mockForgotPassword.mockRejectedValueOnce(new Error("邮箱格式不合法"));
    renderPage();
    const input = screen.getByPlaceholderText(/your@email.com|邮箱/i);
    const submitBtn = screen.getByRole("button", { name: /发送|提交|重置/i });

    await act(async () => {
      fireEvent.change(input, { target: { value: "user@example.com" } });
    });
    await act(async () => {
      fireEvent.click(submitBtn);
    });

    await waitFor(() => {
      expect(screen.getByText(/邮箱格式不合法/i)).toBeInTheDocument();
    });
  });

  it("加载中按钮禁用，防止重复提交", async () => {
    // 让请求挂起，模拟加载中状态
    let resolveFn: (v: string) => void = () => {};
    mockForgotPassword.mockImplementationOnce(
      () => new Promise<string>((resolve) => { resolveFn = resolve; })
    );
    renderPage();
    const input = screen.getByPlaceholderText(/your@email.com|邮箱/i);
    const submitBtn = screen.getByRole("button", { name: /发送|提交|重置/i }) as HTMLButtonElement;

    await act(async () => {
      fireEvent.change(input, { target: { value: "user@example.com" } });
    });
    await act(async () => {
      fireEvent.click(submitBtn);
    });

    await waitFor(() => {
      expect(submitBtn.disabled).toBe(true);
    });
    resolveFn("若邮箱存在，重置链接已发送");
    await waitFor(() => {
      expect(submitBtn.disabled).toBe(false);
    });
  });
});
