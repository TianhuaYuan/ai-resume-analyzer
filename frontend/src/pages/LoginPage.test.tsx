import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import LoginPage from "./LoginPage";

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

// 默认 mock：login / register 都是 noop
const mockLogin = vi.fn(async () => {});
const mockRegister = vi.fn(async () => {});

vi.mock("../context/AuthContext", () => ({
  useAuth: () => ({
    login: mockLogin,
    register: mockRegister,
  }),
}));

function renderLogin() {
  return render(
    <MemoryRouter initialEntries={["/login"]}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/forgot-password" element={<div>forgot password page</div>} />
        <Route path="/" element={<div>home page</div>} />
      </Routes>
    </MemoryRouter>
  );
}

describe("LoginPage 重新设计", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("登录表单渲染提交按钮", async () => {
    renderLogin();
    await waitFor(() => {
      expect(screen.getByTestId("submit-btn")).toBeInTheDocument();
    });
  });

  it("登录表单渲染 '忘记密码？' 链接，点击导航到 /forgot-password", async () => {
    renderLogin();
    await waitFor(() => {
      expect(screen.getByText(/忘记密码/)).toBeInTheDocument();
    });
    fireEvent.click(screen.getByText(/忘记密码/));
    await waitFor(() => {
      expect(screen.getByText("forgot password page")).toBeInTheDocument();
    });
  });

  it("点击 '注册' 切换到注册表单", async () => {
    renderLogin();
    await waitFor(() => {
      expect(screen.getByText(/注册/i)).toBeInTheDocument();
    });
    fireEvent.click(screen.getByText(/注册/i));
    // 注册表单应有用户名输入框
    await waitFor(() => {
      expect(screen.getByPlaceholderText(/至少2个字符/)).toBeInTheDocument();
    });
  });

  it("注册表单不显示 '忘记密码？' 链接", async () => {
    renderLogin();
    // 先切换到注册
    await waitFor(() => {
      expect(screen.getByText(/注册/i)).toBeInTheDocument();
    });
    fireEvent.click(screen.getByText(/注册/i));
    await waitFor(() => {
      expect(screen.getByPlaceholderText(/至少2个字符/)).toBeInTheDocument();
    });
    // 注册表单下不应有忘记密码
    expect(screen.queryByText(/忘记密码/)).toBeNull();
  });

  it("注册表单渲染注册提交按钮", async () => {
    renderLogin();
    await waitFor(() => {
      expect(screen.getByText(/注册/i)).toBeInTheDocument();
    });
    fireEvent.click(screen.getByText(/注册/i));
    await waitFor(() => {
      expect(screen.getByTestId("register-submit-btn")).toBeInTheDocument();
    });
  });

  it("注册表单有 '返回登录' 链接，点击切回登录", async () => {
    renderLogin();
    // 切换到注册
    await waitFor(() => {
      expect(screen.getByText(/注册/i)).toBeInTheDocument();
    });
    fireEvent.click(screen.getByText(/注册/i));
    await waitFor(() => {
      expect(screen.getByPlaceholderText(/至少2个字符/)).toBeInTheDocument();
    });
    // 点击返回登录
    const backLink = screen.getByText(/返回登录/i);
    fireEvent.click(backLink);
    await waitFor(() => {
      expect(screen.getByTestId("submit-btn")).toBeInTheDocument();
    });
  });

  it("注册成功后调用 login 接口并跳转到首页（自动登录）", async () => {
    renderLogin();
    // 切换到注册
    await waitFor(() => {
      expect(screen.getByText(/注册/i)).toBeInTheDocument();
    });
    fireEvent.click(screen.getByText(/注册/i));
    await waitFor(() => {
      expect(screen.getByPlaceholderText(/至少2个字符/)).toBeInTheDocument();
    });
    // 填写表单
    fireEvent.change(screen.getByPlaceholderText(/至少2个字符/), {
      target: { value: "newuser" },
    });
    fireEvent.change(screen.getByPlaceholderText(/your@email.com/), {
      target: { value: "newuser@test.com" },
    });
    fireEvent.change(screen.getByPlaceholderText(/至少8位/), {
      target: { value: "Password123" },
    });
    fireEvent.change(screen.getByPlaceholderText(/再输一遍/), {
      target: { value: "Password123" },
    });
    // 填写验证码
    fireEvent.change(screen.getByPlaceholderText(/6位数字/), {
      target: { value: "123456" },
    });
    // 提交
    fireEvent.click(screen.getByTestId("register-submit-btn"));
    // 应先调用 register（含 verification_code）
    await waitFor(() => {
      expect(mockRegister).toHaveBeenCalledWith(
        "newuser",
        "newuser@test.com",
        "Password123",
        "Password123",
        "123456"
      );
    });
    // register 成功后应自动调用 login 完成登录
    await waitFor(() => {
      expect(mockLogin).toHaveBeenCalledWith("newuser@test.com", "Password123");
    });
    // 登录成功后应跳转到首页
    await waitFor(() => {
      expect(screen.getByText("home page")).toBeInTheDocument();
    });
  });

  it("注册页标题为「创建账号」（全中文化）", async () => {
    renderLogin();
    await waitFor(() => {
      expect(screen.getByText(/注册/i)).toBeInTheDocument();
    });
    fireEvent.click(screen.getByText(/注册/i));
    await waitFor(() => {
      expect(screen.getByText("创建账号")).toBeInTheDocument();
    });
  });

  it("注册页图标使用 favicon.svg", async () => {
    renderLogin();
    await waitFor(() => {
      expect(screen.getByText(/注册/i)).toBeInTheDocument();
    });
    fireEvent.click(screen.getByText(/注册/i));
    await waitFor(() => {
      const icon = document.querySelector('img[alt*="logo"], img[src*="favicon"]');
      expect(icon).toBeInTheDocument();
    });
  });
});
