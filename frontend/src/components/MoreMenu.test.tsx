import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import MoreMenu, { type MoreMenuItem } from "./MoreMenu";

const items: MoreMenuItem[] = [
  { key: "preview", label: "预览", onClick: vi.fn() },
  { key: "chunks", label: "分块", onClick: vi.fn() },
  { key: "analyze", label: "分析", onClick: vi.fn() },
  { key: "delete", label: "删除", onClick: vi.fn(), danger: true },
];

function renderMenu(override: Partial<MoreMenuItem[]> = {}) {
  const merged = items.map((it, i) => ({ ...it, ...(override[i] ?? {}) }));
  return render(<MoreMenu items={merged} label="更多操作" />);
}

describe("MoreMenu", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("renders trigger button with correct a11y attributes", () => {
    renderMenu();
    const trigger = screen.getByRole("button", { name: /更多操作/ });
    expect(trigger).toHaveAttribute("aria-haspopup", "menu");
    expect(trigger).toHaveAttribute("aria-expanded", "false");
  });

  it("click trigger opens menu and toggles aria-expanded", async () => {
    const user = userEvent.setup();
    renderMenu();
    const trigger = screen.getByRole("button", { name: /更多操作/ });

    await user.click(trigger);

    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("menu")).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: /预览/ })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: /删除/ })).toBeInTheDocument();
  });

  it("click menu item triggers onClick and closes menu", async () => {
    const user = userEvent.setup();
    renderMenu();
    const trigger = screen.getByRole("button", { name: /更多操作/ });

    await user.click(trigger);
    const previewItem = screen.getByRole("menuitem", { name: /预览/ });
    await user.click(previewItem);

    expect(items[0].onClick).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("press Escape closes menu without triggering any item", async () => {
    const user = userEvent.setup();
    renderMenu();
    const trigger = screen.getByRole("button", { name: /更多操作/ });

    await user.click(trigger);
    await user.keyboard("{Escape}");

    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    items.forEach((it) => expect(it.onClick).not.toHaveBeenCalled());
  });

  it("click outside closes menu", async () => {
    const user = userEvent.setup();
    render(
      <div>
        <button>outside</button>
        <MoreMenu items={items} label="更多操作" />
      </div>
    );

    const trigger = screen.getByRole("button", { name: /更多操作/ });
    await user.click(trigger);
    expect(screen.getByRole("menu")).toBeInTheDocument();

    await user.click(screen.getByText("outside"));
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("disabled item is not clickable", async () => {
    const user = userEvent.setup();
    renderMenu([{ disabled: true } as Partial<MoreMenuItem>]);
    const trigger = screen.getByRole("button", { name: /更多操作/ });

    await user.click(trigger);
    const previewItem = screen.getByRole("menuitem", { name: /预览/ });
    expect(previewItem).toHaveAttribute("aria-disabled", "true");

    await user.click(previewItem);
    expect(items[0].onClick).not.toHaveBeenCalled();
  });

  it("danger item has red color class", async () => {
    const user = userEvent.setup();
    renderMenu();
    const trigger = screen.getByRole("button", { name: /更多操作/ });

    await user.click(trigger);
    const deleteItem = screen.getByRole("menuitem", { name: /删除/ });
    expect(deleteItem.className).toMatch(/text-red-400/);
  });

  it("trigger button respects disabled prop", async () => {
    const user = userEvent.setup();
    render(<MoreMenu items={items} label="更多操作" triggerDisabled />);
    const trigger = screen.getByRole("button", { name: /更多操作/ });

    expect(trigger).toBeDisabled();
    await user.click(trigger);
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("keyboard ArrowDown navigates to first menu item after opening", async () => {
    const user = userEvent.setup();
    renderMenu();
    const trigger = screen.getByRole("button", { name: /更多操作/ });

    await user.click(trigger);
    await user.keyboard("{ArrowDown}");

    const previewItem = screen.getByRole("menuitem", { name: /预览/ });
    expect(previewItem).toHaveFocus();
  });
});
