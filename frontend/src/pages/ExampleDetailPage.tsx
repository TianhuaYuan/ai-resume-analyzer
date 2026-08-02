/**
 * ExampleDetailPage — 简历范文详情页（真实 API 数据）。
 *
 * 路由：/examples/:id
 * 左栏：完整简历内容预览（白底卡片，不跟随主题）——从 payload.modules 渲染
 * 右栏：标签 + 标题 + 元信息 + 描述 + 相关标签 + 核心亮点 + 适用人群 + CTA
 * 底部：上/下一个范文导航 + 推荐范文网格
 */

import { useEffect, useState, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  CaretLeft,
  CaretRight,
  FilePlus,
  Briefcase,
  Buildings,
  UserCircle,
  Spinner,
} from "@phosphor-icons/react";
import LandingNav from "../components/LandingNav";
import { listSamples, getSample } from "../api/market";
import type { ResumeSample, ResumeSampleDetail } from "../api/market";
import type { ResumeModuleInput } from "../api/builder";

// ── 工具函数：从 modules 提取特定类型的模块 ──

function findModule(modules: ResumeModuleInput[] | undefined, type: string): ResumeModuleInput | undefined {
  return modules?.find((m) => m.module_type === type);
}

function findAllModules(modules: ResumeModuleInput[] | undefined, type: string): ResumeModuleInput[] {
  return modules?.filter((m) => m.module_type === type) ?? [];
}

// ── 工具函数：将 description 中的换行拆为要点列表 ──

function splitPoints(desc?: string): string[] {
  if (!desc) return [];
  return desc.split("\n").map((s) => s.trim()).filter(Boolean);
}

// ── 工具函数：格式化日期范围 ──

function formatDateRange(start?: string, end?: string): string {
  const s = start ? formatShortDate(start) : "";
  const e = end ? formatShortDate(end) : "至今";
  if (!s && !e) return "";
  return `${s} ~ ${e}`;
}

function formatShortDate(d: string): string {
  // "2025-07" → "2025.07"
  const match = d.match(/^(\d{4})-?(\d{2})/);
  return match ? `${match[1]}.${match[2]}` : d;
}

function formatDateFull(dateStr?: string): string {
  if (!dateStr) return "";
  const normalized = /[Z+]/.test(dateStr) ? dateStr : dateStr + "Z";
  const d = new Date(normalized);
  if (isNaN(d.getTime())) return dateStr.slice(0, 10);
  return d.toLocaleDateString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit" });
}

// ── 左栏：简历内容组件 ──

