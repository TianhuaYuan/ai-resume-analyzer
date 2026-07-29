import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, fireEvent, act, waitFor, screen } from "@testing-library/react";

vi.mock("../api/resumes", () => ({
  getChunks: vi.fn(),
}));

import ChunksModal from "./ChunksModal";
import { getChunks } from "../api/resumes";

const mockGetChunks = vi.mocked(getChunks);

beforeEach(() => {
  mockGetChunks.mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
});

function renderModal(props: Partial<React.ComponentProps<typeof ChunksModal>> = {}) {
  const defaultProps = {
    resumeId: 42,
    resumeFilename: "test-resume.pdf",
    open: true,
    onClose: vi.fn(),
  };
  return render(<ChunksModal {...defaultProps} {...props} />);
}

const SAMPLE_CHUNKS = [
  {
    chunk_index: 0,
    section: "基本信息",
    text: "姓名：张三，邮箱：zhangsan@example.com",
    start_char: 0,
    end_char: 30,
  },
  {
    chunk_index: 1,
    section: "工作经历",
    text: "A 公司 后端工程师 2022-2024",
    start_char: 30,
    end_char: 60,
  },
  {
    chunk_index: 2,
    section: "技能",
    text: "Python, FastAPI, MySQL",
    start_char: 60,
    end_char: 85,
  },
];

