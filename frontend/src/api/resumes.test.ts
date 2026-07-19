import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

vi.mock("./client", () => ({
  api: { post: vi.fn(), get: vi.fn(), delete: vi.fn() },
  refreshToken: vi.fn(),
  clearSessionAndRedirect: vi.fn(),
}));

import { api } from "./client";
import { analyzeResume, getChunks } from "./resumes";

beforeEach(() => {
  vi.mocked(api.post).mockReset();
  vi.mocked(api.get).mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("analyzeResume (Task 2 前端 API)", () => {
  it("POST /api/v1/resumes/{id}/analyze 带正确 body 和路径", async () => {
    vi.mocked(api.post).mockResolvedValue({
      resume_id: 42,
      analysis_type: "summary",
      analysis: "候选人精通 Python。",
    });

    const result = await analyzeResume(42, "summary");

    expect(api.post).toHaveBeenCalledWith("/api/v1/resumes/42/analyze", {
      analysis_type: "summary",
    });
    expect(result.resume_id).toBe(42);
    expect(result.analysis_type).toBe("summary");
    expect(result.analysis).toContain("Python");
  });

  it("skills 类型透传 analysis_type", async () => {
    vi.mocked(api.post).mockResolvedValue({
      resume_id: 1,
      analysis_type: "skills",
      analysis: "Python, FastAPI",
    });

    await analyzeResume(1, "skills");

    expect(api.post).toHaveBeenCalledWith("/api/v1/resumes/1/analyze", {
      analysis_type: "skills",
    });
  });

  it("experience 类型透传 analysis_type", async () => {
    vi.mocked(api.post).mockResolvedValue({
      resume_id: 7,
      analysis_type: "experience",
      analysis: "A 公司 后端 2022-2024",
    });

    await analyzeResume(7, "experience");

    expect(api.post).toHaveBeenCalledWith("/api/v1/resumes/7/analyze", {
      analysis_type: "experience",
    });
  });

  it("后端返回 409 时抛 Error（简历未就绪）", async () => {
    vi.mocked(api.post).mockRejectedValue(new Error("简历未就绪（当前状态: processing）"));

    await expect(analyzeResume(99, "summary")).rejects.toThrow("简历未就绪");
  });

  it("后端返回 404 时抛 Error（简历不存在）", async () => {
    vi.mocked(api.post).mockRejectedValue(new Error("简历不存在或无权访问"));

    await expect(analyzeResume(99999, "summary")).rejects.toThrow("简历不存在");
  });
});

describe("getChunks (Task 3 前端 API)", () => {
  it("GET /api/v1/resumes/{id}/chunks 带正确路径", async () => {
    vi.mocked(api.get).mockResolvedValue({
      resume_id: 42,
      total: 2,
      chunks: [
        {
          chunk_index: 0,
          section: "基本信息",
          text: "姓名：张三",
          start_char: 0,
          end_char: 5,
        },
        {
          chunk_index: 1,
          section: "技能",
          text: "Python, FastAPI",
          start_char: 5,
          end_char: 20,
        },
      ],
    });

    const result = await getChunks(42);

    expect(api.get).toHaveBeenCalledWith("/api/v1/resumes/42/chunks");
    expect(result.resume_id).toBe(42);
    expect(result.total).toBe(2);
    expect(result.chunks).toHaveLength(2);
    expect(result.chunks[0].chunk_index).toBe(0);
    expect(result.chunks[0].section).toBe("基本信息");
    expect(result.chunks[1].text).toContain("Python");
  });

  it("空 chunks 列表（total=0）正常返回", async () => {
    vi.mocked(api.get).mockResolvedValue({
      resume_id: 7,
      total: 0,
      chunks: [],
    });

    const result = await getChunks(7);

    expect(api.get).toHaveBeenCalledWith("/api/v1/resumes/7/chunks");
    expect(result.total).toBe(0);
    expect(result.chunks).toEqual([]);
  });

  it("后端返回 409 时抛 Error（简历未就绪）", async () => {
    vi.mocked(api.get).mockRejectedValue(new Error("简历未就绪（当前状态: processing）"));

    await expect(getChunks(99)).rejects.toThrow("简历未就绪");
  });

  it("后端返回 404 时抛 Error（简历不存在）", async () => {
    vi.mocked(api.get).mockRejectedValue(new Error("简历不存在"));

    await expect(getChunks(99999)).rejects.toThrow("简历不存在");
  });
});
