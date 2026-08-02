import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import Navbar from "./Navbar";

const mockLogout = vi.fn();

vi.mock("../context/AuthContext", () => ({
  useAuth: () => ({ user: { id: 1, username: "testuser", email: "test@example.com" }, logout: mockLogout }),
}));

describe("Navbar 设计", () => {
  it("导航栏使用毛玻璃半透明背景", () => {
    render(
      <MemoryRouter>
        <Navbar />
      </MemoryRouter>
    );
    const nav = screen.getByRole("navigation");
    expect(nav.className).toMatch(/backdrop-blur/);
    expect(nav.className).toMatch(/bg-white\/70/);
  });

  it("导航栏带底部 hairline 边框", () => {
    render(
      <MemoryRouter>
        <Navbar />
      </MemoryRouter>
    );
    const nav = screen.getByRole("navigation");
    expect(nav.className).toMatch(/border-b/);
  });
});

describe("Navbar 下拉菜单", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("点击用户名显示下拉菜单", () => {
    render(
      <MemoryRouter>
        <Navbar />
      </MemoryRouter>
    );
    const username = screen.getByText("testuser");
    fireEvent.click(username);
    
    expect(screen.getByText("修改密码")).toBeInTheDocument();
    expect(screen.getByText("重新绑定邮箱")).toBeInTheDocument();
    expect(screen.getByText("修改用户名")).toBeInTheDocument();
  });

  it("点击修改密码触发对应回调", async () => {
    render(
      <MemoryRouter>
        <Navbar />
      </MemoryRouter>
    );
    fireEvent.click(screen.getByText("testuser"));
    fireEvent.click(screen.getByText("修改密码"));
    
    await waitFor(() => {
      expect(screen.getByTestId("change-password-dialog")).toBeInTheDocument();
    });
  });

  it("点击重新绑定邮箱触发对应回调", async () => {
    render(
      <MemoryRouter>
        <Navbar />
      </MemoryRouter>
    );
    fireEvent.click(screen.getByText("testuser"));
    fireEvent.click(screen.getByText("重新绑定邮箱"));
    
    await waitFor(() => {
      expect(screen.getByTestId("change-email-dialog")).toBeInTheDocument();
    });
  });

  it("点击修改用户名触发对应回调", async () => {
    render(
      <MemoryRouter>
        <Navbar />
      </MemoryRouter>
    );
    fireEvent.click(screen.getByText("testuser"));
    fireEvent.click(screen.getByText("修改用户名"));
    
    await waitFor(() => {
      expect(screen.getByTestId("change-username-dialog")).toBeInTheDocument();
    });
  });

  it("点击退出按钮调用logout", async () => {
    render(
      <MemoryRouter>
        <Navbar />
      </MemoryRouter>
    );
    fireEvent.click(screen.getByText("退出"));
    expect(mockLogout).toHaveBeenCalledTimes(1);
  });
});
