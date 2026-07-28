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

// 把 useAuth mock 成 noop，让 LoginPage 能独立于 AuthContext 渲染
vi.mock("../context/AuthContext", () => ({
  useAuth: () => ({
    login: vi.fn(async () => {}),
    register: vi.fn(async () => {}),
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
});
