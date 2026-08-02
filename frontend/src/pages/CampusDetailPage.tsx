/**
 * CampusDetailPage — 校招信息详情页。
 *
 * 路由：/campus/:id
 * 数据来源：GET /api/v1/campus/list（无独立详情接口，从列表中查找）
 * 左栏：招聘公告（白底卡片，不跟随主题）
 * 右栏：公司信息侧边栏（Logo、标签、摘要、标签云、核心亮点、适合人群、CTA）
 * 底部：上/下一个校招导航 + 推荐校招网格
 */

import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  CaretLeft,
  CaretRight,
  Building,
  CalendarBlank,
  MapPin,
  Briefcase,
  Clock,
  Factory,
  Spinner,
  Users,
} from "@phosphor-icons/react";
import LandingNav from "../components/LandingNav";
import { listCampusRecords, type CampusRecord } from "../api/campus";

// ── 工具函数 ──

function formatDate(dateStr: string | null | undefined): string {
  if (!dateStr) return "-";
  const d = new Date(dateStr.replace(" ", "T"));
  if (isNaN(d.getTime())) return dateStr.slice(0, 10);
  return d.toLocaleDateString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
}

function parseList(str: string | null | undefined): string[] {
  if (!str) return [];
  return str
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}

function isUrl(str: string): boolean {
  return /^https?:\/\//.test(str);
}

// ── 行业 → 适合人群映射 ──

const INDUSTRY_SUITABLE: Record<string, string[]> = {
  科技: [
    "对前沿科技有热情的应届生",
    "计算机/软件工程相关专业",
    "具备技术研发能力的工程师",
  ],
  "互联网/AI": [
    "计算机科学/AI方向应届生",
    "对互联网产品有热情的候选人",
    "具备全栈开发能力的工程师",
  ],
  "半导体/芯片": [
    "微电子/集成电路相关专业应届生",
    "对芯片设计有深入研究者",
    "有志于国产芯片事业的工程师",
  ],
  "电子/央企": [
    "电子信息/通信工程专业应届生",
    "对国防电子事业有情怀的工程师",
    "有志于投身国家安全与信息化建设的毕业生",
  ],
  "ICT/通信": [
    "通信工程/电子信息专业应届生",
    "对5G/6G通信技术有深入研究者",
    "热衷于系统级软件开发的工程师",
  ],
  金融: [
    "金融/经济/数学相关专业应届生",
    "对量化分析有热情的候选人",
    "具备数据分析能力的工程师",
  ],
  教育: [
    "教育学/心理学相关专业应届生",
    "对教育科技有热情的候选人",
    "具备内容创作能力的人才",
  ],
  "医疗健康": [
    "医学/生物医学相关专业应届生",
    "对医疗科技有热情的候选人",
    "具备数据分析能力的工程师",
  ],
};

// ── 高亮信息图标映射 ──

const HIGHLIGHT_ICONS: Record<
  string,
  React.ComponentType<{ size?: number; className?: string }>
> = {
  招聘城市: MapPin,
  岗位数量: Briefcase,
  招聘批次: Clock,
  所属行业: Factory,
};

// ── 主组件 ──

