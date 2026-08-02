/**
 * ContentSection — 简历模板 / 简历范文 / 求职攻略 共享内容区。
 *
 * 通过 activeTab 切换三类内容（Tab 栏可在三者间跳转），
 * 含分类 Tab、标签筛选、搜索和卡片网格。数据暂为 Mock，后续替换为接口。
 */

import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import {
  CaretRight,
  MagnifyingGlass,
} from "@phosphor-icons/react";
import { listSamples } from "../api/market";
import type { ResumeSample } from "../api/market";

export type ContentTabKey = "templates" | "examples" | "tips";

// ── 分类 Tab ──

const CATEGORY_TABS = [
  { key: "hot", label: "热门" },
  { key: "industry", label: "行业" },
  { key: "position", label: "职位" },
  { key: "major", label: "专业" },
  { key: "niche", label: "冷门岗位" },
];

// ── 标签筛选 ──

const TAG_FILTERS = [
  { key: "all", label: "全部" },
  { key: "fresh", label: "应届生简历" },
  { key: "intern", label: "实习生简历" },
  { key: "aigc", label: "AIGC创作者" },
  { key: "prompt", label: "提示词工程师" },
  { key: "ai", label: "AI助手开发" },
  { key: "pm", label: "产品经理简历" },
  { key: "dev", label: "程序员简历" },
  { key: "design", label: "设计师简历" },
  { key: "data", label: "数据分析师" },
  { key: "1y", label: "1-3年经验" },
  { key: "3y", label: "3-5年经验" },
  { key: "career", label: "转行简历" },
  { key: "job", label: "跳槽简历" },
  { key: "campus", label: "校招简历" },
  { key: "social", label: "社招简历" },
];

// ── Mock 数据：简历模板 ──

const MOCK_TEMPLATES = [
  {
    id: 1,
    title: "仿真算法工程师简历模板（高端制造/航空航天校招）",
    tags: ["应届生简历", "机械类"],
    extraTags: 2,
    count: 622,
    colors: ["from-blue-500/20 to-indigo-500/10", "bg-blue-500/30"],
  },
  {
    id: 2,
    title: "技术支持工程师（FAE）简历模板 - 半导体/企业服务校招专用",
    tags: ["电子信息类", "程序员简历"],
    extraTags: 2,
    count: 816,
    colors: ["from-emerald-500/20 to-teal-500/10", "bg-emerald-500/30"],
  },
  {
    id: 3,
    title: "算法工程师（大模型/AI方向）简历模板 - 互联网校招专用",
    tags: ["AI人工智能", "应届生简历"],
    extraTags: 3,
    count: 618,
    colors: ["from-violet-500/20 to-purple-500/10", "bg-violet-500/30"],
  },
  {
    id: 4,
    title: "产品经理（应用/供应链方向）校招简历模板-互联网智能制造",
    tags: ["互联网", "产品经理"],
    extraTags: 3,
    count: 891,
    colors: ["from-amber-500/20 to-orange-500/10", "bg-amber-500/30"],
  },
  {
    id: 5,
    title: "前端开发工程师简历模板 - React/Vue方向",
    tags: ["程序员简历", "应届生简历"],
    extraTags: 1,
    count: 745,
    colors: ["from-cyan-500/20 to-sky-500/10", "bg-cyan-500/30"],
  },
  {
    id: 6,
    title: "数据分析师简历模板 - 互联网/金融方向",
    tags: ["数据分析师", "应届生简历"],
    extraTags: 2,
    count: 534,
    colors: ["from-rose-500/20 to-pink-500/10", "bg-rose-500/30"],
  },
  {
    id: 7,
    title: "UI/UX设计师简历模板 - 互联网/设计方向",
    tags: ["设计师简历", "应届生简历"],
    extraTags: 1,
    count: 467,
    colors: ["from-fuchsia-500/20 to-pink-500/10", "bg-fuchsia-500/30"],
  },
  {
    id: 8,
    title: "嵌入式软件工程师简历模板 - 智能硬件/机器人校招",
    tags: ["电子信息类", "应届生简历"],
    extraTags: 2,
    count: 389,
    colors: ["from-teal-500/20 to-emerald-500/10", "bg-teal-500/30"],
  },
];

// ── 工具函数 ──

