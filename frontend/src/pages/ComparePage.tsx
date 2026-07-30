import { useEffect, useMemo, useState } from "react";
import { useSearchParams, Link } from "react-router-dom";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";
import {
  compareResumes,
  type CompareResult,
  type ScoreDetail,
} from "../api/resumes";
import MarkdownRenderer from "../components/MarkdownRenderer";

// ── 调色板 ──
const COLORS = ["#38bdf8", "#a78bfa", "#f59e0b", "#34d399", "#f472b6"];

// ── 评分维度配置 ──
const SCORE_METRICS: Array<{
  key: keyof ScoreDetail;
  label: string;
}> = [
  { key: "ats_match", label: "ATS 匹配率" },
  { key: "keyword_coverage", label: "关键词覆盖率" },
  { key: "skill_density", label: "技能密度" },
  { key: "overall", label: "综合评价" },
];

/** 为评分柱状图构建数据：{ metric, resume1: 78, resume2: 87, ... } */
function buildScoreBarData(
  resumes: CompareResult["resumes"],
  scoreData: Record<string, ScoreDetail>
) {
  return SCORE_METRICS.map((metric) => {
    const point: Record<string, string | number> = { metric: metric.label };
    for (const r of resumes) {
      const detail = scoreData[String(r.id)];
      point[String(r.id)] = detail ? detail[metric.key] : 0;
    }
    return point;
  });
}

/** 为项目柱状图构建数据：{ name, count } */
function buildProjectBarData(
  resumes: CompareResult["resumes"],
  projectsData: Record<string, string[]>
) {
  return resumes.map((r) => ({
    name: r.filename.length > 16 ? r.filename.slice(0, 14) + "…" : r.filename,
    项目数: (projectsData[String(r.id)] ?? []).length,
    fullName: r.filename,
  }));
}

