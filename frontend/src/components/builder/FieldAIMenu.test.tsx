import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { FieldAIMenu } from "./FieldAIMenu";

// mock 三个内联 AI 端点，断言按钮触发对应 action
const { mockOptimize, mockCheck, mockRewrite } = vi.hoisted(() => ({
  mockOptimize: vi.fn(),
  mockCheck: vi.fn(),
  mockRewrite: vi.fn(),
}));

vi.mock("../../api/builder", () => ({
  aiOptimize: (...args: unknown[]) => mockOptimize(...args),
  aiCheck: (...args: unknown[]) => mockCheck(...args),
  aiRewrite: (...args: unknown[]) => mockRewrite(...args),
}));

const DEFAULT_TEXT = "负责前端开发，优化首屏加载性能";

describe("FieldAIMenu", () => {
  beforeEach(() => {
    mockOptimize.mockReset();
    mockCheck.mockReset();
    mockRewrite.mockReset();
  });

  it("直接渲染优化/检查/改写三个操作按钮（不折叠）", () => {
    render(
      <FieldAIMenu
        resumeId={1}
        moduleType="work_experience"
        text={DEFAULT_TEXT}
        onApplyText={() => {}}
      />,
    );
    expect(screen.getByRole("button", { name: "优化此条内容" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "检查此条内容" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "按指令改写此条内容" })).toBeInTheDocument();
  });

  it("空文本时禁用操作按钮（调用方传 disabled）", () => {
    render(
      <FieldAIMenu resumeId={1} moduleType="work_experience" text="" disabled onApplyText={() => {}} />,
    );
    expect(screen.getByRole("button", { name: "优化此条内容" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "检查此条内容" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "按指令改写此条内容" })).toBeDisabled();
  });

  it("点击检查触发 aiCheck 并展示问题列表", async () => {
    mockCheck.mockResolvedValue({
      issues: [
        {
          severity: "high",
          category: "量化问题",
          description: "缺少数据支撑",
          field: "工作描述",
        },
      ],
    });
    render(
      <FieldAIMenu
        resumeId={1}
        moduleType="work_experience"
        text={DEFAULT_TEXT}
        onApplyText={() => {}}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "检查此条内容" }));

    await waitFor(() => {
      expect(mockCheck).toHaveBeenCalledWith(1, DEFAULT_TEXT, "work_experience");
    });
    expect(await screen.findByText("缺少数据支撑")).toBeInTheDocument();
  });

  it("点击优化触发 aiOptimize 并可回填结果", async () => {
    mockOptimize.mockResolvedValue({ optimized_text: "优化后的文本", original_text: DEFAULT_TEXT });
    const onApply = vi.fn();
    render(
      <FieldAIMenu resumeId={1} moduleType="work_experience" text={DEFAULT_TEXT} onApplyText={onApply} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "优化此条内容" }));

    await waitFor(() => {
      expect(mockOptimize).toHaveBeenCalledWith(1, DEFAULT_TEXT, "work_experience");
    });
    fireEvent.click(await screen.findByRole("button", { name: "使用 AI 结果" }));
    expect(onApply).toHaveBeenCalledWith("优化后的文本");
  });

  it("点击改写后输入指令触发 aiRewrite", async () => {
    mockRewrite.mockResolvedValue({ rewritten_text: "改写后的文本", original_text: DEFAULT_TEXT });
    render(
      <FieldAIMenu resumeId={1} moduleType="work_experience" text={DEFAULT_TEXT} onApplyText={() => {}} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "按指令改写此条内容" }));

    fireEvent.change(screen.getByLabelText("改写指令"), { target: { value: "更简洁专业" } });
    fireEvent.click(screen.getByRole("button", { name: "执行改写" }));

    await waitFor(() => {
      expect(mockRewrite).toHaveBeenCalledWith(1, DEFAULT_TEXT, "更简洁专业", "work_experience");
    });
  });
});
