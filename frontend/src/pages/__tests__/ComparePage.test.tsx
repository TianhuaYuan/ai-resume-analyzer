import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import ComparePage from "../ComparePage";

// 新数据结构：skills/experience/summary 是 LLM 分析 Markdown 字符串，
// score 是结构化评分，projects 是项目名列表
const mockCompareResult = {
  resumes: [
    { id: 1, filename: "resume-a.pdf" },
    { id: 2, filename: "resume-b.pdf" },
  ],
  dimensions: {
    summary: {
      "1": "候选人精通 Python 与 FastAPI，3 年后端经验。",
      "2": "候选人擅长 Java 与 Spring Boot，5 年后端经验。",
    },
    skills: {
      "1": "编程语言: Python\n框架: FastAPI, React\n工具: Docker, PostgreSQL",
      "2": "编程语言: Java\n框架: Spring Boot\n工具: MySQL, Redis, Kubernetes",
    },
    experience: {
      "1": "工作经历:\n- A 公司 后端工程师 2022-2024",
      "2": "工作经历:\n- B 公司 高级工程师 2020-2025",
    },
    score: {
      "1": {
        ats_match: 85,
        keyword_coverage: 70,
        skill_density: 80,
        overall: 78,
      },
      "2": {
        ats_match: 90,
        keyword_coverage: 85,
        skill_density: 88,
        overall: 87,
      },
    },
    projects: {
      "1": ["简历分析系统"],
      "2": ["电商系统", "支付网关"],
    },
  },
};

// Mock recharts components
vi.mock("recharts", () => {
  const MockBarChart = ({ children, ...props }: any) => (
    <div data-testid="bar-chart" data-bar-chart-props={JSON.stringify(props)}>
      {children}
    </div>
  );
  const MockBar = ({ dataKey, name, ...props }: any) => (
    <div data-testid={`bar-${dataKey}`} data-bar-name={name} />
  );
  const MockXAxis = () => <div data-testid="x-axis" />;
  const MockYAxis = () => <div data-testid="y-axis" />;
  const MockCartesianGrid = () => <div data-testid="cartesian-grid" />;
  const MockTooltip = () => <div data-testid="tooltip" />;
  const MockLegend = () => <div data-testid="legend" />;
  const MockResponsiveContainer = ({ children, ...props }: any) => (
    <div data-testid="responsive-container" data-container-props={JSON.stringify(props)}>
      {children}
    </div>
  );

  return {
    BarChart: MockBarChart,
    Bar: MockBar,
    XAxis: MockXAxis,
    YAxis: MockYAxis,
    CartesianGrid: MockCartesianGrid,
    Tooltip: MockTooltip,
    Legend: MockLegend,
    ResponsiveContainer: MockResponsiveContainer,
  };
});

vi.mock("../../api/resumes", () => ({
  compareResumes: vi.fn(),
}));

import { compareResumes } from "../../api/resumes";

function renderPage(route = "/compare?ids=1,2") {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <ComparePage />
    </MemoryRouter>
  );
}

