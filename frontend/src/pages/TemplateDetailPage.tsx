/**
 * TemplateDetailPage — 简历模板详情页。
 *
 * 路由：/templates/:id（id 为模板名，如 default / minimal）
 * 数据源：GET /api/v1/market/templates/{id}（getTemplate）+ GET /api/v1/market/templates（prev/next/recommended）
 * 左侧：preview_html iframe 预览（transform scale 缩放适配）
 * 右侧：模板名、描述、标签、布局元数据
 * CTA：已登录 → createBuilderResume({ filename, style: { template_id } })；未登录 → 弹登录
 */

import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  CaretLeft,
  CaretRight,
  Pen,
  Spinner,
} from "@phosphor-icons/react";
import LandingNav from "../components/LandingNav";
import { TemplateCardPreview } from "../components/TemplateGalleryModal";
import { useAuth } from "../context/AuthContext";
import { getTemplate, listTemplates } from "../api/market";
import type { MarketTemplate } from "../api/market";
import { createBuilderResume } from "../api/builder";
import type { ResumeStyle } from "../api/builder";

// ── 主组件 ──

export default function TemplateDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { user } = useAuth();

  const [template, setTemplate] = useState<MarketTemplate | null>(null);
  const [allTemplates, setAllTemplates] = useState<MarketTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [creating, setCreating] = useState(false);
  const [actionError, setActionError] = useState("");

  // 模板详情
  useEffect(() => {
    if (!id) return;
    setLoading(true);
    setError("");
    setTemplate(null);
    getTemplate(id)
      .then(setTemplate)
      .catch((err) =>
        setError(err instanceof Error ? err.message : "模板不存在"),
      )
      .finally(() => setLoading(false));
  }, [id]);

  // 模板列表（prev/next + recommended）
  useEffect(() => {
    listTemplates()
      .then((data) => setAllTemplates(data.items))
      .catch(() => setAllTemplates([]));
  }, []);

  // ── Loading ──
  if (loading) {
    return (
      <div className="min-h-screen bg-[var(--color-bg)]">
        <LandingNav activeKey="templates" />
        <div className="flex items-center justify-center py-40">
          <Spinner size={24} className="animate-spin text-[var(--color-text-muted)]" />
        </div>
      </div>
    );
  }

  // ── Error / Not Found ──
  if (error || !template) {
    return (
      <div className="min-h-screen bg-[var(--color-bg)]">
        <LandingNav activeKey="templates" />
        <div className="max-w-7xl mx-auto px-6 py-20 text-center">
          <p className="text-[var(--color-text-muted)] text-sm">
            {error || "模板不存在"}
          </p>
          <button
            onClick={() => navigate("/templates")}
            className="mt-4 text-brand text-sm hover:underline cursor-pointer"
          >
            返回模板列表
          </button>
        </div>
      </div>
    );
  }

  const currentIndex = allTemplates.findIndex((t) => t.id === id);
  const prevT = currentIndex > 0 ? allTemplates[currentIndex - 1] : null;
  const nextT =
    currentIndex < allTemplates.length - 1 ? allTemplates[currentIndex + 1] : null;
  const recommended = allTemplates.filter((t) => t.id !== id).slice(0, 4);

  const layoutText =
    typeof template.layout === "string"
      ? template.layout
      : template.layout != null
        ? JSON.stringify(template.layout, null, 2)
        : "";

  // CTA：已登录 → 用模板创建简历；未登录 → 弹登录
  const handleUseTemplate = async () => {
    if (!user) {
      window.dispatchEvent(new CustomEvent("open-login-modal"));
      return;
    }
    if (creating) return;
    setActionError("");
    setCreating(true);
    try {
      const resume = await createBuilderResume({
        filename: "新简历",
        style: { template_id: template.id } as ResumeStyle,
      });
      navigate(`/resumes/${resume.id}/edit`);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "创建失败，请重试");
      setCreating(false);
    }
  };

  return (
    <div className="min-h-screen bg-[var(--color-bg)]">
      <LandingNav activeKey="templates" />

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
            onClick={() => navigate("/templates")}
            className="hover:text-brand transition-colors cursor-pointer"
          >
            简历模板
          </button>
          <CaretRight size={10} />
          <span className="text-[var(--color-text)] font-medium truncate max-w-[300px]">
            {template.name}
          </span>
        </nav>

        {/* 主体：预览 + 信息 */}
        <div className="flex flex-col lg:flex-row gap-10 mb-16">
          {/* 左侧：预览（有前端组件的模板用 React 渲染，其余 iframe 兜底） */}
          <div className="flex-1 flex justify-center">
            <TemplateCardPreview template={template} className="max-w-[400px] mx-auto" />
          </div>

          {/* 右侧：模板信息 */}
          <div className="flex-1 max-w-lg">
            <div className="flex items-start justify-between gap-4 mb-4">
              <h1 className="text-2xl font-bold text-[var(--color-text)] leading-tight display-tight">
                {template.name}
              </h1>
              <span className="text-xs text-[var(--color-text-muted)] shrink-0 tabular-nums">
                {template.id}
              </span>
            </div>

            <p className="text-sm text-[var(--color-text-secondary)] leading-relaxed mb-6">
              {template.description || "暂无描述"}
            </p>

            {/* 标签 */}
            <h2 className="text-base font-semibold text-[var(--color-text)] mb-3">
              标签
            </h2>
            <div className="flex flex-wrap gap-2 mb-6">
              {(template.tags ?? []).length > 0 ? (
                template.tags.map((t) => (
                  <span
                    key={t}
                    className="px-3 py-1.5 rounded-full text-xs font-medium bg-[var(--color-bg-secondary)] text-[var(--color-text-secondary)] border border-[var(--color-border)]"
                  >
                    {t}
                  </span>
                ))
              ) : (
                <span className="text-xs text-[var(--color-text-muted)]">-</span>
              )}
            </div>

            {/* 布局元数据 */}
            {layoutText && (
              <>
                <h2 className="text-base font-semibold text-[var(--color-text)] mb-3">
                  布局配置
                </h2>
                <pre className="text-[11px] text-[var(--color-text-secondary)] leading-relaxed mb-6 p-4 rounded-xl bg-[var(--color-bg-secondary)] border border-[var(--color-border)] overflow-x-auto whitespace-pre-wrap">
                  {layoutText}
                </pre>
              </>
            )}

            {actionError && (
              <p className="text-xs text-red-500 mb-3">{actionError}</p>
            )}

            {/* CTA 按钮 */}
            <button
              onClick={handleUseTemplate}
              disabled={creating}
              className="w-full flex items-center justify-center gap-2 py-3.5 rounded-xl bg-brand text-white font-semibold text-sm
                hover:bg-[#0077ed] hover:scale-[1.02] active:scale-[0.98]
                transition-all duration-300 cursor-pointer disabled:opacity-60 disabled:cursor-not-allowed"
            >
              {creating ? (
                <Spinner size={16} className="animate-spin" />
              ) : (
                <Pen size={16} weight="regular" />
              )}
              {creating ? "正在创建..." : "使用模板创建简历"}
            </button>
          </div>
        </div>

        {/* 上/下一个模板 */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-5 mb-16">
          {prevT ? (
            <button
              onClick={() => navigate(`/templates/${prevT.id}`)}
              className="glass-card p-5 text-left hover:-translate-y-1 hover:shadow-xl transition-all duration-400 cursor-pointer group"
            >
              <div className="flex items-center gap-1.5 text-xs text-[var(--color-text-muted)] mb-2">
                <CaretLeft
                  size={12}
                  className="group-hover:-translate-x-1 transition-transform"
                />
                上一个模板
              </div>
              <h3 className="text-sm font-semibold text-[var(--color-text)] leading-snug">
                {prevT.name}
              </h3>
              <span className="text-[10px] text-[var(--color-text-muted)]">
                {(prevT.tags ?? []).slice(0, 2).join(" · ") || "模板"}
              </span>
            </button>
          ) : (
            <div />
          )}
          {nextT ? (
            <button
              onClick={() => navigate(`/templates/${nextT.id}`)}
              className="glass-card p-5 text-right hover:-translate-y-1 hover:shadow-xl transition-all duration-400 cursor-pointer group"
            >
              <div className="flex items-center justify-end gap-1.5 text-xs text-[var(--color-text-muted)] mb-2">
                下一个模板
                <CaretRight
                  size={12}
                  className="group-hover:translate-x-1 transition-transform"
                />
              </div>
              <h3 className="text-sm font-semibold text-[var(--color-text)] leading-snug">
                {nextT.name}
              </h3>
              <span className="text-[10px] text-[var(--color-text-muted)]">
                {(nextT.tags ?? []).slice(0, 2).join(" · ") || "模板"}
              </span>
            </button>
          ) : (
            <div />
          )}
        </div>

        {/* 推荐模板 */}
        {recommended.length > 0 && (
          <div className="mb-16">
            <h2 className="text-lg font-bold text-[var(--color-text)] text-center mb-6">
              更多简历模板
            </h2>
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-5">
              {recommended.map((t) => (
                <div
                  key={t.id}
                  className="glass-card overflow-hidden hover:-translate-y-1 hover:shadow-xl transition-all duration-400 cursor-pointer group"
                  onClick={() => navigate(`/templates/${t.id}`)}
                >
                  <div className="aspect-[3/4] overflow-hidden">
                    <iframe
                      srcDoc={t.preview_html}
                      scrolling="no"
                      title={t.name}
                      className="w-full h-full border-0"
                    />
                  </div>
                  <div className="p-3">
                    <h3 className="text-xs font-semibold text-[var(--color-text)] leading-snug line-clamp-2">
                      {t.name}
                    </h3>
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
