import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import ResumeListPage from "../ResumeListPage";

vi.mock("../../api/resumes", () => ({
  listResumes: vi.fn(async () => ({ items: [], total: 0 })),
  uploadResume: vi.fn(async () => ({
    id: 1,
    filename: "test.pdf",
    status: "processing",
  })),
  deleteResume: vi.fn(async () => undefined),
  getResume: vi.fn(async () => ({
    id: 1,
    filename: "test.pdf",
    parsed_text: "",
    chunk_count: 0,
    status: "ready",
    status_message: "",
    created_at: "2026-07-26",
  })),
  retryResume: vi.fn(async () => ({
    id: 1,
    filename: "test.pdf",
    status: "processing",
  })),
  generateIdempotencyKey: vi.fn(async () => "mock-hash-key"),
}));

vi.mock("../../components/AnalysisModal", () => ({
  default: () => <div data-testid="analysis-modal" />,
}));
vi.mock("../../components/ChunksModal", () => ({
  default: () => <div data-testid="chunks-modal" />,
}));
vi.mock("../../components/ResumeViewer", () => ({
  default: () => <div data-testid="resume-viewer" />,
}));
vi.mock("../../components/MatchJDModal", () => ({
  default: () => <div data-testid="match-jd-modal" />,
}));
vi.mock("../../components/MoreMenu", () => ({
  default: () => null,
}));
vi.mock("../../components/Toast", () => ({
  useToast: () => ({
    success: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
    warning: vi.fn(),
  }),
}));

import { listResumes } from "../../api/resumes";

function renderPage() {
  return render(
    <MemoryRouter>
      <ResumeListPage />
    </MemoryRouter>
  );
}

describe("ResumeListPage Minimalist Monochrome 设计", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(listResumes).mockResolvedValue({ items: [], total: 0 });
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  // ── 空状态 ──
  describe("空状态设计", () => {
    it("页面只有一个 h1（顶部栏，空状态不重复）", async () => {
      renderPage();
      await waitFor(() => expect(listResumes).toHaveBeenCalled());
      const h1s = screen.getAllByRole("heading", { level: 1 });
      expect(h1s.length).toBe(1);
      expect(h1s[0].textContent).toContain("我的简历");
    });

    it("空状态有 serif 大字号引导语", async () => {
      renderPage();
      await waitFor(() => expect(listResumes).toHaveBeenCalled());
      // 引导语用大字号，内容是"开始你的简历之旅"
      const heading = screen.getByText(/开始你的/i);
      expect(heading).toBeTruthy();
      expect(heading.tagName).toBe("P");
    });

    it("空状态上传按钮使用 mono-btn-primary 样式", async () => {
      renderPage();
      await waitFor(() => expect(listResumes).toHaveBeenCalled());
      const uploadBtns = screen.getAllByText(/上传简历/i);
      const emptyBtn = uploadBtns.find(btn => btn.className.includes("mono-btn-primary"));
      expect(emptyBtn).toBeTruthy();
    });

    it("空状态有厚水平线分隔（mono-rule）", async () => {
      renderPage();
      await waitFor(() => expect(listResumes).toHaveBeenCalled());
      const rules = document.querySelectorAll(".mono-rule");
      expect(rules.length).toBeGreaterThanOrEqual(1);
    });

    it("空状态不含 mono-rule-thin 细线", async () => {
      renderPage();
      await waitFor(() => expect(listResumes).toHaveBeenCalled());
      const thinRules = document.querySelectorAll(".mono-rule-thin");
      expect(thinRules.length).toBe(0);
    });

    it("所有标题不含渐变色", async () => {
      renderPage();
      await waitFor(() => expect(listResumes).toHaveBeenCalled());
      const headings = screen.getAllByRole("heading", { level: 1 });
      headings.forEach(h => {
        expect(h.className).not.toMatch(/gradient|from-|to-/);
      });
    });
  });

  // ── 顶部栏 ──
  describe("顶部栏设计", () => {
    it("顶部栏滚动时保持固定（sticky）", async () => {
      renderPage();
      await waitFor(() => expect(listResumes).toHaveBeenCalled());
      const h1 = screen.getByRole("heading", { level: 1 });
      const header = h1.closest("div[class*='sticky'], div[class*='fixed']");
      expect(header).toBeTruthy();
      expect(header!.className).toMatch(/sticky|fixed/);
    });

    it("顶部栏不使用半透明背景", async () => {
      renderPage();
      await waitFor(() => expect(listResumes).toHaveBeenCalled());
      const h1 = screen.getByRole("heading", { level: 1 });
      const header = h1.closest("div[class*='sticky'], div[class*='fixed']");
      expect(header).toBeTruthy();
      expect(header!.className).not.toMatch(/backdrop-blur|bg-\[.*\]\/\d+/);
    });
  });

  // ── 简历列表 ──
  describe("简历列表卡片设计", () => {
    const mockResume = {
      id: 1,
      filename: "resume-test.pdf",
      parsed_text: "content",
      chunk_count: 5,
      status: "ready",
      status_message: "",
      created_at: "2026-07-27T00:00:00Z",
    };

    beforeEach(() => {
      vi.mocked(listResumes).mockResolvedValue({ items: [mockResume], total: 1 });
    });

    it("简历卡片无圆角（rounded-none）", async () => {
      renderPage();
      await screen.findByText("resume-test.pdf");
      const card = screen.getByText("resume-test.pdf").closest("div[class*='border']");
      expect(card).toBeTruthy();
      // 卡片不应有 rounded 类
      const allCards = document.querySelectorAll("[data-testid='resume-card'], .mono-hover-border");
      if (allCards.length > 0) {
        allCards.forEach((c) => {
          expect(c.className).not.toMatch(/rounded-[a-z]+(?<!none)/);
        });
      }
    });

    it("简历卡片 hover 不改变背景色（无 mono-hover-inversion）", async () => {
      renderPage();
      await screen.findByText("resume-test.pdf");
      const cards = document.querySelectorAll(".mono-hover-inversion");
      expect(cards.length).toBe(0);
    });

    it("简历卡片 hover 只改变边框样式", async () => {
      renderPage();
      await screen.findByText("resume-test.pdf");
      const cards = document.querySelectorAll(".mono-hover-border");
      expect(cards.length).toBeGreaterThanOrEqual(1);
    });

    it("状态标签无渐变色和圆角", async () => {
      renderPage();
      await screen.findByText("就绪");
      const badge = screen.getByText("就绪");
      expect(badge.className).not.toMatch(/rounded-[a-z]+(?<!none)|gradient|from-/);
    });

    it("上传按钮使用 mono-btn-primary 样式", async () => {
      renderPage();
      await screen.findByText("resume-test.pdf");
      const uploadBtns = screen.getAllByText(/上传简历/i);
      const monoBtn = uploadBtns.find(btn => btn.className.includes("mono-btn-primary"));
      expect(monoBtn).toBeTruthy();
    });
  });
});
