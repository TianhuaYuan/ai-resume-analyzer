import { useEffect, useMemo, useState } from "react";
import { useSearchParams, Link } from "react-router-dom";
import {
  RadarChart,
  Radar,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";
import { compareResumes, type CompareResult } from "../api/resumes";

// ── 调色板 ──
const COLORS = ["#38bdf8", "#a78bfa", "#f59e0b", "#34d399", "#f472b6"];

/** 从对比数据中提取所有唯一技能（合并两份简历的技能集） */
function computeAllSkills(dimensions: CompareResult["dimensions"]): string[] {
  const skills = dimensions.skills ?? {};
  const all = new Set<string>();
  for (const list of Object.values(skills)) {
    for (const s of list) all.add(s);
  }
  return Array.from(all).slice(0, 12); // 最多 12 个技能，避免雷达图过密
}

/** 为雷达图构建数据：{ skill, resumeId: 1|0, ... } */
function buildRadarData(
  resumeIds: number[],
  allSkills: string[],
  skillsData: Record<string, string[]>,
) {
  return allSkills.map((skill) => {
    const point: Record<string, string | number> = { skill };
    for (const id of resumeIds) {
      point[String(id)] = (skillsData[String(id)] ?? []).includes(skill) ? 1 : 0;
    }
    return point;
  });
}

/** 为项目柱状图构建数据：{ name, count } */
function buildBarData(
  resumes: CompareResult["resumes"],
  projectsData: Record<string, string[]>,
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
  const allSkills = useMemo(
    () => (result ? computeAllSkills(result.dimensions) : []),
    [result],
  );
  const radarData = useMemo(
    () =>
      result
        ? buildRadarData(
            result.resumes.map((r) => r.id),
            allSkills,
            result.dimensions.skills ?? {},
          )
        : [],
    [result, allSkills],
  );
  const projectsDim = result?.dimensions.projects;
  const barData = useMemo(
    () => (result && projectsDim ? buildBarData(result.resumes, projectsDim) : []),
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

  return (
    <div className="max-w-4xl mx-auto px-6 md:px-8 lg:px-12 py-12">
      {/* ── 标题 ── */}
      <div className="mb-8">
        <h1 className="font-display text-3xl md:text-4xl font-bold tracking-tight text-[var(--color-text)]">
          多简历对比
        </h1>
        <p className="text-sm text-[var(--color-text-secondary)] mt-2">
          对比 {result.resumes.length} 份简历的技能和项目维度
        </p>
      </div>

      {/* ── 简历信息标签 ── */}
      <div className="mb-8 flex flex-wrap gap-2">
        {result.resumes.map((r, i) => (
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

      {/* ── 技能雷达图 ── */}
      {allSkills.length > 0 && (
        <div className="mb-10">
          <h2 className="font-display text-xl font-bold tracking-tight text-[var(--color-text)] mb-4 uppercase">
            技能对比
          </h2>
          <div className="border border-[var(--color-border)] p-4 md:p-6">
            <ResponsiveContainer width="100%" height={350}>
              <RadarChart data={radarData}>
                <PolarGrid stroke="var(--color-border)" />
                <PolarAngleAxis
                  dataKey="skill"
                  tick={{ fontSize: 11, fill: "var(--color-text-secondary)" }}
                />
                <PolarRadiusAxis
                  domain={[0, 1]}
                  tick={false}
                  axisLine={false}
                />
                <Tooltip
                  contentStyle={{
                    background: "var(--color-bg)",
                    border: "1px solid var(--color-border)",
                    borderRadius: 4,
                    fontSize: 12,
                  }}
                />
                {result.resumes.map((r, i) => (
                  <Radar
                    key={r.id}
                    name={r.filename}
                    dataKey={String(r.id)}
                    stroke={COLORS[i % COLORS.length]}
                    fill={COLORS[i % COLORS.length]}
                    fillOpacity={0.15}
                  />
                ))}
              </RadarChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {/* ── 项目柱状图 + 详情 ── */}
      {projectsDim && (
        <div className="mb-10">
          <h2 className="font-display text-xl font-bold tracking-tight text-[var(--color-text)] mb-4 uppercase">
            项目对比
          </h2>
          <div className="border border-[var(--color-border)] p-4 md:p-6 mb-6">
            <ResponsiveContainer width="100%" height={250}>
              <BarChart data={barData}>
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
                  formatter={(value: number, _name: string, props: { payload: { fullName: string } }) => [
                    value,
                    props.payload.fullName,
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
            {result.resumes.map((r, i) => {
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
                    {(items as string[]).length === 0 ? (
                      <span className="text-xs text-[var(--color-text-muted)]">无项目数据</span>
                    ) : (
                      (items as string[]).map((item, j) => (
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