export default function ComparePage() {
  const [searchParams] = useSearchParams();
  const idsParam = searchParams.get("ids") ?? "";
  const resumeIds = idsParam
    .split(",")
    .map(Number)
    .filter((id) => !isNaN(id));

  const [result, setResult] = useState<CompareResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (resumeIds.length < 2) {
      setError("至少需要选择 2 份简历进行对比");
      setLoading(false);
      return;
    }

    setLoading(true);
    setError("");

    compareResumes(resumeIds)
      .then((data) => {
        setResult(data);
        setLoading(false);
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : "对比分析失败");
        setLoading(false);
      });
  }, [idsParam]);

  // ── 计算图表数据 ──
  const scoreDim = result?.dimensions.score;
  const scoreBarData = useMemo(
    () => (result && scoreDim ? buildScoreBarData(result.resumes, scoreDim) : []),
    [result, scoreDim],
  );

  const projectsDim = result?.dimensions.projects;
  const projectBarData = useMemo(
    () => (result && projectsDim ? buildProjectBarData(result.resumes, projectsDim) : []),
    [result, projectsDim],
  );

  // ── 加载中 ──
  if (loading) {
    return (
      <div className="max-w-4xl mx-auto px-6 md:px-8 lg:px-12 py-12">
        <div className="animate-pulse space-y-6">
          <div className="h-8 w-48 bg-[var(--color-border)]" />
          <div className="h-64 bg-[var(--color-border)]" />
        </div>
      </div>
    );
  }

  // ── 错误 ──
  if (error) {
    return (
      <div className="max-w-4xl mx-auto px-6 md:px-8 lg:px-12 py-12">
        <div className="mb-6 p-3.5 border-b-2 border-[var(--color-text)] text-[var(--color-text)] text-sm">
          <span className="font-mono-label tracking-widest uppercase text-xs">{error}</span>
        </div>
        <Link to="/" className="mono-btn-primary inline-flex">
          返回简历列表
        </Link>
      </div>
    );
  }

  if (!result) return null;

  const { resumes, dimensions } = result;
  const summaryDim = dimensions.summary;
  const skillsDim = dimensions.skills;
  const experienceDim = dimensions.experience;

  return (
    <div className="max-w-4xl mx-auto px-6 md:px-8 lg:px-12 py-12">
      {/* ── 标题 ── */}
      <div className="mb-8">
        <h1 className="font-display text-3xl md:text-4xl font-bold tracking-tight text-[var(--color-text)]">
          多简历对比
        </h1>
        <p className="text-sm text-[var(--color-text-secondary)] mt-2">
          对比 {resumes.length} 份简历的总结、技能、经验、评分和项目维度
        </p>
      </div>

      {/* ── 简历信息标签 ── */}
      <div className="mb-8 flex flex-wrap gap-2">
        {resumes.map((r, i) => (
          <span
            key={r.id}
            className="inline-flex items-center gap-1.5 rounded-md px-3 py-1 text-xs font-medium"
            style={{
              backgroundColor: `${COLORS[i % COLORS.length]}20`,
              borderColor: `${COLORS[i % COLORS.length]}40`,
              borderWidth: 1,
              color: COLORS[i % COLORS.length],
            }}
          >
            {r.filename}
          </span>
        ))}
      </div>

      {/* ── 总结对比 ── */}
      {summaryDim && (
        <div className="mb-10">
          <h2 className="font-display text-xl font-bold tracking-tight text-[var(--color-text)] mb-4 uppercase">
            总结对比
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {resumes.map((r, i) => (
              <div
                key={r.id}
                className="border border-[var(--color-border)] p-4"
                style={{ borderLeftColor: COLORS[i % COLORS.length], borderLeftWidth: 3 }}
              >
                <p className="text-sm font-medium text-[var(--color-text)] mb-2">
                  {r.filename}
                </p>
                <MarkdownRenderer>
                  {summaryDim[String(r.id)] ?? "无总结数据"}
                </MarkdownRenderer>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── 技能对比 ── */}
      {skillsDim && (
        <div className="mb-10">
          <h2 className="font-display text-xl font-bold tracking-tight text-[var(--color-text)] mb-4 uppercase">
            技能对比
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {resumes.map((r, i) => (
              <div
                key={r.id}
                className="border border-[var(--color-border)] p-4"
                style={{ borderLeftColor: COLORS[i % COLORS.length], borderLeftWidth: 3 }}
              >
                <p className="text-sm font-medium text-[var(--color-text)] mb-2">
                  {r.filename}
                </p>
                <MarkdownRenderer>
                  {skillsDim[String(r.id)] ?? "无技能数据"}
                </MarkdownRenderer>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── 经验对比 ── */}
      {experienceDim && (
        <div className="mb-10">
          <h2 className="font-display text-xl font-bold tracking-tight text-[var(--color-text)] mb-4 uppercase">
            经验对比
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {resumes.map((r, i) => (
              <div
                key={r.id}
                className="border border-[var(--color-border)] p-4"
                style={{ borderLeftColor: COLORS[i % COLORS.length], borderLeftWidth: 3 }}
              >
                <p className="text-sm font-medium text-[var(--color-text)] mb-2">
                  {r.filename}
                </p>
                <MarkdownRenderer>
                  {experienceDim[String(r.id)] ?? "无经验数据"}
                </MarkdownRenderer>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── 评分对比 ── */}
      {scoreDim && (
        <div className="mb-10">
          <h2 className="font-display text-xl font-bold tracking-tight text-[var(--color-text)] mb-4 uppercase">
            评分对比
          </h2>
          <div className="border border-[var(--color-border)] p-4 md:p-6 mb-6">
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={scoreBarData}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
                <XAxis
                  dataKey="metric"
                  tick={{ fontSize: 11, fill: "var(--color-text-secondary)" }}
                />
                <YAxis
                  domain={[0, 100]}
                  tick={{ fontSize: 11, fill: "var(--color-text-secondary)" }}
                />
                <Tooltip
                  contentStyle={{
                    background: "var(--color-bg)",
                    border: "1px solid var(--color-border)",
                    borderRadius: 4,
                    fontSize: 12,
                  }}
                />
                <Legend />
                {resumes.map((r, i) => (
                  <Bar
                    key={r.id}
                    dataKey={String(r.id)}
                    name={r.filename}
                    fill={COLORS[i % COLORS.length]}
                    radius={[2, 2, 0, 0]}
                  />
                ))}
              </BarChart>
            </ResponsiveContainer>
          </div>

          {/* 评分数值卡片 */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {resumes.map((r, i) => {
              const detail = scoreDim[String(r.id)];
              if (!detail) return null;
              return (
                <div
                  key={r.id}
                  className="border border-[var(--color-border)] p-4"
                  style={{ borderLeftColor: COLORS[i % COLORS.length], borderLeftWidth: 3 }}
                >
                  <p className="text-sm font-medium text-[var(--color-text)] mb-3">
                    {r.filename}
                  </p>
                  <div className="grid grid-cols-2 gap-3 text-xs">
                    {SCORE_METRICS.map((metric) => (
                      <div
                        key={metric.key}
                        className="flex items-center justify-between p-2 bg-[var(--color-bg-secondary)] rounded"
                      >
                        <span className="text-[var(--color-text-muted)]">{metric.label}</span>
                        <span className="font-mono font-semibold text-[var(--color-text)]">
                          {detail[metric.key]}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* ── 项目对比 ── */}
      {projectsDim && (
        <div className="mb-10">
          <h2 className="font-display text-xl font-bold tracking-tight text-[var(--color-text)] mb-4 uppercase">
            项目对比
          </h2>
          <div className="border border-[var(--color-border)] p-4 md:p-6 mb-6">
            <ResponsiveContainer width="100%" height={250}>
              <BarChart data={projectBarData}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
                <XAxis
                  dataKey="name"
                  tick={{ fontSize: 11, fill: "var(--color-text-secondary)" }}
                />
                <YAxis
                  allowDecimals={false}
                  tick={{ fontSize: 11, fill: "var(--color-text-secondary)" }}
                />
                <Tooltip
                  contentStyle={{
                    background: "var(--color-bg)",
                    border: "1px solid var(--color-border)",
                    borderRadius: 4,
                    fontSize: 12,
                  }}
                  // eslint-disable-next-line @typescript-eslint/no-explicit-any
                  formatter={(value: any, _name: any, props: any) => [
                    typeof value === "number" ? value : 0,
                    props?.payload?.fullName ?? "",
                  ]}
                />
                <Bar
                  dataKey="项目数"
                  fill={COLORS[0]}
                  radius={[2, 2, 0, 0]}
                />
              </BarChart>
            </ResponsiveContainer>
          </div>

          {/* 项目名称列表 */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {resumes.map((r, i) => {
              const items = projectsDim[String(r.id)] ?? [];
              return (
                <div
                  key={r.id}
                  className="border border-[var(--color-border)] p-4"
                >
                  <p className="text-sm font-medium text-[var(--color-text)] mb-2">
                    {r.filename}
                  </p>
                  <div className="flex flex-wrap gap-1.5">
                    {items.length === 0 ? (
                      <span className="text-xs text-[var(--color-text-muted)]">无项目数据</span>
                    ) : (
                      items.map((item, j) => (
                        <span
                          key={j}
                          className="inline-flex items-center rounded-md px-2.5 py-0.5 text-xs font-medium"
                          style={{
                            backgroundColor: `${COLORS[i % COLORS.length]}20`,
                            borderColor: `${COLORS[i % COLORS.length]}40`,
                            borderWidth: 1,
                            color: COLORS[i % COLORS.length],
                          }}
                        >
                          {item}
                        </span>
                      ))
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* ── 返回按钮 ── */}
      <Link to="/" className="mono-btn-primary inline-flex">
        返回简历列表
      </Link>
    </div>
  );
}
