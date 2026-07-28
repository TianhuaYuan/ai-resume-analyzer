import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { SignInCard2 } from "./ui/sign-in-card-2";

// Mock framer-motion：jsdom 环境下 motion 组件渲染为原生元素
vi.mock("framer-motion", () => ({
  motion: {
    div: ({ children, ...props }: React.ComponentProps<"div">) => (
      <div {...props}>{children}</div>
    ),
    button: ({ children, ...props }: React.ComponentProps<"button">) => (
      <button {...props}>{children}</button>
    ),
    span: ({ children, ...props }: React.ComponentProps<"span">) => (
      <span {...props}>{children}</span>
    ),
    h1: ({ children, ...props }: React.ComponentProps<"h1">) => (
      <h1 {...props}>{children}</h1>
    ),
    p: ({ children, ...props }: React.ComponentProps<"p">) => (
      <p {...props}>{children}</p>
    ),
  },
  AnimatePresence: ({ children }: { children: React.ReactNode }) => (
    <>{children}</>
  ),
  useMotionValue: () => ({ get: () => 0, set: () => {} }),
  useTransform: () => ({ get: () => 0 }),
}));

function renderCard(props: Partial<React.ComponentProps<typeof SignInCard2>> = {}) {
  const defaultProps = {
    email: "",
    password: "",
    onEmailChange: vi.fn(),
    onPasswordChange: vi.fn(),
    onSubmit: vi.fn(),
    onForgotPassword: vi.fn(),
    onSignUp: vi.fn(),
  };
  return render(<SignInCard2 {...defaultProps} {...props} />);
}

describe("SignInCard2 登录卡片组件", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("渲染邮箱输入框", () => {
    renderCard();
    expect(screen.getByPlaceholderText(/email/i)).toBeInTheDocument();
  });

  it("渲染密码输入框", () => {
    renderCard();
    expect(screen.getByPlaceholderText(/password/i)).toBeInTheDocument();
  });

  it("输入邮箱触发 onEmailChange", () => {
    const onEmailChange = vi.fn();
    renderCard({ onEmailChange });
    fireEvent.change(screen.getByPlaceholderText(/email/i), {
      target: { value: "test@example.com" },
    });
    expect(onEmailChange).toHaveBeenCalledWith("test@example.com");
  });

  it("输入密码触发 onPasswordChange", () => {
    const onPasswordChange = vi.fn();
    renderCard({ onPasswordChange });
    fireEvent.change(screen.getByPlaceholderText(/password/i), {
      target: { value: "secret123" },
    });
    expect(onPasswordChange).toHaveBeenCalledWith("secret123");
  });

  it("点击眼睛图标切换密码可见性", () => {
    renderCard();
    const passwordInput = screen.getByPlaceholderText(/password/i);
    expect(passwordInput).toHaveAttribute("type", "password");

    // 点击切换按钮（眼睛图标）
    const toggleBtn = screen.getByRole("button", { name: /toggle password/i }) ||
      passwordInput.parentElement?.querySelector("[data-testid='password-toggle']");
    if (toggleBtn) {
      fireEvent.click(toggleBtn);
      expect(passwordInput).toHaveAttribute("type", "text");
    }
  });

  it("渲染 '忘记密码？' 链接并触发 onForgotPassword", () => {
    const onForgotPassword = vi.fn();
    renderCard({ onForgotPassword });
    const link = screen.getByText(/忘记密码/i);
    expect(link).toBeInTheDocument();
    fireEvent.click(link);
    expect(onForgotPassword).toHaveBeenCalled();
  });

  it("提交表单触发 onSubmit", () => {
    const onSubmit = vi.fn();
    renderCard({ onSubmit });
    const form = screen.getByPlaceholderText(/email/i).closest("form");
    expect(form).toBeInTheDocument();
    if (form) {
      fireEvent.submit(form);
      expect(onSubmit).toHaveBeenCalled();
    }
  });

  it("渲染 '记住我' 复选框", () => {
    renderCard();
    const checkbox = screen.getByRole("checkbox", { name: /remember/i }) ||
      screen.getByLabelText(/remember/i);
    expect(checkbox).toBeInTheDocument();
  });

  it("不渲染 Google 登录按钮", () => {
    renderCard();
    expect(screen.queryByText(/google/i)).not.toBeInTheDocument();
  });

  it("isLoading=true 时禁用提交按钮", () => {
    renderCard({ isLoading: true });
    const submitBtn = screen.getByTestId("submit-btn");
    expect(submitBtn).toBeDisabled();
  });

  it("渲染 'Sign up' 链接并触发 onSignUp", () => {
    const onSignUp = vi.fn();
    renderCard({ onSignUp });
    const link = screen.getByText(/sign up/i);
    expect(link).toBeInTheDocument();
    fireEvent.click(link);
    expect(onSignUp).toHaveBeenCalled();
  });
});