function formatDate(iso: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

// ── Mock 数据：求职攻略 ──

const MOCK_TIPS = [
  {
    id: 1,
    title: "2026秋招技术岗求职攻略：从简历到面试全流程",
    date: "2026-08-01",
    summary: "涵盖简历制作、面试准备、薪资谈判等全方位指导，帮助应届生顺利斩获心仪 offer。",
    count: 1024,
    colors: ["from-blue-500/20 to-indigo-500/10", "bg-blue-500/30"],
  },
  {
    id: 2,
    title: "AI岗位求职指南：如何准备大模型/AI方向的校招面试",
    date: "2026-07-30",
    summary: "从 LLM 基础到工程实践，全面梳理 AI 方向校招面试的核心知识点和常见问题。",
    count: 876,
    colors: ["from-violet-500/20 to-purple-500/10", "bg-violet-500/30"],
  },
  {
    id: 3,
    title: "简历关键词优化：如何通过 ATS 机筛",
    date: "2026-07-28",
    summary: "解析主流 ATS 系统的工作原理，教你如何优化简历关键词、格式和内容结构。",
    count: 654,
    colors: ["from-emerald-500/20 to-teal-500/10", "bg-emerald-500/30"],
  },
];

// ── 组件 ──

export default function ContentSection({ activeTab }: { activeTab: ContentTabKey }) {
  const navigate = useNavigate();
  const [category, setCategory] = useState("hot");
  const [tagFilter, setTagFilter] = useState("all");
  const [query, setQuery] = useState("");
  const [apiSamples, setApiSamples] = useState<ResumeSample[]>([]);
  const [apiLoading, setApiLoading] = useState(false);

  useEffect(() => {
    if (activeTab === "examples") {
      setApiLoading(true);
      listSamples({ page: 1, limit: 12 })
        .then((data) => setApiSamples(data.items))
        .catch(() => setApiSamples([]))
        .finally(() => setApiLoading(false));
    }
  }, [activeTab]);

  const tabs = [
    { key: "templates", label: "简历模板", route: "/templates" },
    { key: "examples", label: "简历范文", route: "/examples" },
    { key: "tips", label: "求职攻略", route: "/tips" },
  ];

  const tab = tabs.find((t) => t.key === activeTab) ?? tabs[0];

  const currentData =
    tab.key === "templates"
      ? MOCK_TEMPLATES
      : tab.key === "tips"
        ? MOCK_TIPS
        : [];

  return (
    <div className="max-w-7xl mx-auto px-6 py-8">
      {/* 内容 Tab 栏 */}
      <div className="flex items-center gap-1 mb-6 border-b border-[var(--color-border)]">
        {tabs.map((t) => (
          <button
            key={t.key}
            onClick={() => navigate(t.route)}
            className={`px-5 py-2.5 text-sm font-medium transition-all duration-300 cursor-pointer border-b-2 -mb-px
              ${activeTab === t.key
                ? "text-brand border-brand"
                : "text-[var(--color-text-muted)] border-transparent hover:text-[var(--color-text-secondary)]"
              }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* 分类 Tab + 查看更多 */}
      <div className="flex items-center justify-between mb-5">
        <div className="flex items-center gap-2 overflow-x-auto">
          {CATEGORY_TABS.map((cat) => (
            <button
              key={cat.key}
              onClick={() => setCategory(cat.key)}
              className={`px-4 py-2 rounded-full text-sm font-medium transition-all duration-300 cursor-pointer whitespace-nowrap
                ${category === cat.key
                  ? "bg-brand text-white shadow-md shadow-brand/25"
                  : "text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-secondary)]"
                }`}
            >
              {cat.label}
            </button>
          ))}
        </div>
        <button className="inline-flex items-center gap-1 text-sm text-[var(--color-text-muted)] hover:text-brand transition-colors cursor-pointer shrink-0 ml-3">
          查看更多 <CaretRight size={14} />
        </button>
      </div>

      {/* 标签筛选 + 搜索 */}
      <div className="flex items-center gap-3 mb-6">
        <div className="flex flex-wrap gap-2 flex-1">
          {TAG_FILTERS.map((tag) => (
            <button
              key={tag.key}
              onClick={() => setTagFilter(tag.key)}
              className={`px-3 py-1.5 rounded-full text-xs font-medium transition-all duration-300 cursor-pointer
                ${tagFilter === tag.key
                  ? "bg-brand/10 text-brand border border-brand/30"
                  : "bg-[var(--color-bg-secondary)] text-[var(--color-text-muted)] border border-transparent hover:border-[var(--color-border)]"
                }`}
            >
              {tag.label}
            </button>
          ))}
        </div>
        <div className="relative shrink-0">
          <MagnifyingGlass size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--color-text-muted)]" />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={`搜索${tab.label}...`}
            className="pl-9 pr-3 py-2 rounded-xl bg-[#F2F2F7] border border-transparent
              text-sm text-[var(--color-text)] placeholder:text-[var(--color-text-muted)]
              focus:outline-none focus:bg-white focus:border-brand/40 focus:ring-4 focus:ring-brand/15
              transition-all duration-200 w-48"
          />
        </div>
      </div>

      {/* 卡片网格 */}
      {tab.key === "tips" ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
          {(currentData as typeof MOCK_TIPS).map((item) => (
            <div
              key={item.id}
              className="glass-card p-5 hover:-translate-y-1 hover:shadow-xl hover:shadow-black/5 transition-all duration-400 cursor-pointer animate-fade-in-up"
            >
              <p className="text-[10px] text-[var(--color-text-muted)] mb-2">{item.date}</p>
              <h3 className="text-sm font-semibold text-[var(--color-text)] mb-2 leading-snug">
                {item.title}
              </h3>
              <p className="text-xs text-[var(--color-text-muted)] leading-relaxed mb-4 line-clamp-3">
                {item.summary}
              </p>
              <div className="flex items-center justify-between">
                <span className="inline-flex items-center gap-1 text-xs text-brand hover:underline">
                  阅读全文 <CaretRight size={12} />
                </span>
                <span className="text-xs text-orange-500 tabular-nums">
                  🔥 {item.count}
                </span>
              </div>
            </div>
          ))}
        </div>
      ) : tab.key === "examples" ? (
        apiLoading ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
            {Array.from({ length: 8 }).map((_, i) => (
              <div key={i} className="glass-card p-5 animate-pulse">
                <div className="h-4 bg-gray-200 rounded w-3/4 mb-3" />
                <div className="h-3 bg-gray-200 rounded w-1/2 mb-4" />
                <div className="flex items-center justify-between">
                  <div className="h-5 bg-gray-200 rounded w-16" />
                  <div className="h-3 bg-gray-200 rounded w-20" />
                </div>
              </div>
            ))}
          </div>
        ) : apiSamples.length === 0 ? (
          <div className="text-center py-16 text-[var(--color-text-muted)] text-sm">
            暂无范文数据
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
            {apiSamples.map((item) => (
              <div
                key={item.id}
                onClick={() => navigate(`/examples/${item.id}`)}
                className="glass-card p-5 hover:-translate-y-1 hover:shadow-xl transition-all cursor-pointer animate-fade-in-up"
              >
                <h3 className="text-sm font-semibold text-[var(--color-text)] mb-2 line-clamp-2">
                  {item.title}
                </h3>
                <p className="text-xs text-[var(--color-text-muted)] mb-3">{item.position}</p>
                <div className="flex items-center justify-between">
                  <span className="px-2 py-0.5 rounded text-[10px] bg-brand/10 text-brand">{item.category}</span>
                  <span className="text-[10px] text-[var(--color-text-muted)]">{formatDate(item.created_at)}</span>
                </div>
              </div>
            ))}
          </div>
        )
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
          {(currentData as typeof MOCK_TEMPLATES).map((item) => (
            <div
              key={item.id}
              onClick={() => navigate(`/templates/${item.id}`)}
              className="glass-card overflow-hidden hover:-translate-y-1 hover:shadow-xl hover:shadow-black/5 transition-all duration-400 cursor-pointer group animate-fade-in-up"
            >
              {/* 预览区 */}
              <div className={`aspect-[3/4] bg-gradient-to-br ${item.colors[0]} p-4 flex flex-col justify-between`}>
                {/* 模拟简历内容 */}
                <div className="bg-white rounded-lg shadow-sm p-3 flex-1 overflow-hidden">
                  <div className="flex items-center gap-2 mb-2">
                    <div className="w-6 h-6 rounded-full bg-gray-200" />
                    <div>
                      <div className="w-12 h-1.5 bg-gray-300 rounded" />
                      <div className="w-8 h-1 bg-gray-200 rounded mt-0.5" />
                    </div>
                  </div>
                  {[...Array(6)].map((_, i) => (
                    <div key={i} className="flex gap-1 mb-1">
                      <div className={`h-1 rounded ${i % 3 === 0 ? "w-full" : i % 3 === 1 ? "w-3/4" : "w-1/2"} bg-gray-200`} />
                    </div>
                  ))}
                  <div className="mt-2 flex gap-1">
                    <div className={`h-1 rounded ${item.colors[1]} w-8`} />
                    <div className="h-1 rounded bg-gray-200 w-16" />
                  </div>
                  {[...Array(4)].map((_, i) => (
                    <div key={i} className="flex gap-1 mb-0.5 mt-0.5">
                      <div className="h-1 rounded bg-gray-200" style={{ width: `${60 + Math.random() * 30}%` }} />
                    </div>
                  ))}
                </div>
              </div>

              {/* 信息区 */}
              <div className="p-4">
                <h3 className="text-sm font-semibold text-[var(--color-text)] leading-snug mb-3 line-clamp-2 min-h-[2.5rem]">
                  {item.title}
                </h3>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-1.5 flex-wrap min-w-0">
                    {item.tags.map((tag) => (
                      <span
                        key={tag}
                        className="px-2 py-0.5 rounded text-[10px] bg-[var(--color-bg-secondary)] text-[var(--color-text-muted)] border border-[var(--color-border)]"
                      >
                        {tag}
                      </span>
                    ))}
                    {item.extraTags > 0 && (
                      <span className="text-[10px] text-[var(--color-text-muted)]">
                        +{item.extraTags}
                      </span>
                    )}
                  </div>
                  <span className="text-xs text-orange-400 shrink-0 ml-2 tabular-nums">
                    🔥 {item.count}
                  </span>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
