/**
 * ContentSection — 简历模板 / 简历范文 / 求职攻略 共享内容区。
 *
 * 通过 activeTab 切换三类内容（Tab 栏可在三者间跳转），
 * 含分类 Tab、标签筛选、搜索和卡片网格。
 * 数据源：模板 → /api/v1/market/templates；范文 → /api/v1/market/samples；攻略 → /api/v1/market/guides
 */

import { useState, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import {
  CaretRight,
  MagnifyingGlass,
} from "@phosphor-icons/react";
import { listSamples, listTemplates, listGuides } from "../api/market";
import type { ResumeSample, MarketTemplate, MarketGuideItem } from "../api/market";

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

// ── 工具函数 ──

function formatDate(iso?: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso.slice(0, 10);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

// ── 模板预览（iframe srcDoc + transform scale 缩放适配） ──

const PREVIEW_BASE_WIDTH = 800;

function TemplatePreview({ html }: { html: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(1);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const update = () => {
      if (el.clientWidth > 0) setScale(el.clientWidth / PREVIEW_BASE_WIDTH);
    };
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  if (!html) {
    return <div className="aspect-[3/4] w-full bg-[var(--color-bg-secondary)]" />;
  }

  return (
    <div
      ref={ref}
      className="aspect-[3/4] w-full overflow-hidden relative bg-[var(--color-bg-secondary)]"
    >
      <div
        className="absolute top-0 left-0 origin-top-left"
        style={{
          width: PREVIEW_BASE_WIDTH,
          height: Math.ceil((PREVIEW_BASE_WIDTH * 4) / 3),
          transform: `scale(${scale})`,
        }}
      >
        <iframe
          srcDoc={html}
          scrolling="no"
          title="模板预览"
          className="w-full h-full border-0"
        />
      </div>
    </div>
  );
}

// ── 组件 ──

export default function ContentSection({ activeTab }: { activeTab: ContentTabKey }) {
  const navigate = useNavigate();
  const [category, setCategory] = useState("hot");
  const [tagFilter, setTagFilter] = useState("all");
  const [query, setQuery] = useState("");
  const [apiSamples, setApiSamples] = useState<ResumeSample[]>([]);
  const [apiTemplates, setApiTemplates] = useState<MarketTemplate[]>([]);
  const [apiTips, setApiTips] = useState<MarketGuideItem[]>([]);
  const [apiLoading, setApiLoading] = useState(false);

  useEffect(() => {
    if (activeTab === "examples") {
      setApiLoading(true);
      listSamples({ page: 1, limit: 12 })
        .then((data) => setApiSamples(data.items))
        .catch(() => setApiSamples([]))
        .finally(() => setApiLoading(false));
    } else if (activeTab === "templates") {
      setApiLoading(true);
      listTemplates()
        .then((data) => setApiTemplates(data.items))
        .catch(() => setApiTemplates([]))
        .finally(() => setApiLoading(false));
    } else if (activeTab === "tips") {
      setApiLoading(true);
      listGuides({ page: 1, limit: 12 })
        .then((data) => setApiTips(data.items))
        .catch(() => setApiTips([]))
        .finally(() => setApiLoading(false));
    }
  }, [activeTab]);

  const tabs = [
    { key: "templates", label: "简历模板", route: "/templates" },
    { key: "examples", label: "简历范文", route: "/examples" },
    { key: "tips", label: "求职攻略", route: "/tips" },
  ];

  const tab = tabs.find((t) => t.key === activeTab) ?? tabs[0];

  // 模板前端过滤：搜索（name/tags/description 模糊）+ 标签筛选
  const filteredTemplates = apiTemplates.filter((t) => {
    const q = query.trim().toLowerCase();
    if (q) {
      const hay = `${t.name} ${(t.tags ?? []).join(" ")} ${t.description ?? ""}`.toLowerCase();
      if (!hay.includes(q)) return false;
    }
    if (tagFilter !== "all") {
      const label = TAG_FILTERS.find((x) => x.key === tagFilter)?.label ?? "";
      if (label && !(t.tags ?? []).some((tag) => tag.includes(label))) return false;
    }
    return true;
  });

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
          {apiTips.map((item) => (
            <div
              key={item.id}
              onClick={() => navigate(`/guides/${item.id}`)}
              className="glass-card p-5 hover:-translate-y-1 hover:shadow-xl hover:shadow-black/5 transition-all duration-400 cursor-pointer animate-fade-in-up"
            >
              <p className="text-[10px] text-[var(--color-text-muted)] mb-2">{formatDate(item.date) || "-"}</p>
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
      ) : apiLoading ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="glass-card overflow-hidden animate-pulse">
              <div className="aspect-[3/4] bg-gray-200" />
              <div className="p-4">
                <div className="h-4 bg-gray-200 rounded w-3/4 mb-2" />
                <div className="h-3 bg-gray-200 rounded w-1/2" />
              </div>
            </div>
          ))}
        </div>
      ) : filteredTemplates.length === 0 ? (
        <div className="text-center py-16 text-[var(--color-text-muted)] text-sm">
          暂无模板数据
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
          {filteredTemplates.map((item) => (
            <div
              key={item.id}
              onClick={() => navigate(`/templates/${item.id}`)}
              className="glass-card overflow-hidden hover:-translate-y-1 hover:shadow-xl hover:shadow-black/5 transition-all duration-400 cursor-pointer group animate-fade-in-up"
            >
              {/* 预览区（iframe srcDoc + 缩放） */}
              <TemplatePreview html={item.preview_html} />

              {/* 信息区 */}
              <div className="p-4">
                <h3 className="text-sm font-semibold text-[var(--color-text)] leading-snug mb-2 line-clamp-2 min-h-[2.5rem]">
                  {item.name}
                </h3>
                {item.description && (
                  <p className="text-[10px] text-[var(--color-text-muted)] leading-relaxed line-clamp-2 mb-3">
                    {item.description}
                  </p>
                )}
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-1.5 flex-wrap min-w-0">
                    {(item.tags ?? []).slice(0, 3).map((tag) => (
                      <span
                        key={tag}
                        className="px-2 py-0.5 rounded text-[10px] bg-[var(--color-bg-secondary)] text-[var(--color-text-muted)] border border-[var(--color-border)]"
                      >
                        {tag}
                      </span>
                    ))}
                    {(item.tags ?? []).length > 3 && (
                      <span className="text-[10px] text-[var(--color-text-muted)]">
                        +{(item.tags ?? []).length - 3}
                      </span>
                    )}
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
