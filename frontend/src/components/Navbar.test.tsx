import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import Navbar from "./Navbar";

vi.mock("../context/AuthContext", () => ({
  useAuth: () => ({ user: { email: "test@example.com" }, logout: vi.fn() }),
}));

vi.mock("../context/ThemeContext", () => ({
  useTheme: () => ({ theme: "dark", toggleTheme: vi.fn() }),
}));

describe("Navbar 设计", () => {
  it("导航栏不使用 backdrop-blur 或半透明背景", () => {
    render(
      <MemoryRouter>
        <Navbar />
      </MemoryRouter>
    );
    const nav = screen.getByRole("navigation");
    expect(nav.className).not.toMatch(/backdrop-blur|bg-\[.*\]\/\d+/);
  });

  it("导航栏使用纯色背景", () => {
    render(
      <MemoryRouter>
        <Navbar />
      </MemoryRouter>
    );
    const nav = screen.getByRole("navigation");
    expect(nav.className).toMatch(/bg-\[var\(--color-bg\)\]/);
  });
});
