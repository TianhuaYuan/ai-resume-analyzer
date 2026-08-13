import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { CompareSelectDialog } from "./CompareSelectDialog";

vi.mock("../api/resumes", () => ({
  listResumes: vi.fn(async () => ({
    items: [
      { id: 7, filename: "当前简历", status: "draft", chunk_count: 0 },
      { id: 8, filename: "另一份简历", status: "ready", chunk_count: 2 },
    ],
  })),
}));

describe("CompareSelectDialog", () => {
  it("allows selecting one additional resume because the current resume is the baseline", async () => {
    const onConfirm = vi.fn();
    render(
      <CompareSelectDialog
        open
        currentResumeId={7}
        onConfirm={onConfirm}
        onCancel={() => undefined}
      />,
    );

    await waitFor(() => expect(screen.getByText("另一份简历")).toBeInTheDocument());
    fireEvent.click(screen.getByText("另一份简历"));
    fireEvent.click(screen.getByRole("button", { name: "确认" }));
    expect(onConfirm).toHaveBeenCalledWith([8]);
  });
});
