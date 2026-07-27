import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, fireEvent, waitFor, screen, act } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import ResetPasswordPage from "./ResetPasswordPage";

const mockResetPassword = vi.fn(async () => "密码已重置，请使用新密码登录");

vi.mock("../api/auth", () => ({
  resetPassword: (...args: unknown[]) => mockResetPassword(...args),
}));

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
});

// 用 Routes 包一层让 ResetPasswordPage 能从 useSearchParams 读取 query string
function renderPage(path = "/reset-password?token=valid-token-abc") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/reset-password" element={<ResetPasswordPage />} />
        <Route path="/login" element={<div>登录页</div>} />
        <Route path="/forgot-password" element={<div>忘记密码页</div>} />
      </Routes>
    </MemoryRouter>
  );
}

describe("ResetPasswordPage (Task 1.2)", () => {
  it("有 token 时渲染新密码 + 确认密码输入框 + 提交按钮", () => {
    renderPage();
    // 用精确匹配避免 "新密码" 同时匹配 "确认新密码"
    expect(screen.getByLabelText(/^新密码$/)).toBeInTheDocument();
    expect(screen.getByLabelText(/^确认新密码$/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /重置|提交/i })).toBeInTheDocument();
  });

  it("无 token 时显示错误提示 + 重新申请入口（链接到 /forgot-password）", () => {
    renderPage("/reset-password");
    // 用 heading 精确匹配错误标题，避免 "无效" 同时匹配标题和正文
    expect(screen.getByRole("heading", { name: /链接无效/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /重新申请/i })).toBeInTheDocument();
  });

  it("新密码少于 8 位时显示校验错误，不发请求", async () => {
    renderPage();
    const newPwdInput = screen.getByLabelText(/^新密码$/);
    const submitBtn = screen.getByRole("button", { name: /重置|提交/i });

    await act(async () => {
      fireEvent.change(newPwdInput, { target: { value: "short1" } });
    });
    await act(async () => {
      fireEvent.click(submitBtn);
    });

    await waitFor(() => {
      expect(screen.getByText(/至少8位/i)).toBeInTheDocument();
    });
    expect(mockResetPassword).not.toHaveBeenCalled();
  });

  it("两次密码不一致时显示校验错误，不发请求", async () => {
    renderPage();
    const newPwdInput = screen.getByLabelText(/^新密码$/i);
    const confirmInput = screen.getByLabelText(/确认新密码/i);
    const submitBtn = screen.getByRole("button", { name: /重置|提交/i });

    await act(async () => {
      fireEvent.change(newPwdInput, { target: { value: "NewPass123!" } });
      fireEvent.change(confirmInput, { target: { value: "Different123!" } });
    });
    await act(async () => {
      fireEvent.click(submitBtn);
    });

    await waitFor(() => {
      expect(screen.getByText(/两次密码不一致/i)).toBeInTheDocument();
    });
    expect(mockResetPassword).not.toHaveBeenCalled();
  });

  it("密码缺少数字时显示校验错误（前端强度校验）", async () => {
    renderPage();
    const newPwdInput = screen.getByLabelText(/^新密码$/i);
    const confirmInput = screen.getByLabelText(/确认新密码/i);
    const submitBtn = screen.getByRole("button", { name: /重置|提交/i });

    await act(async () => {
      fireEvent.change(newPwdInput, { target: { value: "NoDigitHere!" } });
      fireEvent.change(confirmInput, { target: { value: "NoDigitHere!" } });
    });
    await act(async () => {
      fireEvent.click(submitBtn);
    });

    await waitFor(() => {
      expect(screen.getByText(/数字/i)).toBeInTheDocument();
    });
  });

  it("合法输入提交后调用 resetPassword(token, new_password) 并跳转 /login", async () => {
    renderPage();
    const newPwdInput = screen.getByLabelText(/^新密码$/i);
    const confirmInput = screen.getByLabelText(/确认新密码/i);
    const submitBtn = screen.getByRole("button", { name: /重置|提交/i });

    await act(async () => {
      fireEvent.change(newPwdInput, { target: { value: "NewPass123!" } });
      fireEvent.change(confirmInput, { target: { value: "NewPass123!" } });
    });
    await act(async () => {
      fireEvent.click(submitBtn);
    });

    await waitFor(() => {
      expect(mockResetPassword).toHaveBeenCalledWith("valid-token-abc", "NewPass123!");
    });
    // 跳转后渲染登录页
    await waitFor(() => {
      expect(screen.getByText("登录页")).toBeInTheDocument();
    });
  });

  it("后端 400（token 无效）时显示错误 + 重新申请入口", async () => {
    mockResetPassword.mockRejectedValueOnce(new Error("无效或过期的重置凭证"));
    renderPage();
    const newPwdInput = screen.getByLabelText(/^新密码$/i);
    const confirmInput = screen.getByLabelText(/确认新密码/i);
    const submitBtn = screen.getByRole("button", { name: /重置|提交/i });

    await act(async () => {
      fireEvent.change(newPwdInput, { target: { value: "NewPass123!" } });
      fireEvent.change(confirmInput, { target: { value: "NewPass123!" } });
    });
    await act(async () => {
      fireEvent.click(submitBtn);
    });

    await waitFor(() => {
      expect(screen.getByText(/无效或过期的重置凭证/i)).toBeInTheDocument();
    });
    expect(screen.getByText(/重新申请|重新获取/i)).toBeInTheDocument();
  });

  it("加载中按钮禁用，防止重复提交", async () => {
    let resolveFn: (v: string) => void = () => {};
    mockResetPassword.mockImplementationOnce(
      () => new Promise<string>((resolve) => { resolveFn = resolve; })
    );
    renderPage();
    const newPwdInput = screen.getByLabelText(/^新密码$/i);
    const confirmInput = screen.getByLabelText(/确认新密码/i);
    const submitBtn = screen.getByRole("button", { name: /重置|提交/i }) as HTMLButtonElement;

    await act(async () => {
      fireEvent.change(newPwdInput, { target: { value: "NewPass123!" } });
      fireEvent.change(confirmInput, { target: { value: "NewPass123!" } });
    });
    await act(async () => {
      fireEvent.click(submitBtn);
    });

    await waitFor(() => {
      expect(submitBtn.disabled).toBe(true);
    });
    resolveFn("密码已重置");
    await waitFor(() => {
      expect(submitBtn.disabled).toBe(false);
    });
  });
});
