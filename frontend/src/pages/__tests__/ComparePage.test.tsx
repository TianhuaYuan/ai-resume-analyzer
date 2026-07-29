import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import ComparePage from "../ComparePage";

const mockCompareResult = {
  resumes: [
    { id: 1, filename: "resume-a.pdf" },
    { id: 2, filename: "resume-b.pdf" },
  ],
  dimensions: {
    skills: {
      "1": ["Python", "FastAPI", "React", "Docker", "PostgreSQL"],
      "2": ["Java", "Spring Boot", "MySQL", "Redis", "Kubernetes"],
    },
    projects: {
      "1": ["简历分析系统"],
      "2": ["电商系统", "支付网关"],
    },
  },
};

// Mock recharts components — they render div wrappers for testing
vi.mock("recharts", () => {
  const MockRadarChart = ({ children, ...props }: any) => (
    <div data-testid="radar-chart" data-radar-chart-props={JSON.stringify(props)}>
      {children}
    </div>
  );
  const MockBarChart = ({ children, ...props }: any) => (
    <div data-testid="bar-chart" data-bar-chart-props={JSON.stringify(props)}>
      {children}
    </div>
  );
  const MockRadar = ({ dataKey, name, ...props }: any) => (
    <div data-testid={`radar-${dataKey}`} data-radar-name={name} />
  );
  const MockBar = ({ dataKey, name, ...props }: any) => (
    <div data-testid={`bar-${dataKey}`} data-bar-name={name} />
  );
  const MockPolarGrid = () => <div data-testid="polar-grid" />;
  const MockPolarAngleAxis = ({ dataKey }: any) => (
    <div data-testid="polar-angle-axis" data-datakey={dataKey} />
  );
  const MockPolarRadiusAxis = () => <div data-testid="polar-radius-axis" />;
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
    RadarChart: MockRadarChart,
    BarChart: MockBarChart,
    Radar: MockRadar,
    Bar: MockBar,
    PolarGrid: MockPolarGrid,
    PolarAngleAxis: MockPolarAngleAxis,
    PolarRadiusAxis: MockPolarRadiusAxis,
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
    // 永不 resolve 的 Promise，保持 loading 状态
    vi.mocked(compareResumes).mockReturnValue(new Promise(() => {}));
    renderPage();
    // 骨架屏使用 animate-pulse 类
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

  it("API 返回 404 时显示错误信息", async () => {
    vi.mocked(compareResumes).mockRejectedValue(new Error("Request failed with status code 404"));
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/404/)).toBeInTheDocument();
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
      // resume-a.pdf 在标签列表和项目区域各出现一次 → getAllByText
      const matches = screen.getAllByText("resume-a.pdf");
      expect(matches.length).toBeGreaterThanOrEqual(1);
      const matchesB = screen.getAllByText("resume-b.pdf");
      expect(matchesB.length).toBeGreaterThanOrEqual(1);
    });
  });

  it("成功时显示技能维度标签", async () => {
    vi.mocked(compareResumes).mockResolvedValue(mockCompareResult);
    renderPage();
    await waitFor(() => {
      // 技能在雷达图中渲染（mock 中 data-testid="radar-chart" 存在）
      const skillsSection = screen.getByText("技能对比").closest("div");
      expect(skillsSection?.querySelector('[data-testid="radar-chart"]')).toBeInTheDocument();
    });
  });

  it("成功时显示项目维度标签", async () => {
    vi.mocked(compareResumes).mockResolvedValue(mockCompareResult);
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("简历分析系统")).toBeInTheDocument();
      expect(screen.getByText("电商系统")).toBeInTheDocument();
    });
  });

  it("技能维度渲染雷达图", async () => {
    vi.mocked(compareResumes).mockResolvedValue(mockCompareResult);
    renderPage();
    await waitFor(() => {
      const skillsSection = screen.getByText("技能对比").closest("div");
      expect(skillsSection?.querySelector('[data-testid="radar-chart"]')).toBeInTheDocument();
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

  it("没有项目数据时显示「无项目数据」", async () => {
    const noProjectResult = {
      resumes: [
        { id: 1, filename: "resume-a.pdf" },
        { id: 2, filename: "resume-b.pdf" },
      ],
      dimensions: {
        skills: {
          "1": ["Python"],
          "2": ["Java"],
        },
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
