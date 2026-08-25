import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import Citations from "./Citations";

describe("Citations", () => {
  it("renders source count and expandable content", () => {
    render(
      <Citations
        sources={[
          { text: "work history", section: "experience" },
          { text: "education", section: "education" },
        ]}
      />,
    );
    const buttons = screen.getAllByRole("button");
    expect(buttons).toHaveLength(1);
    fireEvent.click(buttons[0]);
    expect(screen.getByText("work history")).toBeTruthy();
    expect(screen.getAllByText("education")).toHaveLength(2);
  });

  it("renders nothing for missing or empty sources", () => {
    expect(render(<Citations />).container.innerHTML).toBe("");
    expect(render(<Citations sources={[{ text: "" }]} />).container.innerHTML).toBe("");
  });

  it("does not display percentages for missing, unknown, bm25, or rrf score kinds", () => {
    render(
      <Citations
        sources={[
          { text: "missing", score: 0.42 },
          { text: "unknown", score: 0.42, score_kind: "unknown" },
          { text: "bm25", score: 0.42, score_kind: "bm25" },
          { text: "rrf", score: 0.42, score_kind: "rrf" },
        ]}
      />,
    );
    fireEvent.click(screen.getAllByRole("button")[0]);
    expect(screen.queryByText(/42%/)).toBeNull();
    expect(screen.getAllByText("评分 0.42")).toHaveLength(4);
  });

  it("only displays percentage for dense and rerank scores within 0..1", () => {
    render(
      <Citations
        sources={[
          { text: "zero", score: 0, score_kind: "dense_similarity" },
          { text: "one", score: 1, score_kind: "rerank_relevance" },
          { text: "high", score: 1.01, score_kind: "dense_similarity" },
          { text: "negative", score: -0.01, score_kind: "rerank_relevance" },
        ]}
      />,
    );
    fireEvent.click(screen.getAllByRole("button")[0]);
    expect(screen.getAllByText(/相关度/)).toHaveLength(2);
    expect(screen.getByText("评分 1.01")).toBeTruthy();
    expect(screen.getByText("评分 -0.01")).toBeTruthy();
  });
});