describe("ChunksModal (Task 3 前端)", () => {
  it("open=false 时不渲染", () => {
    renderModal({ open: false });
    expect(screen.queryByText(/test-resume\.pdf/)).toBeNull();
  });

  it("open=true 时显示标题（含 filename）和总数摘要", async () => {
    mockGetChunks.mockResolvedValue({
      resume_id: 42,
      total: 3,
      chunks: SAMPLE_CHUNKS,
    });
    renderModal();

    await waitFor(() => expect(mockGetChunks).toHaveBeenCalled());

    expect(screen.getByText(/test-resume\.pdf/)).toBeInTheDocument();
    // 摘要里显示总数："个分块" 是稳定的文本片段
    expect(screen.getByText(/个分块/)).toBeInTheDocument();
    // 数字 3 应该作为分块计数显示
    expect(screen.getByText("3")).toBeInTheDocument();
  });

  it("open=true 自动调 getChunks(id)", async () => {
    mockGetChunks.mockResolvedValue({
      resume_id: 42,
      total: 3,
      chunks: SAMPLE_CHUNKS,
    });
    renderModal();

    await waitFor(() => {
      expect(mockGetChunks).toHaveBeenCalledWith(42);
    });
  });

  it("Loading 态显示 skeleton", async () => {
    // 永不 resolve 锁定 loading 态
    mockGetChunks.mockReturnValue(new Promise(() => {}));
    renderModal();

    await waitFor(() => expect(mockGetChunks).toHaveBeenCalled());
    const skeletons = document.querySelectorAll(".animate-skeleton");
    expect(skeletons.length).toBeGreaterThanOrEqual(3);
  });

  it("Error 态显示错误信息 + 重试按钮，点重试重新调用", async () => {
    mockGetChunks.mockRejectedValueOnce(new Error("简历向量未就绪"));
    mockGetChunks.mockResolvedValueOnce({
      resume_id: 42,
      total: 3,
      chunks: SAMPLE_CHUNKS,
    });
    renderModal();

    await waitFor(() => {
      expect(screen.getByText(/简历向量未就绪/)).toBeInTheDocument();
    });

    const retryBtn = screen.getByRole("button", { name: /重试/ });
    await act(async () => {
      fireEvent.click(retryBtn);
    });

    await waitFor(() => {
      expect(mockGetChunks).toHaveBeenCalledTimes(2);
    });
  });

  it("Success 态渲染所有 chunk 卡片（按 chunk_index 排列）", async () => {
    mockGetChunks.mockResolvedValue({
      resume_id: 42,
      total: 3,
      chunks: SAMPLE_CHUNKS,
    });
    renderModal();

    // 三个 section 标题都应出现
    await waitFor(() => {
      expect(screen.getByText(/基本信息/)).toBeInTheDocument();
      expect(screen.getByText(/工作经历/)).toBeInTheDocument();
      expect(screen.getByText(/技能/)).toBeInTheDocument();
    });
  });

  it("chunk 文本默认折叠，点击展开后显示文本内容", async () => {
    mockGetChunks.mockResolvedValue({
      resume_id: 42,
      total: 1,
      chunks: [SAMPLE_CHUNKS[0]],
    });
    renderModal();

    await waitFor(() => {
      expect(screen.getByText(/基本信息/)).toBeInTheDocument();
    });

    // 折叠态：不显示文本内容
    expect(screen.queryByText(/姓名：张三/)).toBeNull();

    // 点击卡片头部展开
    const card = screen.getByText(/基本信息/).closest("button") as HTMLElement;
    await act(async () => {
      fireEvent.click(card);
    });

    // 展开后显示文本
    await waitFor(() => {
      expect(screen.getByText(/姓名：张三/)).toBeInTheDocument();
    });
  });

  it("空 chunks（total=0）显示空态提示", async () => {
    mockGetChunks.mockResolvedValue({
      resume_id: 42,
      total: 0,
      chunks: [],
    });
    renderModal();

    await waitFor(() => {
      expect(screen.getByText(/暂无分块数据/)).toBeInTheDocument();
    });
  });

  it("点 X 按钮调用 onClose", async () => {
    mockGetChunks.mockResolvedValue({
      resume_id: 42,
      total: 1,
      chunks: [SAMPLE_CHUNKS[0]],
    });
    const onClose = vi.fn();
    renderModal({ onClose });

    const closeBtn = screen.getByLabelText(/关闭/);
    await act(async () => {
      fireEvent.click(closeBtn);
    });

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("按 Esc 调用 onClose", async () => {
    mockGetChunks.mockResolvedValue({
      resume_id: 42,
      total: 1,
      chunks: [SAMPLE_CHUNKS[0]],
    });
    const onClose = vi.fn();
    renderModal({ onClose });

    const dialog = document.querySelector("dialog");
    expect(dialog).not.toBeNull();
    await act(async () => {
      dialog!.dispatchEvent(new Event("cancel", { cancelable: true }));
    });

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("点 overlay 遮罩调用 onClose", async () => {
    mockGetChunks.mockResolvedValue({
      resume_id: 42,
      total: 1,
      chunks: [SAMPLE_CHUNKS[0]],
    });
    const onClose = vi.fn();
    renderModal({ onClose });

    const dialog = document.querySelector("dialog");
    expect(dialog).not.toBeNull();
    await act(async () => {
      dialog!.dispatchEvent(new Event("close"));
    });

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("点卡片本体不关闭（事件不冒泡到 overlay）", async () => {
    mockGetChunks.mockResolvedValue({
      resume_id: 42,
      total: 1,
      chunks: [SAMPLE_CHUNKS[0]],
    });
    const onClose = vi.fn();
    renderModal({ onClose });

    await act(async () => {
      fireEvent.click(screen.getByText(/test-resume\.pdf/));
    });

    expect(onClose).not.toHaveBeenCalled();
  });

  it("每个 chunk 卡片显示 chunk_index 徽章 + section 名", async () => {
    mockGetChunks.mockResolvedValue({
      resume_id: 42,
      total: 3,
      chunks: SAMPLE_CHUNKS,
    });
    renderModal();

    await waitFor(() => {
      // 三个 chunk_index 徽章
      expect(screen.getByText("#0")).toBeInTheDocument();
      expect(screen.getByText("#1")).toBeInTheDocument();
      expect(screen.getByText("#2")).toBeInTheDocument();
    });
  });

  describe("布局结构", () => {
    it("dialog 本身不可滚动 (overflow-hidden)，防止标题跟内容一起滚", async () => {
      mockGetChunks.mockResolvedValue({
        resume_id: 42,
        total: 3,
        chunks: SAMPLE_CHUNKS,
      });
      renderModal();

      await waitFor(() => {
        expect(screen.getByText(/基本信息/)).toBeInTheDocument();
      });

      const dialog = document.querySelector("dialog") as HTMLElement;
      expect(dialog).not.toBeNull();
      expect(dialog!.className).toContain("overflow-hidden");
    });

    it("弹窗内容容器为 flex 列布局 + overflow-hidden 防止双重滚动", async () => {
      mockGetChunks.mockResolvedValue({
        resume_id: 42,
        total: 3,
        chunks: SAMPLE_CHUNKS,
      });
      renderModal();

      await waitFor(() => {
        expect(screen.getByText(/基本信息/)).toBeInTheDocument();
      });

      // 内部白色卡片容器：flex-col + overflow-hidden
      const container = document.querySelector("dialog > div") as HTMLElement;
      expect(container).not.toBeNull();
      expect(container.className).toContain("flex");
      expect(container.className).toContain("flex-col");
      expect(container.className).toContain("overflow-hidden");
    });

    it("标题栏 shrink-0 固定置顶，不会随内容滚动", async () => {
      mockGetChunks.mockResolvedValue({
        resume_id: 42,
        total: 3,
        chunks: SAMPLE_CHUNKS,
      });
      renderModal();

      await waitFor(() => {
        expect(screen.getByText(/基本信息/)).toBeInTheDocument();
      });

      // 标题栏（含"分块预览"文字的直接父级）有 shrink-0
      const header = screen.getByText("分块预览").closest(".shrink-0") as HTMLElement;
      expect(header).not.toBeNull();
    });

    it("分块列表区域独立滚动 (overflow-y-auto + scrollbarGutter)", async () => {
      mockGetChunks.mockResolvedValue({
        resume_id: 42,
        total: 3,
        chunks: SAMPLE_CHUNKS,
      });
      renderModal();

      await waitFor(() => {
        expect(screen.getByText(/基本信息/)).toBeInTheDocument();
      });

      // 内容滚动区域
      const scrollArea = document.querySelector(".overflow-y-auto") as HTMLElement;
      expect(scrollArea).not.toBeNull();
      expect(scrollArea.className).toContain("overflow-y-auto");
      // scrollbar-gutter: stable 防止滚动条挤压内容
      expect(scrollArea.style.scrollbarGutter).toBe("stable");
    });

    it("弹窗容器有响应式宽度断点 (sm/md)", async () => {
      mockGetChunks.mockResolvedValue({
        resume_id: 42,
        total: 3,
        chunks: SAMPLE_CHUNKS,
      });
      renderModal();

      await waitFor(() => {
        expect(screen.getByText(/基本信息/)).toBeInTheDocument();
      });

      const container = document.querySelector("dialog > div") as HTMLElement;
      expect(container).not.toBeNull();
      // 响应式断点
      expect(container.className).toContain("sm:max-w-lg");
      expect(container.className).toContain("md:max-w-2xl");
    });

    it("弹窗容器有响应式最大高度断点", async () => {
      mockGetChunks.mockResolvedValue({
        resume_id: 42,
        total: 3,
        chunks: SAMPLE_CHUNKS,
      });
      renderModal();

      await waitFor(() => {
        expect(screen.getByText(/基本信息/)).toBeInTheDocument();
      });

      const container = document.querySelector("dialog > div") as HTMLElement;
      expect(container).not.toBeNull();
      // 移动端和桌面端不同 max-h
      expect(container.className).toContain("max-h-");
    });

    it("chunk 列表容器有足够上下间距", async () => {
      mockGetChunks.mockResolvedValue({
        resume_id: 42,
        total: 3,
        chunks: SAMPLE_CHUNKS,
      });
      renderModal();

      await waitFor(() => {
        expect(screen.getByText(/基本信息/)).toBeInTheDocument();
      });

      // 列表容器 spacing 从 space-y-2.5 提升到 space-y-3.5
      const listContainer = document.querySelector(".space-y-3\\.5") as HTMLElement;
      expect(listContainer).not.toBeNull();
    });
  });
});