export default function CampusDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

  const [record, setRecord] = useState<CampusRecord | null>(null);
  const [allItems, setAllItems] = useState<CampusRecord[]>([]);
  const [recommended, setRecommended] = useState<CampusRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // 获取当前记录 + 列表（用于上/下一个导航）
  useEffect(() => {
    if (!id) return;
    setLoading(true);
    setError("");
    setRecord(null);
    listCampusRecords({ q: "", page: 1, limit: 100 })
      .then((data) => {
        const found = data.items.find((item) => item.id === id);
        if (found) {
          setRecord(found);
          setAllItems(data.items);
        } else {
          setError("记录不存在");
        }
      })
      .catch((err) =>
        setError(err instanceof Error ? err.message : "加载失败，请稍后再试"),
      )
      .finally(() => setLoading(false));
  }, [id]);

  // 获取推荐校招
  useEffect(() => {
    listCampusRecords({ page: 1, limit: 5 })
      .then((data) => {
        setRecommended(
          data.items.filter((item) => item.id !== id).slice(0, 4),
        );
      })
      .catch(() => {});
  }, [id]);

  // ── Loading ──
  if (loading) {
    return (
      <div className="min-h-screen bg-[var(--color-bg)]">
        <LandingNav activeKey="campus" />
        <div className="flex items-center justify-center py-40">
          <Spinner
            size={24}
            className="animate-spin text-[var(--color-text-muted)]"
          />
        </div>
      </div>
    );
  }

  // ── Error / Not Found ──
  if (error || !record) {
    return (
      <div className="min-h-screen bg-[var(--color-bg)]">
        <LandingNav activeKey="campus" />
        <div className="max-w-7xl mx-auto px-6 py-20 text-center">
          <p className="text-[var(--color-text-muted)] text-sm">
            {error || "记录不存在"}
          </p>
          <button
            onClick={() => navigate("/campus")}
            className="mt-4 text-brand text-sm hover:underline cursor-pointer"
          >
            返回校招列表
          </button>
        </div>
      </div>
    );
  }

  // ── 派生数据 ──
  const positionsList = parseList(record.positions);
  const workLocations = parseList(record.workLocation);
  const publishDate = record.recordTime || record.createTime;

  const currentIndex = allItems.findIndex((item) => item.id === id);
  const prevRecord = currentIndex > 0 ? allItems[currentIndex - 1] : null;
  const nextRecord =
    currentIndex < allItems.length - 1 ? allItems[currentIndex + 1] : null;

  // 核心亮点
  const highlights = [
    {
      label: "招聘城市",
      value: workLocations.join("、") || record.workLocation || "-",
    },
    { label: "岗位数量", value: `${positionsList.length} 个岗位` },
    { label: "招聘批次", value: record.infoType || "-" },
    { label: "所属行业", value: record.industry || "-" },
  ];

  // 标签云（industry + 工作地点拆分）
  const tagCloudItems = [record.industry, ...workLocations].filter(Boolean);

  // 公司摘要（industry + positions 概要）
  const summaryText =
    `${record.industry}行业，共${positionsList.length}个岗位` +
    (workLocations.length > 0 ? `，覆盖${workLocations.join("、")}等地` : "");

  // 适合关注的人群（基于 industry 推导）
  const suitableFor = INDUSTRY_SUITABLE[record.industry] || [
    `${record.industry}相关专业应届生`,
    "对相关行业有热情的候选人",
    "具备专业技能的优秀毕业生",
  ];

  return (
    <div className="min-h-screen bg-[var(--color-bg)]">
      <LandingNav activeKey="campus" />

      <div className="max-w-7xl mx-auto px-6 py-6">
        {/* ── 面包屑 ── */}
        <nav className="flex items-center gap-1.5 text-xs text-[var(--color-text-muted)] mb-6">
          <button
            onClick={() => navigate("/")}
            className="hover:text-brand transition-colors cursor-pointer"
          >
            首页
          </button>
          <CaretRight size={10} />
          <button
            onClick={() => navigate("/campus")}
            className="hover:text-brand transition-colors cursor-pointer"
          >
            校招信息
          </button>
          <CaretRight size={10} />
          <span className="text-[var(--color-text)] font-medium truncate max-w-[300px]">
            {record.company}
            {record.title ? ` · ${record.title}` : ""}
          </span>
        </nav>

        {/* ── 主体：左栏 + 右栏 ── */}
        <div className="flex flex-col lg:flex-row gap-8 mb-16">
          {/* ── 左栏：招聘公告（白底卡片，不跟随主题） ── */}
          <div className="flex-[3] min-w-0">
            <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-6 md:p-8">
              {/* 公司名 + 公告标题 + 发布时间 */}
              <div className="mb-6">
                <h1 className="text-xl font-bold text-gray-900 leading-snug mb-2">
                  {record.title || `${record.company}校园招聘`}
                </h1>
                <div className="flex items-center gap-3 text-xs text-gray-400">
                  <span className="inline-flex items-center gap-1">
                    <Building size={13} className="text-gray-400" />
                    {record.company}
                  </span>
                  <span className="inline-flex items-center gap-1">
                    <CalendarBlank size={13} className="text-gray-400" />
                    {formatDate(publishDate)}
                  </span>
                </div>
              </div>

              {/* 企业简介（用 remarks 字段） */}
              <div className="mb-6">
                <h2 className="text-sm font-bold text-gray-800 mb-3 pb-2 border-b border-gray-100">
                  企业简介
                </h2>
                <p className="text-sm text-gray-600 leading-relaxed">
                  {record.remarks || "暂无详细介绍"}
                </p>
              </div>

              {/* 招聘岗位（解析 positions 为列表） */}
              {positionsList.length > 0 && (
                <div className="mb-6">
                  <h2 className="text-sm font-bold text-gray-800 mb-3 pb-2 border-b border-gray-100">
                    招聘岗位
                  </h2>
                  <div className="flex flex-wrap gap-2">
                    {positionsList.map((pos) => (
                      <span
                        key={pos}
                        className="px-3 py-1.5 rounded-lg bg-gray-50 border border-gray-100 text-sm text-gray-700"
                      >
                        {pos}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* 工作地点 */}
              <div className="mb-6">
                <h2 className="text-sm font-bold text-gray-800 mb-3 pb-2 border-b border-gray-100">
                  工作地点
                </h2>
                <div className="flex flex-wrap gap-2">
                  {workLocations.length > 0 ? (
                    workLocations.map((loc) => (
                      <span
                        key={loc}
                        className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg bg-gray-50 border border-gray-100 text-sm text-gray-700"
                      >
                        <MapPin size={12} className="text-gray-400" />
                        {loc}
                      </span>
                    ))
                  ) : (
                    <span className="text-sm text-gray-400">-</span>
                  )}
                </div>
              </div>

              {/* 行业 */}
              <div className="mb-6">
                <h2 className="text-sm font-bold text-gray-800 mb-3 pb-2 border-b border-gray-100">
                  行业
                </h2>
                <span className="px-3 py-1.5 rounded-lg bg-gray-50 border border-gray-100 text-sm text-gray-700">
                  {record.industry || "-"}
                </span>
              </div>

              {/* 投递方式（链接可点击） */}
              <div className="mb-2">
                <h2 className="text-sm font-bold text-gray-800 mb-3 pb-2 border-b border-gray-100">
                  投递方式
                </h2>
                {record.referralMethod ? (
                  isUrl(record.referralMethod) ? (
                    <a
                      href={record.referralMethod}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-sm text-brand hover:underline break-all"
                    >
                      {record.referralMethod}
                    </a>
                  ) : (
                    <span className="text-sm text-gray-700">
                      {record.referralMethod}
                    </span>
                  )
                ) : (
                  <span className="text-sm text-gray-400">暂无投递方式</span>
                )}
              </div>
            </div>
          </div>

          {/* ── 右栏：公司信息侧边栏（跟随主题色） ── */}
          <div className="flex-[2] max-w-md">
            {/* Logo + 公司名 */}
            <div className="flex items-center gap-4 mb-5">
              <div className="w-14 h-14 rounded-2xl bg-[var(--color-bg-secondary)] border border-[var(--color-border)] flex items-center justify-center shrink-0">
                <Building
                  size={24}
                  className="text-[var(--color-text-muted)]"
                />
              </div>
              <div>
                <h2 className="text-lg font-bold text-[var(--color-text)] display-tight">
                  {record.company}
                </h2>
                <span className="text-xs text-[var(--color-text-muted)]">
                  校园招聘
                </span>
              </div>
            </div>

            {/* 标签（infoType + 日期） */}
            <div className="flex flex-wrap gap-2 mb-5">
              {record.infoType && (
                <span className="px-2.5 py-1 rounded-full text-[11px] font-medium bg-brand/10 text-brand border border-brand/20">
                  {record.infoType}
                </span>
              )}
              {publishDate && (
                <span className="px-2.5 py-1 rounded-full text-[11px] font-medium bg-brand/10 text-brand border border-brand/20">
                  {formatDate(publishDate)}
                </span>
              )}
            </div>

            {/* 公司摘要（industry + positions 概要） */}
            <p className="text-sm text-[var(--color-text-secondary)] leading-relaxed mb-5">
              {summaryText}
            </p>

            {/* 标签云（industry + 工作地点拆分） */}
            {tagCloudItems.length > 0 && (
              <div className="flex flex-wrap gap-2 mb-5">
                {tagCloudItems.map((tag) => (
                  <span
                    key={tag}
                    className="px-2.5 py-1 rounded-full bg-gray-100 text-gray-600 text-[11px]"
                  >
                    {tag}
                  </span>
                ))}
              </div>
            )}

            {/* 核心亮点 */}
            <div className="mb-5">
              <h3 className="text-sm font-semibold text-[var(--color-text)] mb-3">
                核心亮点
              </h3>
              <div className="space-y-0 divide-y divide-[var(--color-border)]">
                {highlights.map((item) => {
                  const Icon = HIGHLIGHT_ICONS[item.label];
                  return (
                    <div
                      key={item.label}
                      className="flex items-center gap-3 py-2.5"
                    >
                      {Icon && (
                        <div className="w-8 h-8 rounded-lg bg-brand/10 flex items-center justify-center shrink-0">
                          <Icon size={15} className="text-brand" />
                        </div>
                      )}
                      <div className="min-w-0">
                        <div className="text-[10px] text-[var(--color-text-muted)] leading-tight">
                          {item.label}
                        </div>
                        <div className="text-xs font-medium text-[var(--color-text)] leading-tight mt-0.5">
                          {item.value}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* 适合关注的人群（基于 industry 推导） */}
            <div className="mb-6">
              <h3 className="text-sm font-semibold text-[var(--color-text)] mb-3 inline-flex items-center gap-1.5">
                <Users size={14} className="text-brand" />
                适合关注的人群
              </h3>
              <div className="space-y-2">
                {suitableFor.map((item, i) => (
                  <div
                    key={i}
                    className="flex items-start gap-2 text-xs text-[var(--color-text-secondary)]"
                  >
                    <span className="w-1 h-1 rounded-full bg-brand mt-1.5 shrink-0" />
                    {item}
                  </div>
                ))}
              </div>
            </div>

            {/* CTA 按钮 */}
            <div className="space-y-3">
              <button
                onClick={() => navigate("/resumes/new")}
                className="w-full flex items-center justify-center gap-2 py-3 rounded-xl bg-brand text-white text-sm font-semibold
                  hover:bg-[#0077ed] hover:scale-[1.02] active:scale-[0.98]
                  transition-all duration-300 cursor-pointer"
              >
                创建简历并投递
              </button>
              <button
                onClick={() => navigate("/qa")}
                className="w-full flex items-center justify-center gap-2 py-3 rounded-xl bg-[var(--color-bg-secondary)] border border-[var(--color-border)] text-sm font-medium text-[var(--color-text-secondary)]
                  hover:bg-[#E5E5EA] hover:scale-[1.02] active:scale-[0.98]
                  transition-all duration-300 cursor-pointer"
              >
                网申通过率测试
              </button>
            </div>
          </div>
        </div>

        {/* ── 上/下一个校招导航 ── */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-5 mb-16">
          {prevRecord ? (
            <button
              onClick={() => navigate(`/campus/${prevRecord.id}`)}
              className="glass-card p-5 text-left hover:-translate-y-1 hover:shadow-xl transition-all duration-400 cursor-pointer group"
            >
              <div className="flex items-center gap-1.5 text-xs text-[var(--color-text-muted)] mb-2">
                <CaretLeft
                  size={12}
                  className="group-hover:-translate-x-1 transition-transform"
                />
                上一个校招
              </div>
              <h3 className="text-sm font-semibold text-[var(--color-text)] leading-snug">
                {prevRecord.company}
                {prevRecord.title ? ` · ${prevRecord.title}` : ""}
              </h3>
              <span className="text-[10px] text-[var(--color-text-muted)]">
                {prevRecord.industry}
              </span>
            </button>
          ) : (
            <div />
          )}
          {nextRecord ? (
            <button
              onClick={() => navigate(`/campus/${nextRecord.id}`)}
              className="glass-card p-5 text-right hover:-translate-y-1 hover:shadow-xl transition-all duration-400 cursor-pointer group"
            >
              <div className="flex items-center justify-end gap-1.5 text-xs text-[var(--color-text-muted)] mb-2">
                下一个校招
                <CaretRight
                  size={12}
                  className="group-hover:translate-x-1 transition-transform"
                />
              </div>
              <h3 className="text-sm font-semibold text-[var(--color-text)] leading-snug">
                {nextRecord.company}
                {nextRecord.title ? ` · ${nextRecord.title}` : ""}
              </h3>
              <span className="text-[10px] text-[var(--color-text-muted)]">
                {nextRecord.industry}
              </span>
            </button>
          ) : (
            <div />
          )}
        </div>

        {/* ── 推荐校招 ── */}
        {recommended.length > 0 && (
          <div className="mb-16">
            <h2 className="text-lg font-bold text-[var(--color-text)] text-center mb-6">
              更多校招信息
            </h2>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
              {recommended.map((item) => (
                <div
                  key={item.id}
                  className="glass-card overflow-hidden hover:-translate-y-1 hover:shadow-xl transition-all duration-400 cursor-pointer group"
                  onClick={() => navigate(`/campus/${item.id}`)}
                >
                  <div className="p-4">
                    <div className="flex items-center gap-3 mb-3">
                      <div className="w-10 h-10 rounded-xl bg-[var(--color-bg-secondary)] border border-[var(--color-border)] flex items-center justify-center shrink-0">
                        <Building
                          size={18}
                          className="text-[var(--color-text-muted)]"
                        />
                      </div>
                      <div className="min-w-0">
                        <h3 className="text-sm font-semibold text-[var(--color-text)] leading-snug truncate">
                          {item.company}
                        </h3>
                        <span className="text-[10px] text-[var(--color-text-muted)]">
                          {item.industry}
                        </span>
                      </div>
                    </div>
                    <p className="text-xs text-[var(--color-text-secondary)] leading-relaxed line-clamp-2 mb-3">
                      {item.title || `${item.company}校园招聘`}
                    </p>
                    <div className="flex flex-wrap gap-1.5">
                      {item.infoType && (
                        <span className="px-2 py-0.5 rounded bg-brand/10 text-brand text-[10px]">
                          {item.infoType}
                        </span>
                      )}
                      {parseList(item.positions)
                        .slice(0, 2)
                        .map((pos) => (
                          <span
                            key={pos}
                            className="px-2 py-0.5 rounded bg-gray-100 text-gray-600 text-[10px]"
                          >
                            {pos}
                          </span>
                        ))}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
