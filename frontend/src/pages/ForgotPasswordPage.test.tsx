import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, fireEvent, waitFor, screen, act } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import ForgotPasswordPage from "./ForgotPasswordPage";

const mockForgotPassword = vi.fn(async () => "密码已重置，请使用新密码登录");
const mockSendCode = vi.fn(async () => "验证码已发送");
const mockNavigate = vi.fn();

vi.mock("../api/auth", () => ({
  forgotPassword: (...args: unknown[]) => mockForgotPassword(...args),
  sendCode: (...args: unknown[]) => mockSendCode(...args),
}));

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

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

async function fillForm({
  email = "user@example.com",
  code = "123456",
  newPassword = "NewPass123!",
  confirmPassword = "NewPass123!",
}: Partial<{
  email: string;
  code: string;
  newPassword: string;
  confirmPassword: string;
}> = {}) {
  const emailInput = screen.getByLabelText(/^邮箱$/);
  const codeInput = screen.getByLabelText(/^验证码$/);
  const newPwdInput = screen.getByLabelText(/^新密码$/);
  const confirmPwdInput = screen.getByLabelText(/^确认新密码$/);

  await act(async () => {
    fireEvent.change(emailInput, { target: { value: email } });
  });
  await act(async () => {
    fireEvent.change(codeInput, { target: { value: code } });
  });
  await act(async () => {
    fireEvent.change(newPwdInput, { target: { value: newPassword } });
  });
  await act(async () => {
    fireEvent.change(confirmPwdInput, { target: { value: confirmPassword } });
  });
}

describe("ForgotPasswordPage（新流程：验证码+新密码直接重置）", () => {
  it("渲染所有输入框、发送按钮、提交按钮、返回链接", () => {
    renderPage();
    expect(screen.getByLabelText(/^邮箱$/)).toBeInTheDocument();
    expect(screen.getByLabelText(/^验证码$/)).toBeInTheDocument();
    expect(screen.getByLabelText(/^新密码$/)).toBeInTheDocument();
    expect(screen.getByLabelText(/^确认新密码$/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /发送/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /重置密码/ })).toBeInTheDocument();
    expect(screen.getByText(/返回登录/)).toBeInTheDocument();
  });

  it("空邮箱提交时显示前端校验错误", async () => {
    const { container } = renderPage();
    const form = container.querySelector("form")!;
    await act(async () => {
      fireEvent.submit(form);
    });
    await waitFor(() => {
      expect(screen.getByText(/请输入邮箱/)).toBeInTheDocument();
    }, { timeout: 3000 });
    expect(mockForgotPassword).not.toHaveBeenCalled();
  });

  it("非法邮箱格式前端拦截", async () => {
    const { container } = renderPage();
    const emailInput = screen.getByLabelText(/^邮箱$/);
    await act(async () => {
      fireEvent.change(emailInput, { target: { value: "not-an-email" } });
    });
    const form = container.querySelector("form")!;
    await act(async () => {
      fireEvent.submit(form);
    });
    await waitFor(() => {
      expect(screen.getByText(/邮箱格式不合法/)).toBeInTheDocument();
    }, { timeout: 3000 });
    expect(mockForgotPassword).not.toHaveBeenCalled();
  });

  it("未输入验证码提交时显示错误", async () => {
    const { container } = renderPage();
    await act(async () => {
      fireEvent.change(screen.getByLabelText(/^邮箱$/), { target: { value: "user@example.com" } });
    });
    const form = container.querySelector("form")!;
    await act(async () => {
      fireEvent.submit(form);
    });
    await waitFor(() => {
      expect(screen.getByText(/请输入6位验证码/)).toBeInTheDocument();
    }, { timeout: 5000 });
    expect(mockForgotPassword).not.toHaveBeenCalled();
  });

  it("新密码过短时前端拦截", async () => {
    const { container } = renderPage();
    await fillForm({ newPassword: "short1", confirmPassword: "short1" });
    const form = container.querySelector("form")!;
    await act(async () => {
      fireEvent.submit(form);
    });
    await waitFor(() => {
      expect(screen.getByText(/新密码至少8位/)).toBeInTheDocument();
    }, { timeout: 3000 });
    expect(mockForgotPassword).not.toHaveBeenCalled();
  });

  it("两次密码不一致前端拦截", async () => {
    const { container } = renderPage();
    await fillForm({ newPassword: "NewPass123!", confirmPassword: "Different123!" });
    const form = container.querySelector("form")!;
    await act(async () => {
      fireEvent.submit(form);
    });
    await waitFor(() => {
      expect(screen.getByText(/两次密码不一致/)).toBeInTheDocument();
    }, { timeout: 3000 });
    expect(mockForgotPassword).not.toHaveBeenCalled();
  });

  it("合法表单提交后调用 forgotPassword 传 email+code+newPassword", async () => {
    const { container } = renderPage();
    await fillForm();
    const form = container.querySelector("form")!;
    await act(async () => {
      fireEvent.submit(form);
    });
    await waitFor(() => {
      expect(mockForgotPassword).toHaveBeenCalledWith(
        "user@example.com",
        "123456",
        "NewPass123!"
      );
    }, { timeout: 3000 });
    await waitFor(() => {
      expect(screen.getByText(/密码已重置/)).toBeInTheDocument();
    }, { timeout: 3000 });
  });

  it("成功后跳转到登录页并带上 email", async () => {
    const { container } = renderPage();
    await fillForm();
    const form = container.querySelector("form")!;
    await act(async () => {
      fireEvent.submit(form);
    });
    await waitFor(() => {
      expect(mockForgotPassword).toHaveBeenCalled();
    });
    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith("/login", { state: { email: "user@example.com" } });
    }, { timeout: 5000 });
  });

  it("点击发送验证码按钮调用 sendCode", async () => {
    renderPage();
    await act(async () => {
      fireEvent.change(screen.getByLabelText(/^邮箱$/), { target: { value: "user@example.com" } });
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /^发送$/ }));
    });
    await waitFor(() => {
      expect(mockSendCode).toHaveBeenCalledWith("user@example.com");
    });
    await waitFor(() => {
      expect(screen.getByText(/验证码已发送/)).toBeInTheDocument();
    });
  });

  it("发送验证码时按钮禁用防止重复发送", async () => {
    let resolveFn: (v: string) => void = () => {};
    mockSendCode.mockImplementationOnce(
      () => new Promise<string>((resolve) => { resolveFn = resolve; })
    );
    renderPage();
    await act(async () => {
      fireEvent.change(screen.getByLabelText(/^邮箱$/), { target: { value: "user@example.com" } });
    });
    const sendCodeBtn = screen.getByRole("button", { name: /^发送$/ }) as HTMLButtonElement;
    await act(async () => {
      fireEvent.click(sendCodeBtn);
    });
    await waitFor(() => {
      expect(sendCodeBtn.disabled).toBe(true);
    });
    resolveFn("验证码已发送");
    await waitFor(() => {
      expect(sendCodeBtn.disabled).toBe(true);
      expect(sendCodeBtn.textContent).toMatch(/\d+s/);
    });
  });
});