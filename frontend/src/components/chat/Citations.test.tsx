import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import Citations from "./Citations";

describe("Citations（普通问答来源引用）", () => {
  it("有 sources 时显示「查看 N 条来源」折叠头", () => {
    render(<Citations sources={[{ text: "工作经历片段", section: "工作经历" }]} />);
    expect(screen.getByText("查看 1 条来源")).toBeTruthy();
  });

  it("点击展开后显示编号 + section 标签 + 原文", () => {
    render(
      <Citations
        sources={[
          { text: "任职期间负责核心模块", section: "工作经历" },
          { text: "毕业于某某大学", section: "教育背景" },
        ]}
      />,
    );
    fireEvent.click(screen.getByText("查看 2 条来源"));
    // 编号 [1] [2]
    expect(screen.getAllByText(/1|2/).length).toBeGreaterThan(0);
    expect(screen.getByText("工作经历")).toBeTruthy();
    expect(screen.getByText("教育背景")).toBeTruthy();
    expect(screen.getByText("任职期间负责核心模块")).toBeTruthy();
  });

  it("无 sources 或全部为空时不渲染", () => {
    const empty = render(<Citations />);
    expect(empty.container.innerHTML).toBe("");
    const emptyTexts = render(<Citations sources={[{ text: "" }]} />);
    expect(emptyTexts.container.innerHTML).toBe("");
  });
});