describe("ComparePage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("加载中显示骨架屏", () => {
    vi.mocked(compareResumes).mockReturnValue(new Promise(() => {}));
    renderPage();
    const skeleton = document.querySelector(".animate-pulse");
    expect(skeleton).toBeInTheDocument();
  });

  it("少于 2 份简历时显示错误", async () => {
    renderPage("/compare?ids=1");
    await waitFor(() => {
      expect(screen.getByText(/至少需要选择 2 份简历/)).toBeInTheDocument();
    });
  });

  it("无 ids 参数时显示错误", async () => {
    renderPage("/compare");
    await waitFor(() => {
      expect(screen.getByText(/至少需要选择 2 份简历/)).toBeInTheDocument();
    });
  });

  it("API 错误时显示错误信息", async () => {
    vi.mocked(compareResumes).mockRejectedValue(new Error("网络错误"));
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/网络错误/)).toBeInTheDocument();
    });
  });

  it("成功时显示对比结果标题和简历数量", async () => {
    vi.mocked(compareResumes).mockResolvedValue(mockCompareResult);
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("多简历对比")).toBeInTheDocument();
      expect(screen.getByText(/2 份简历/)).toBeInTheDocument();
    });
  });

  it("成功时显示每份简历的名称标签", async () => {
    vi.mocked(compareResumes).mockResolvedValue(mockCompareResult);
    renderPage();
    await waitFor(() => {
      const matches = screen.getAllByText("resume-a.pdf");
      expect(matches.length).toBeGreaterThanOrEqual(1);
      const matchesB = screen.getAllByText("resume-b.pdf");
      expect(matchesB.length).toBeGreaterThanOrEqual(1);
    });
  });

  it("显示总结维度（summary）区域标题", async () => {
    vi.mocked(compareResumes).mockResolvedValue(mockCompareResult);
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("总结对比")).toBeInTheDocument();
    });
  });

  it("显示技能维度（skills）区域标题", async () => {
    vi.mocked(compareResumes).mockResolvedValue(mockCompareResult);
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("技能对比")).toBeInTheDocument();
    });
  });

  it("显示经验维度（experience）区域标题", async () => {
    vi.mocked(compareResumes).mockResolvedValue(mockCompareResult);
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("经验对比")).toBeInTheDocument();
    });
  });

  it("显示评分维度（score）区域标题", async () => {
    vi.mocked(compareResumes).mockResolvedValue(mockCompareResult);
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("评分对比")).toBeInTheDocument();
    });
  });

  it("显示项目维度（projects）区域标题", async () => {
    vi.mocked(compareResumes).mockResolvedValue(mockCompareResult);
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("项目对比")).toBeInTheDocument();
    });
  });

  it("skills 维度渲染 LLM 分析文本（Markdown）", async () => {
    vi.mocked(compareResumes).mockResolvedValue(mockCompareResult);
    renderPage();
    await waitFor(() => {
      // skills 现在是字符串，应渲染 Markdown 内容而非雷达图
      // 两份简历都有"编程语言"，用 getAllByText
      expect(screen.getAllByText(/编程语言/).length).toBeGreaterThanOrEqual(2);
      expect(screen.getAllByText(/Python/).length).toBeGreaterThanOrEqual(1);
      expect(screen.getAllByText(/Spring Boot/).length).toBeGreaterThanOrEqual(1);
    });
  });

  it("score 维度渲染结构化评分", async () => {
    vi.mocked(compareResumes).mockResolvedValue(mockCompareResult);
    renderPage();
    await waitFor(() => {
      // 应显示综合评分数字
      expect(screen.getByText("78")).toBeInTheDocument();
      expect(screen.getByText("87")).toBeInTheDocument();
    });
  });

  it("score 维度渲染评分柱状图", async () => {
    vi.mocked(compareResumes).mockResolvedValue(mockCompareResult);
    renderPage();
    await waitFor(() => {
      const scoreSection = screen.getByText("评分对比").closest("div");
      expect(scoreSection?.querySelector('[data-testid="bar-chart"]')).toBeInTheDocument();
    });
  });

  it("summary 维度渲染 Markdown 文本", async () => {
    vi.mocked(compareResumes).mockResolvedValue(mockCompareResult);
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/候选人精通 Python/)).toBeInTheDocument();
      expect(screen.getByText(/候选人擅长 Java/)).toBeInTheDocument();
    });
  });

  it("experience 维度渲染 Markdown 文本", async () => {
    vi.mocked(compareResumes).mockResolvedValue(mockCompareResult);
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/A 公司/)).toBeInTheDocument();
      expect(screen.getByText(/B 公司/)).toBeInTheDocument();
    });
  });

  it("项目维度渲染柱状图", async () => {
    vi.mocked(compareResumes).mockResolvedValue(mockCompareResult);
    renderPage();
    await waitFor(() => {
      const projectsSection = screen.getByText("项目对比").closest("div");
      expect(projectsSection?.querySelector('[data-testid="bar-chart"]')).toBeInTheDocument();
    });
  });

  it("项目维度显示项目名称", async () => {
    vi.mocked(compareResumes).mockResolvedValue(mockCompareResult);
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("简历分析系统")).toBeInTheDocument();
      expect(screen.getByText("电商系统")).toBeInTheDocument();
      expect(screen.getByText("支付网关")).toBeInTheDocument();
    });
  });

  it("没有项目数据时显示「无项目数据」", async () => {
    const noProjectResult = {
      ...mockCompareResult,
      dimensions: {
        ...mockCompareResult.dimensions,
        projects: {
          "1": [],
          "2": [],
        },
      },
    };
    vi.mocked(compareResumes).mockResolvedValue(noProjectResult);
    renderPage();
    await waitFor(() => {
      expect(screen.getAllByText("无项目数据").length).toBeGreaterThanOrEqual(2);
    });
  });

  it("返回按钮导航到首页", async () => {
    vi.mocked(compareResumes).mockResolvedValue(mockCompareResult);
    renderPage();
    await waitFor(() => {
      const backLink = screen.getByText("返回简历列表");
      expect(backLink).toBeInTheDocument();
      expect(backLink.closest("a")).toHaveAttribute("href", "/");
    });
  });

  it("错误页面显示返回按钮", async () => {
    renderPage("/compare?ids=1");
    await waitFor(() => {
      const backLink = screen.getByText("返回简历列表");
      expect(backLink).toBeInTheDocument();
      expect(backLink.closest("a")).toHaveAttribute("href", "/");
    });
  });
});
