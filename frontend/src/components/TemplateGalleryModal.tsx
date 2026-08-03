/**
 * TemplateGalleryModal — 模板画廊点击卡片的放大预览弹窗。
 *
 * 双轨预览：有前端 React 组件的模板用 ResumeTemplateView + mock 渲染；
 * 其余保留后端 preview_html iframe 兜底。
 * 底部 CTA：「使用模板创建简历」（未登录 → 弹全局登录；已登录 → createBuilderResume）。
 *
 * 同时导出 TemplateCardPreview — 画廊/详情页共用的 A4 比例卡片预览（React vs iframe 双轨）。
 */

import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowRight, Pen, Spinner, X } from "@phosphor-icons/react";
import { useAuth } from "../context/AuthContext";
import { createBuilderResume } from "../api/builder";
import type { ResumeModule, ResumeStyle } from "../api/builder";
import type { MarketTemplate } from "../api/market";
import { ResumeTemplateView } from "./templates";
import { A4PreviewContainer } from "./builder/A4PreviewContainer";
import { getTemplateConfigs, hasTemplateComponent } from "./templates/registry";
import { createMockModules, createMockStyle } from "./templates/shared/mockData";

// ── A4 比例卡片预览（双轨：React 组件 vs iframe 兜底） ──────────

export interface TemplateCardPreviewProps {
  template: MarketTemplate;
  /** 主题色覆盖（画廊轮播/选色器），不传用模板默认色 */
  accentColor?: string;
  /** 自定义 modules（放大预览可复用手卡片一致的数据） */
  modules?: ResumeModule[];
  className?: string;
}

export function TemplateCardPreview({
  template,
  accentColor,
  modules,
  className = "",
}: TemplateCardPreviewProps) {
  const isComponent = hasTemplateComponent(template.id);

  // 前端组件模板的 React 渲染（mock 数据 + 模板 config 派生 style）
  const reactView = useMemo(() => {
    if (!isComponent) return null;
    const config = getTemplateConfigs().find((c) => c.id === template.id);
    if (!config) return null;
    return (
      <ResumeTemplateView
        modules={modules ?? createMockModules()}
        style={createMockStyle(config, accentColor)}
      />
    );
  }, [isComponent, template.id, modules, accentColor]);

  // 无前端组件的模板 → 后端 preview_html iframe 兜底
  if (!isComponent) {
    if (!template.preview_html) {
      return (
        <A4PreviewContainer className={`ring-1 ring-[var(--color-border)] rounded-sm ${className}`}>
          <div className="w-full h-full bg-white" />
        </A4PreviewContainer>
      );
    }
    return (
      <A4PreviewContainer className={`ring-1 ring-[var(--color-border)] rounded-sm ${className}`}>
        <iframe
          srcDoc={template.preview_html}
          scrolling="no"
          title={`${template.name} 模板预览`}
          className="w-full h-full border-0 bg-white"
        />
      </A4PreviewContainer>
    );
  }

  return (
    <A4PreviewContainer className={`ring-1 ring-[var(--color-border)] rounded-sm ${className}`}>
      {reactView}
    </A4PreviewContainer>
  );
}

// ── 放大预览弹窗 ──────────────────────────────────────────────

export interface TemplateGalleryModalProps {
  template: MarketTemplate | null;
  onClose: () => void;
  /** 画廊当前选中的主题色（透传给预览） */
  accentColor?: string;
}

export default function TemplateGalleryModal({
  template,
  onClose,
  accentColor,
}: TemplateGalleryModalProps) {
  const navigate = useNavigate();
  const { user } = useAuth();
  const [creating, setCreating] = useState(false);
  const [actionError, setActionError] = useState("");

  // Esc 关闭 + body 滚动锁定
  useEffect(() => {
    if (!template) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
    };
  }, [template, onClose]);

  if (!template) return null;

  // CTA：已登录 → 用模板创建简历；未登录 → 弹登录（对齐 TemplateDetailPage 模式）
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
      onClose();
      navigate(`/resumes/${resume.id}/edit`);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "创建失败，请重试");
      setCreating(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center p-4
        bg-black/50 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-label={`${template.name} 模板预览`}
      onClick={onClose}
    >
      <div
        className="w-full max-w-3xl glass-card overflow-hidden flex flex-col max-h-[88vh] shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* 头部：模板名 + 关闭 */}
        <div className="flex items-center justify-between gap-3 px-5 py-4 border-b border-[var(--color-border)]">
          <div className="min-w-0">
            <h3 className="text-base font-semibold text-[var(--color-text)] leading-snug truncate">
              {template.name}
            </h3>
            <span className="text-xs text-[var(--color-text-muted)]">{template.id}</span>
          </div>
          <button
            onClick={onClose}
            aria-label="关闭"
            className="p-1.5 rounded-lg text-[var(--color-text-secondary)]
              hover:bg-[var(--color-bg-secondary)] hover:text-[var(--color-text)]
              active:scale-[0.95] transition-all cursor-pointer shrink-0"
          >
            <X size={18} weight="bold" aria-hidden="true" />
          </button>
        </div>

        {/* 放大预览 */}
        <div className="flex-1 overflow-y-auto p-5 bg-[var(--color-bg)]">
          <TemplateCardPreview
            template={template}
            accentColor={accentColor}
            className="max-w-[420px] mx-auto rounded-lg shadow-lg ring-1 ring-[var(--color-border)]"
          />
          {template.description && (
            <p className="text-xs text-[var(--color-text-secondary)] leading-relaxed mt-4 max-w-[420px] mx-auto">
              {template.description}
            </p>
          )}
        </div>

        {/* 底部 CTA */}
        <div className="px-5 py-4 border-t border-[var(--color-border)]">
          {actionError && <p className="text-xs text-red-500 mb-2">{actionError}</p>}
          <div className="flex items-center justify-between gap-3 flex-wrap">
            <button
              onClick={() => {
                onClose();
                navigate(`/templates/${template.id}`);
              }}
              className="inline-flex items-center gap-1 text-sm text-[var(--color-text-muted)]
                hover:text-brand transition-colors cursor-pointer"
            >
              查看详情 <ArrowRight size={14} />
            </button>
            <button
              onClick={handleUseTemplate}
              disabled={creating}
              className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-brand text-white font-semibold text-sm
                hover:bg-[#0077ed] active:scale-[0.98] transition-all duration-300 cursor-pointer
                disabled:opacity-60 disabled:cursor-not-allowed"
            >
              {creating ? (
                <Spinner size={16} className="animate-spin" aria-hidden="true" />
              ) : (
                <Pen size={16} aria-hidden="true" />
              )}
              {creating ? "正在创建..." : "使用模板创建简历"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
