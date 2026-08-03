/**
 * TemplateSheet — 编辑器内模板切换抽屉（借鉴 Magic Resume TemplateSheet）。
 *
 * 用当前编辑的 modules + 各模板主题色实时渲染缩略图，点击切换模板。
 * 切换后覆盖 accent_color/section_spacing/spacing（与模板配色对齐），
 * 数据由 BuilderPage 的 style state 驱动，保存时一并持久化。
 */

import { useEffect, useRef, useState } from "react";
import { X, Check } from "@phosphor-icons/react";
import { getTemplateConfigs } from "../templates/registry";
import { ResumeTemplateView } from "../templates";
import type { ResumeModule, ResumeStyle } from "../../api/builder";

const A4_WIDTH_PX = 794;
const A4_HEIGHT_PX = A4_WIDTH_PX * 1.4142;

interface TemplateSheetProps {
  open: boolean;
  onClose: () => void;
  modules: ResumeModule[];
  style: ResumeStyle;
  currentTemplateId: string | null;
  onSelect: (templateId: string) => void;
}

function TemplateThumbnail({
  templateId,
  modules,
  style,
}: {
  templateId: string;
  modules: ResumeModule[];
  style: ResumeStyle;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(0.2);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const update = () => {
      if (el.clientWidth > 0) setScale(el.clientWidth / A4_WIDTH_PX);
    };
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  return (
    <div ref={containerRef} className="w-full overflow-hidden bg-white">
      <div style={{ width: A4_WIDTH_PX, height: A4_HEIGHT_PX, transform: `scale(${scale})`, transformOrigin: "top left" }}>
        <ResumeTemplateView modules={modules} style={{ ...style, template_id: templateId }} />
      </div>
    </div>
  );
}

export function TemplateSheet({
  open,
  onClose,
  modules,
  style,
  currentTemplateId,
  onSelect,
}: TemplateSheetProps) {
  const templates = getTemplateConfigs();

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50"
      role="dialog"
      aria-modal="true"
      aria-label="选择模板"
    >
      {/* 遮罩 */}
      <div className="absolute inset-0 bg-black/30 backdrop-blur-sm" onClick={onClose} />

      {/* 抽屉 */}
      <div className="absolute inset-y-0 right-0 w-[420px] max-w-[90vw] flex flex-col
        bg-[var(--color-bg)] border-l border-[var(--color-border)] shadow-2xl animate-fade-in-up">
        {/* 头部 */}
        <div className="shrink-0 flex items-center justify-between px-5 py-4 border-b border-[var(--color-border)]">
          <h3 className="text-base font-semibold text-[var(--color-text)]">选择模板</h3>
          <button
            onClick={onClose}
            className="btn-tool-icon"
            aria-label="关闭"
          >
            <X size={16} weight="bold" />
          </button>
        </div>

        {/* 模板列表 */}
        <div className="flex-1 overflow-y-auto px-5 py-4">
          <div className="grid grid-cols-2 gap-4">
            {templates.map((t) => {
              const isActive = t.id === currentTemplateId;
              return (
                <button
                  key={t.id}
                  onClick={() => onSelect(t.id)}
                  className={`group flex flex-col rounded-xl overflow-hidden border-2 transition-all cursor-pointer text-left
                    ${isActive
                      ? "border-brand ring-2 ring-brand/20"
                      : "border-[var(--color-border)] hover:border-brand/40 hover:shadow-lg"
                    }`}
                  aria-pressed={isActive}
                >
                  <div className="aspect-[3/4] overflow-hidden relative bg-white">
                    <TemplateThumbnail templateId={t.id} modules={modules} style={style} />
                    {/* 选中角标 */}
                    {isActive && (
                      <span className="absolute top-2 right-2 w-5 h-5 rounded-full bg-brand text-white
                        flex items-center justify-center">
                        <Check size={12} weight="bold" />
                      </span>
                    )}
                  </div>
                  <div className="px-2.5 py-2 flex items-center justify-between bg-white border-t border-[var(--color-border)]/60">
                    <span className={`text-xs font-medium ${isActive ? "text-brand" : "text-[var(--color-text)]"}`}>
                      {t.name}
                    </span>
                    <span className="text-[10px] text-[var(--color-text-muted)] line-clamp-1 max-w-[60%]">
                      {t.description}
                    </span>
                  </div>
                </button>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
