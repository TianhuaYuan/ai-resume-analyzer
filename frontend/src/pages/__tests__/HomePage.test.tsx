import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import HomePage from "../HomePage";

const mockNavigate = vi.fn();
const { mockUseAuth } = vi.hoisted(() => ({ mockUseAuth: vi.fn() }));

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return { ...actual, useNavigate: () => mockNavigate };
});

vi.mock("../../api/resumes", () => ({
  listResumes: vi.fn(),
  uploadResume: vi.fn(),
  generateIdempotencyKey: vi.fn(),
}));

vi.mock("../../api/builder", () => ({
  createBuilderResume: vi.fn(),
}));

vi.mock("../../api/analytics", () => ({
  trackEvent: vi.fn(),
  getCtaSource: vi.fn(),
}));

vi.mock("../../components/Toast", () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn() }),
}));

// HomePage 依赖 LandingNav，两者都使用 AuthContext/ThemeContext
vi.mock("../../context/AuthContext", () => ({
  useAuth: () => mockUseAuth(),
}));

vi.mock("../../context/ThemeContext", () => ({
  useTheme: () => ({ theme: "light", toggleTheme: vi.fn(), textScale: 1, setTextScale: vi.fn() }),
}));

// LandingNav 挂载时轮询 getQuota，避免真实请求
vi.mock("../../api/qa", () => ({
  getQuota: vi.fn(async () => ({
    enabled: false,
    used: 0,
    limit: 0,
    remaining: 0,
    reset_at: null,
  })),
}));

beforeEach(() => {
  vi.clearAllMocks();
  mockUseAuth.mockReturnValue({
    user: null,
    logout: vi.fn(),
    login: vi.fn(),
    register: vi.fn(),
    sendCode: vi.fn(),
    updateUser: vi.fn(),
    loading: false,
    sessionDialog: null,
    handleSessionGoLogin: vi.fn(),
  });
});

describe("HomePage 渲染", () => {
  it("渲染 Hero 标题与副标题", () => {
    render(<MemoryRouter><HomePage /></MemoryRouter>);
    // P0 重设计后 h1 含品牌渐变强调行，用正则匹配
    expect(screen.getByRole("heading", { level: 1, name: /拿下心仪 offer/ })).toBeInTheDocument();
    expect(screen.getByText(/一站式 AI 求职助手/)).toBeInTheDocument();
  });

  it("未登录时显示「开始使用」CTA", () => {
    render(<MemoryRouter><HomePage /></MemoryRouter>);
    expect(screen.getByText("开始使用")).toBeInTheDocument();
  });

  it("已登录时显示「我的简历」CTA 并跳转 /resumes", () => {
    mockUseAuth.mockReturnValue({
      user: { id: 1, username: "tester", email: "t@test.com", is_admin: false },
      logout: vi.fn(),
      login: vi.fn(),
      register: vi.fn(),
      sendCode: vi.fn(),
      updateUser: vi.fn(),
      loading: false,
      sessionDialog: null,
      handleSessionGoLogin: vi.fn(),
    });
    render(<MemoryRouter><HomePage /></MemoryRouter>);

    const btn = screen.getByText("我的简历");
    fireEvent.click(btn);
    expect(mockNavigate).toHaveBeenCalledWith("/resumes");
  });

  it("渲染功能简介卡片", () => {
    render(<MemoryRouter><HomePage /></MemoryRouter>);
    expect(screen.getByText("一站式求职，从简历开始")).toBeInTheDocument();
    expect(screen.getByText("AI 智能对话")).toBeInTheDocument();
    expect(screen.getByText("专业简历编辑器")).toBeInTheDocument();
    expect(screen.getByText("求职全程护航")).toBeInTheDocument();
  });
});