function ResumeContent({ modules }: { modules: ResumeModuleInput[] | undefined }) {
  if (!modules || modules.length === 0) {
    return (
      <div className="w-full max-w-[420px] mx-auto">
        <div className="bg-white rounded-2xl shadow-lg border border-gray-200 p-10 text-center">
          <p className="text-gray-400 text-sm">暂无简历内容</p>
        </div>
      </div>
    );
  }

  const basicInfo = findModule(modules, "basic_info")?.content as Record<string, unknown> | undefined;
  const workExps = findAllModules(modules, "work_experience");
  const projectExps = findAllModules(modules, "project_experience");
  const educations = findAllModules(modules, "education");
  const skillsMod = findModule(modules, "skills")?.content as Record<string, unknown> | undefined;

  const name = (basicInfo?.name as string) ?? "";
  const phone = (basicInfo?.phone as string) ?? "";
  const email = (basicInfo?.email as string) ?? "";
  const city = (basicInfo?.city as string) ?? "";
  const summary = (basicInfo?.summary as string) ?? "";

  return (
    <div className="w-full max-w-[420px] mx-auto">
      <div className="bg-white rounded-2xl shadow-lg border border-gray-200 overflow-hidden">
        {/* 头部：头像 + 姓名 + 联系方式 */}
        <div className="bg-gray-50 px-6 py-5 text-center border-b border-gray-100">
          <div className="w-16 h-16 rounded-full bg-gray-200 mx-auto mb-2.5 flex items-center justify-center">
            <UserCircle size={32} className="text-gray-400" weight="thin" />
          </div>
          {name && <div className="text-lg font-bold text-gray-900">{name}</div>}
          {(city || phone || email) && (
            <div className="flex items-center justify-center gap-3 mt-1.5 text-[10px] text-gray-400">
              {city && <span>{city}</span>}
              {phone && <span>{phone}</span>}
              {email && <span>{email}</span>}
            </div>
          )}
        </div>

        {/* 简历正文 */}
        <div className="p-5 space-y-4 text-[10px] leading-relaxed text-gray-700">
          {/* 个人总结 */}
          {summary && (
            <div>
              <div className="text-[11px] font-bold text-blue-600 border-b border-blue-100 pb-1 mb-2">
                个人总结
              </div>
              <div className="text-gray-600 whitespace-pre-line">{summary}</div>
            </div>
          )}

          {/* 工作经历 */}
          {workExps.length > 0 && (
            <div>
              <div className="text-[11px] font-bold text-blue-600 border-b border-blue-100 pb-1 mb-2">
                工作经历
              </div>
              {workExps.map((mod, i) => {
                const c = mod.content as Record<string, unknown>;
                const company = (c.company as string) ?? "";
                const position = (c.position as string) ?? "";
                const period = formatDateRange(c.start_date as string, c.end_date as string);
                const points = splitPoints(c.description as string);
                return (
                  <div key={i} className="mb-2 last:mb-0">
                    <div className="flex justify-between items-start">
                      <div>
                        <span className="font-semibold text-gray-900">{company}</span>
                        {position && <span className="text-gray-500 ml-2">{position}</span>}
                      </div>
                      {period && <span className="text-gray-400 shrink-0">{period}</span>}
                    </div>
                    {points.length > 0 && (
                      <ul className="list-disc list-inside mt-1 space-y-0.5 text-gray-600">
                        {points.map((p, j) => (
                          <li key={j}>{p}</li>
                        ))}
                      </ul>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          {/* 项目经历 */}
          {projectExps.length > 0 && (
            <div>
              <div className="text-[11px] font-bold text-blue-600 border-b border-blue-100 pb-1 mb-2">
                项目经历
              </div>
              {projectExps.map((mod, i) => {
                const c = mod.content as Record<string, unknown>;
                const projectName = (c.name as string) ?? "";
                const role = (c.role as string) ?? "";
                const period = formatDateRange(c.start_date as string, c.end_date as string);
                const points = splitPoints(c.description as string);
                return (
                  <div key={i} className="mb-2 last:mb-0">
                    <div className="flex justify-between items-start">
                      <div>
                        <span className="font-semibold text-gray-900">{projectName}</span>
                        {role && <span className="text-gray-500 ml-2">{role}</span>}
                      </div>
                      {period && <span className="text-gray-400 shrink-0">{period}</span>}
                    </div>
                    {points.length > 0 && (
                      <ul className="list-disc list-inside mt-1 space-y-0.5 text-gray-600">
                        {points.map((p, j) => (
                          <li key={j}>{p}</li>
                        ))}
                      </ul>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          {/* 教育背景 */}
          {educations.length > 0 && (
            <div>
              <div className="text-[11px] font-bold text-blue-600 border-b border-blue-100 pb-1 mb-2">
                教育背景
              </div>
              {educations.map((mod, i) => {
                const c = mod.content as Record<string, unknown>;
                const school = (c.school as string) ?? "";
                const major = (c.major as string) ?? "";
                const degree = (c.degree as string) ?? "";
                const period = formatDateRange(c.start_date as string, c.end_date as string);
                return (
                  <div key={i} className="mb-2 last:mb-0">
                    <div className="flex justify-between items-start">
                      <div>
                        <span className="font-semibold text-gray-900">{school}</span>
                        {(major || degree) && (
                          <span className="text-gray-500 ml-2">{major}{major && degree ? " · " : ""}{degree}</span>
                        )}
                      </div>
                      {period && <span className="text-gray-400 shrink-0">{period}</span>}
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          {/* 技能专长 */}
          {skillsMod && (
            <div>
              <div className="text-[11px] font-bold text-blue-600 border-b border-blue-100 pb-1 mb-2">
                技能专长
              </div>
              {(() => {
                const categories = skillsMod.categories as { name: string; items: string }[] | undefined;
                if (categories && categories.length > 0) {
                  return (
                    <div className="space-y-1.5">
                      {categories.map((cat, i) => (
                        <div key={i}>
                          <span className="font-semibold text-gray-900">{cat.name}：</span>
                          <span className="text-gray-600">{cat.items}</span>
                        </div>
                      ))}
                    </div>
                  );
                }
                const desc = (skillsMod.description as string) ?? "";
                if (desc) {
                  return <div className="text-gray-600 whitespace-pre-line">{desc}</div>;
                }
                return null;
              })()}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── 主组件 ──

export default function ExampleDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [detail, setDetail] = useState<ResumeSampleDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // 上/下一个导航数据
  const [prevSample, setPrevSample] = useState<ResumeSample | null>(null);
  const [nextSample, setNextSample] = useState<ResumeSample | null>(null);

  // 推荐范文
  const [recommended, setRecommended] = useState<ResumeSample[]>([]);

  // ── 加载范文详情 ──
  const loadDetail = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    setError("");
    try {
      const data = await getSample(id);
      setDetail(data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "加载范文失败");
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    loadDetail();
  }, [loadDetail]);

  // ── 加载上/下一个 + 推荐范文 ──
  useEffect(() => {
    if (!detail) return;

    let cancelled = false;

    (async () => {
      try {
        const listRes = await listSamples({ page: 1, limit: 20 });
        if (cancelled) return;
        const items = listRes.items;
        const currentIdx = items.findIndex((s) => s.id === detail.id);
        if (currentIdx > 0) {
          setPrevSample(items[currentIdx - 1]);
        } else {
          setPrevSample(null);
        }
        if (currentIdx < items.length - 1) {
          setNextSample(items[currentIdx + 1]);
        } else {
          setNextSample(null);
        }
        // 推荐范文：排除当前 id，取前 4 个
        const rec = items.filter((s) => s.id !== detail.id).slice(0, 4);
        setRecommended(rec);
      } catch {
        // 非关键错误，静默处理
      }
    })();

    return () => { cancelled = true; };
  }, [detail]);

  // ── 从 modules 提取元数据 ──

  const modules = detail?.payload?.modules;
  const position = detail?.position ?? "";
  const category = detail?.category ?? "";

  // 核心亮点：从 modules 的 module_type 推导
  const highlights = (() => {
    if (!modules || modules.length === 0) return [];
    const types = new Set(modules.map((m) => m.module_type));
    const h: string[] = [];
    if (types.has("work_experience")) h.push("突出工作经历");
    if (types.has("project_experience")) h.push("项目经验丰富");
    if (types.has("education")) h.push("教育背景扎实");
    if (types.has("skills")) h.push("技能体系完整");
    if (types.has("honors")) h.push("荣誉奖项突出");
    if (types.has("publications")) h.push("学术成果显著");
    if (types.has("language")) h.push("语言能力优秀");
    if (types.has("certificates")) h.push("专业资质齐全");
    // 如果推导不出，给一个通用的
    if (h.length === 0 && position) h.push(`${position}岗位专用结构`);
    return h;
  })();

  // 适用人群：基于 position 推导
  const targetAudience = position
    ? `适合目标岗位为 ${position} 的应届生或转行求职者，可根据自身经历参照此范文的结构进行优化。`
    : "适合希望参考简历结构的求职者。";

  // 相关标签
  const relatedTags = (() => {
    const tags: string[] = [];
    if (position) tags.push(`#${position}`);
    if (category) tags.push(`#${category}`);
    if (modules) {
      const types = new Set(modules.map((m) => m.module_type));
      if (types.has("work_experience")) tags.push("#工作经历");
      if (types.has("project_experience")) tags.push("#项目经历");
      if (types.has("skills")) tags.push("#技能");
      if (types.has("education")) tags.push("#教育");
    }
    return tags;
  })();

  // ── Loading 状态 ──
  if (loading) {
    return (
      <div className="min-h-screen bg-[var(--color-bg)]">
        <LandingNav activeKey="examples" />
        <div className="min-h-[60vh] flex items-center justify-center">
          <Spinner size={24} className="animate-spin text-brand" />
        </div>
      </div>
    );
  }

  // ── Error 状态 ──
  if (error || !detail) {
    return (
      <div className="min-h-screen bg-[var(--color-bg)]">
        <LandingNav activeKey="examples" />
        <div className="max-w-7xl mx-auto px-6 py-20 text-center">
          <p className="text-red-500 text-sm mb-4">{error || "范文不存在"}</p>
          <button
            onClick={() => navigate("/examples")}
            className="text-brand text-sm hover:underline cursor-pointer"
          >
            返回范文列表
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[var(--color-bg)]">
      <LandingNav activeKey="examples" />

      <div className="max-w-7xl mx-auto px-6 py-6">
        {/* 面包屑 */}
        <nav className="flex items-center gap-1.5 text-xs text-[var(--color-text-muted)] mb-6">
          <button
            onClick={() => navigate("/")}
            className="hover:text-brand transition-colors cursor-pointer"
          >
            首页
          </button>
          <CaretRight size={10} />
          <button
            onClick={() => navigate("/examples")}
            className="hover:text-brand transition-colors cursor-pointer"
          >
            简历范文
          </button>
          <CaretRight size={10} />
          <span className="text-[var(--color-text)] font-medium truncate max-w-[300px]">
            {detail.title}
          </span>
        </nav>

        {/* 主体：左栏简历 + 右栏信息 */}
        <div className="flex flex-col lg:flex-row gap-10 mb-16">
          {/* 左栏：完整简历内容 */}
          <div className="flex-1 flex justify-center">
            <ResumeContent modules={modules} />
          </div>

          {/* 右栏：范文信息 */}
          <div className="flex-1 max-w-lg">
            {/* 标签行 */}
            <div className="flex items-center gap-2 mb-3">
              {category && (
                <span className="px-2.5 py-1 rounded-full text-[10px] font-medium bg-brand/10 text-brand border border-brand/20">
                  {category}
                </span>
              )}
              {detail.created_at && (
                <span className="text-xs text-[var(--color-text-muted)] tabular-nums">
                  {formatDateFull(detail.created_at)}
                </span>
              )}
            </div>

            {/* 标题 */}
            <h1 className="text-2xl font-bold text-[var(--color-text)] leading-tight display-tight mb-3">
              {detail.title}
            </h1>

            {/* 元信息 */}
            <div className="flex items-center gap-4 mb-5 text-xs text-[var(--color-text-secondary)]">
              {position && (
                <span className="inline-flex items-center gap-1">
                  <Briefcase size={13} weight="duotone" className="text-brand" />
                  {position}
                </span>
              )}
              {category && (
                <span className="inline-flex items-center gap-1">
                  <Buildings size={13} weight="duotone" className="text-brand" />
                  {category}
                </span>
              )}
              <span className="inline-flex items-center gap-1">
                <UserCircle size={13} weight="duotone" className="text-brand" />
                应届生
              </span>
            </div>

            {/* 描述 */}
            <p className="text-sm text-[var(--color-text-secondary)] leading-relaxed mb-6">
              {category}{position ? ` · ${position}` : ""}——专为求职者打造的简历范文参考。
            </p>

            {/* 相关标签 */}
            {relatedTags.length > 0 && (
              <div className="flex flex-wrap gap-2 mb-6">
                {relatedTags.map((t) => (
                  <span
                    key={t}
                    className="px-3 py-1.5 rounded-full text-xs font-medium bg-[var(--color-bg-secondary)] text-[var(--color-text-secondary)] border border-[var(--color-border)]"
                  >
                    {t}
                  </span>
                ))}
              </div>
            )}

            {/* 核心亮点 */}
            {highlights.length > 0 && (
              <>
                <h2 className="text-base font-semibold text-[var(--color-text)] mb-3">
                  核心亮点
                </h2>
                <div className="flex flex-wrap gap-2 mb-6">
                  {highlights.map((h) => (
                    <span
                      key={h}
                      className="px-3 py-1.5 rounded-full text-xs font-medium bg-brand/10 text-brand border border-brand/20"
                    >
                      {h}
                    </span>
                  ))}
                </div>
              </>
            )}

            {/* 适用人群 */}
            <h2 className="text-base font-semibold text-[var(--color-text)] mb-3">
              适用人群
            </h2>
            <p className="text-sm text-[var(--color-text-secondary)] leading-relaxed mb-6 p-4 rounded-xl bg-[var(--color-bg-secondary)] border border-[var(--color-border)]">
              {targetAudience}
            </p>

            {/* CTA 按钮 */}
            <button
              onClick={() => navigate("/examples")}
              className="w-full flex items-center justify-center gap-2 py-3.5 rounded-xl bg-brand text-white font-semibold text-sm
                hover:bg-[#0077ed] hover:scale-[1.02] active:scale-[0.98]
                transition-all duration-300 cursor-pointer"
            >
              <FilePlus size={16} weight="bold" />
              使用范文创建简历
            </button>
          </div>
        </div>

        {/* 上/下一个范文 */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-5 mb-16">
          {prevSample ? (
            <button
              onClick={() => navigate(`/examples/${prevSample.id}`)}
              className="glass-card p-5 text-left hover:-translate-y-1 hover:shadow-xl transition-all duration-400 cursor-pointer group"
            >
              <div className="flex items-center gap-1.5 text-xs text-[var(--color-text-muted)] mb-2">
                <CaretLeft
                  size={12}
                  className="group-hover:-translate-x-1 transition-transform"
                />
                上一个范文
              </div>
              <h3 className="text-sm font-semibold text-[var(--color-text)] leading-snug">
                {prevSample.title}
              </h3>
              {prevSample.position && (
                <span className="text-[10px] text-[var(--color-text-muted)] mt-1 inline-block">
                  <Briefcase size={10} className="inline -mt-px mr-0.5" weight="duotone" />
                  {prevSample.position}
                </span>
              )}
            </button>
          ) : (
            <div />
          )}
          {nextSample ? (
            <button
              onClick={() => navigate(`/examples/${nextSample.id}`)}
              className="glass-card p-5 text-right hover:-translate-y-1 hover:shadow-xl transition-all duration-400 cursor-pointer group"
            >
              <div className="flex items-center justify-end gap-1.5 text-xs text-[var(--color-text-muted)] mb-2">
                下一个范文
                <CaretRight
                  size={12}
                  className="group-hover:translate-x-1 transition-transform"
                />
              </div>
              <h3 className="text-sm font-semibold text-[var(--color-text)] leading-snug">
                {nextSample.title}
              </h3>
              {nextSample.position && (
                <span className="text-[10px] text-[var(--color-text-muted)] mt-1 inline-block">
                  <Briefcase size={10} className="inline -mt-px mr-0.5" weight="duotone" />
                  {nextSample.position}
                </span>
              )}
            </button>
          ) : (
            <div />
          )}
        </div>

        {/* 推荐范文 */}
        {recommended.length > 0 && (
          <div className="mb-16">
            <h2 className="text-lg font-bold text-[var(--color-text)] text-center mb-6">
              推荐范文
            </h2>
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-5">
              {recommended.map((ex) => (
                <div
                  key={ex.id}
                  className="glass-card p-5 hover:-translate-y-1 hover:shadow-xl transition-all duration-400 cursor-pointer group"
                  onClick={() => navigate(`/examples/${ex.id}`)}
                >
                  <h3 className="text-sm font-semibold text-[var(--color-text)] leading-snug line-clamp-2 mb-2">
                    {ex.title}
                  </h3>
                  <div className="flex flex-wrap gap-1.5 mb-2">
                    {ex.category && (
                      <span
                        className="px-2 py-0.5 rounded text-[9px] font-medium bg-brand/10 text-brand"
                      >
                        {ex.category}
                      </span>
                    )}
                  </div>
                  {ex.position && (
                    <p className="text-[10px] text-[var(--color-text-muted)] line-clamp-2 leading-relaxed">
                      目标岗位：{ex.position}
                    </p>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
