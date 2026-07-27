import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import LoginPage from "./LoginPage";

// 把 useAuth mock 成 noop，让 LoginPage 能独立于 AuthContext 渲染
vi.mock("../context/AuthContext", () => ({
  useAuth: () => ({
    login: vi.fn(async () => {}),
    register: vi.fn(async () => {}),
  }),
}));

// ── Task 1.2 收尾：LoginPage 必须提供"忘记密码"入口 ──
// 修复前：LoginPage 登录表单没有"忘记密码"链接，用户一旦忘记密码无路可走
// 修复后：登录 tab 下提供"忘记密码？"链接，点击跳转到 /forgot-password

describe("LoginPage 忘记密码入口 (Task 1.2 收尾)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("登录 tab 下渲染 '忘记密码？' 链接", async () => {
    render(
      <MemoryRouter initialEntries={["/login"]}>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/forgot-password" element={<div>forgot page</div>} />
        </Routes>
      </MemoryRouter>
    );

    // 等待组件挂载动画完成
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /登 录/ })).toBeInTheDocument();
    });

    // 断言存在 "忘记密码？" 链接
    const link = screen.getByRole("link", { name: /忘记密码/ });
    expect(link).toBeInTheDocument();
    expect(link).toHaveAttribute("href", "/forgot-password");
  });

  it("注册 tab 下不渲染 '忘记密码？' 链接（避免误导）", async () => {
    render(
      <MemoryRouter initialEntries={["/login"]}>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/forgot-password" element={<div>forgot page</div>} />
        </Routes>
      </MemoryRouter>
    );

    // 切换到注册 tab
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /登 录/ })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: "注册" }));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /注 册/ })).toBeInTheDocument();
    });

    // 注册 tab 下不应有忘记密码链接
    expect(screen.queryByRole("link", { name: /忘记密码/ })).toBeNull();
  });

  it("点击 '忘记密码？' 链接导航到 /forgot-password", async () => {
    render(
      <MemoryRouter initialEntries={["/login"]}>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/forgot-password" element={<div>forgot password page</div>} />
        </Routes>
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByRole("link", { name: /忘记密码/ })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("link", { name: /忘记密码/ }));

    await waitFor(() => {
      expect(screen.getByText("forgot password page")).toBeInTheDocument();
    });
  });
});
