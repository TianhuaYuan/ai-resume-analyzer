/**
 * T31: StylePanel — 简历样式配置面板。
 *
 * 功能：
 * - 模板选择器（11 套模板，radio 卡片）
 * - 字体下拉、间距下拉
 * - 排版精细调参：字号下拉（细档位）、行高滑块（1.0–2.0）
 * - 主题色选择器（12 预设 + 自定义 hex 输入）
 * - 所有变更立即调用 onChange(style)
 * - 可折叠（toggle show/hide）
 */

import { useCallback, useMemo, useState } from "react";
import { PaintBrush, X, Check } from "@phosphor-icons/react";
import type { ResumeStyle, ModuleType } from "../../api/builder";
import {
  TEMPLATE_OPTIONS,
  FONT_OPTIONS,
  FONT_SIZE_OPTIONS,
  SPACING_OPTIONS,
  ACCENT_COLOR_OPTIONS,
  PAGE_SIZE_OPTIONS,
} from "../../api/templates";
import { TEMPLATE_THUMBNAILS } from "./templateThumbnails";

interface StylePanelProps {
  /** 当前样式配置 */
  style: ResumeStyle;
  /** 样式变更回调 */
  onChange: (style: ResumeStyle) => void;
  /** 是否显示 */
  show: boolean;
  /** 切换显示回调 */
  onToggle: () => void;
}

/** 通用下拉框样式 */
const SELECT_CLASS =
  "w-full px-3 py-2 rounded-xl text-sm text-[var(--color-text)] " +
  "bg-[#F2F2F7] border border-transparent " +
  "focus:outline-none focus:bg-white focus:ring-4 focus:ring-brand/15 " +
  "focus:border-brand/40 transition-all duration-200 " +
  "cursor-pointer appearance-none";

const LABEL_CLASS =
  "block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5";

export function StylePanel({
  style,
  onChange,
  show,
  onToggle,
}: StylePanelProps) {
  const [customColor, setCustomColor] = useState("");

  // 通用属性更新
  const updateStyle = useCallback(
    <K extends keyof ResumeStyle>(key: K, value: ResumeStyle[K]) => {
      onChange({ ...style, [key]: value });
    },
    [style, onChange],
  );

  // 自定义颜色应用
  const handleCustomColor = useCallback(() => {
    const trimmed = customColor.trim();
    if (/^#[0-9a-fA-F]{6}$/.test(trimmed)) {
      updateStyle("accent_color", trimmed);
      setCustomColor("");
    }
  }, [customColor, updateStyle]);

  if (!show) return null;

  return (
    <div className="flex flex-col h-full w-72 border-r border-[var(--color-border)]
      bg-[var(--color-bg)] animate-fade-in-up motion-reduce:animate-none">
      {/* 标题栏 */}
      <div className="shrink-0 flex items-center justify-between px-4 py-3
        border-b border-[var(--color-border)]">
        <div className="flex items-center gap-2">
          <PaintBrush size={14} weight="duotone" className="text-brand" aria-hidden="true" />
          <h3 className="text-xs font-semibold text-[var(--color-text-secondary)] uppercase tracking-wider">
            样式配置
          </h3>
        </div>
        <button
          onClick={onToggle}
          className="p-1 rounded-md text-[var(--color-text-muted)]
            hover:text-[var(--color-text)] hover:bg-[var(--color-bg-secondary)]
            transition-all cursor-pointer"
          aria-label="关闭样式面板"
        >
          <X size={14} weight="bold" aria-hidden="true" />
        </button>
      </div>

      {/* 配置内容 */}
      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-5">
        {/* 模板选择 */}
        <div>
          <label className={LABEL_CLASS}>模板</label>
          <div className="grid grid-cols-2 gap-2">
            {TEMPLATE_OPTIONS.map((tpl) => {
              const isActive = style.template_id === tpl.id;
              const Thumbnail = TEMPLATE_THUMBNAILS[tpl.id];
              return (
                <button
                  key={tpl.id}
                  onClick={() => updateStyle("template_id", tpl.id)}
                  className={`flex flex-col items-center p-2 rounded-xl border transition-all cursor-pointer
            ${isActive
              ? "bg-brand/10 border-brand/40 ring-1 ring-brand/30"
              : "border-[var(--color-border)] hover:border-brand/20 hover:bg-[var(--color-bg-secondary)]"
            }`}
                  aria-pressed={isActive}
                  title={tpl.description}
                >
                  {Thumbnail && (
                    <div className="w-full aspect-[3/4] rounded overflow-hidden
                      border border-[var(--color-border)]/30
                      transition-transform duration-200 hover:scale-105">
                      <Thumbnail className="w-full h-full" />
                    </div>
                  )}
                  <span className={`mt-1.5 text-xs font-medium ${
                    isActive ? "text-brand" : "text-[var(--color-text)]"
                  }`}>
                    {tpl.name}
                  </span>
                </button>
              );
            })}
          </div>
        </div>

        {/* 字体 */}
        <div>
          <label className={LABEL_CLASS}>字体</label>
          <select
            value={style.font_family}
            onChange={(e) => updateStyle("font_family", e.target.value)}
            className={SELECT_CLASS}
          >
            {FONT_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>

        {/* 间距 */}
        <div>
          <label className={LABEL_CLASS}>间距</label>
          <select
            value={style.spacing}
            onChange={(e) => updateStyle("spacing", e.target.value)}
            className={SELECT_CLASS}
          >
            {SPACING_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>

        {/* 排版精细调参 */}
        <div>
          <label className={LABEL_CLASS + " mb-3"}>排版精细调参</label>
          {/* 字号档位 */}
          <div className="mb-3">
            <span className="text-[11px] text-[var(--color-text-muted)] block mb-1">字号</span>
            <select
              value={style.font_size}
              onChange={(e) => updateStyle("font_size", e.target.value)}
              className={SELECT_CLASS}
            >
              {FONT_SIZE_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>
          {/* 行高滑块 */}
          <div>
            <div className="flex items-center justify-between mb-1">
              <span className="text-[11px] text-[var(--color-text-muted)]">行高</span>
              <span className="text-[11px] font-mono text-[var(--color-text-secondary)]">
                {(typeof style.line_height === "number" ? style.line_height : 1.6).toFixed(1)}
              </span>
            </div>
            <input
              type="range"
              min={1.0}
              max={2.0}
              step={0.1}
              value={typeof style.line_height === "number" ? style.line_height : 1.6}
              onChange={(e) => updateStyle("line_height", Number(e.target.value))}
              className="w-full accent-brand cursor-pointer"
              aria-label="行高"
            />
          </div>
        </div>

        {/* 主题色 */}
        <div>
          <label className={LABEL_CLASS}>主题色</label>
          <div className="flex flex-wrap gap-2 mb-2">
            {ACCENT_COLOR_OPTIONS.map((opt) => {
              const isActive = style.accent_color === opt.value;
              return (
                <button
                  key={opt.value}
                  onClick={() => updateStyle("accent_color", opt.value)}
                  className={`w-7 h-7 rounded-lg border-2 transition-all cursor-pointer
                    ${isActive
                      ? "border-[var(--color-text)] scale-110"
                      : "border-transparent hover:scale-105"
                    }`}
                  style={{ backgroundColor: opt.value }}
                  aria-label={opt.label}
                  aria-pressed={isActive}
                  title={opt.label}
                >
                  {isActive && (
                    <Check
                      size={12}
                      weight="bold"
                      className="text-white mx-auto"
                      aria-hidden="true"
                    />
                  )}
                </button>
              );
            })}
          </div>
          {/* 自定义颜色输入 */}
          <div className="flex items-center gap-2">
            <input
              type="text"
              value={customColor}
              onChange={(e) => setCustomColor(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") handleCustomColor();
              }}
              placeholder="#000000"
              className="flex-1 px-3 py-1.5 rounded-xl text-xs font-mono
                text-[var(--color-text)] bg-[#F2F2F7] border border-transparent
                focus:outline-none focus:bg-white focus:ring-4 focus:ring-brand/15
                focus:border-brand/40 transition-all duration-200"
            />
            <button
              onClick={handleCustomColor}
              disabled={!/^#[0-9a-fA-F]{6}$/.test(customColor.trim())}
              className="px-3 py-1.5 rounded-full text-xs font-medium
                bg-brand/15 text-brand border border-brand/30
                hover:bg-brand/25
                disabled:opacity-40 disabled:cursor-not-allowed
                transition-all cursor-pointer"
            >
              应用
            </button>
          </div>
          {/* 当前颜色预览 */}
          <div className="flex items-center gap-2 mt-2">
            <span className="text-[11px] text-[var(--color-text-muted)]">当前：</span>
            <span
              className="inline-block w-4 h-4 rounded border border-[var(--color-border)]"
              style={{ backgroundColor: style.accent_color }}
              aria-hidden="true"
            />
            <span className="text-[11px] font-mono text-[var(--color-text-secondary)]">
              {style.accent_color}
            </span>
          </div>
        </div>

        {/* 分隔线 */}
        <div className="border-t border-[var(--color-border)]/50 pt-4" />

        {/* 页面设置 */}
        <div>
          <label className={LABEL_CLASS + " mb-3"}>页面设置</label>
          {/* 页边距滑块 */}
          <div className="mb-3">
            <div className="flex items-center justify-between mb-1">
              <span className="text-[11px] text-[var(--color-text-muted)]">页边距</span>
              <span className="text-[11px] font-mono text-[var(--color-text-secondary)]">
                {style.margin}
              </span>
            </div>
            <input
              type="range"
              min={10}
              max={30}
              step={1}
              value={parseInt(style.margin) || 16}
              onChange={(e) => updateStyle("margin", `${e.target.value}mm`)}
              className="w-full accent-brand cursor-pointer"
              aria-label="页边距"
            />
          </div>
          {/* 页面大小选择 */}
          <div>
            <span className="text-[11px] text-[var(--color-text-muted)] block mb-1">页面大小</span>
            <select
              value={style.page_size}
              onChange={(e) => updateStyle("page_size", e.target.value)}
              className={SELECT_CLASS}
            >
              {PAGE_SIZE_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>
        </div>

        {/* 段落设置 */}
        <div>
          <label className={LABEL_CLASS + " mb-3"}>段落设置</label>
          <div>
            <div className="flex items-center justify-between mb-1">
              <span className="text-[11px] text-[var(--color-text-muted)]">段落间距</span>
              <span className="text-[11px] font-mono text-[var(--color-text-secondary)]">
                {style.section_spacing}
              </span>
            </div>
            <input
              type="range"
              min={8}
              max={24}
              step={2}
              value={parseInt(style.section_spacing) || 16}
              onChange={(e) => updateStyle("section_spacing", `${e.target.value}px`)}
              className="w-full accent-brand cursor-pointer"
              aria-label="段落间距"
            />
          </div>
        </div>

        {/* 自定义 CSS */}
        <div>
          <label className={LABEL_CLASS}>自定义 CSS</label>
          <textarea
            value={style.custom_css}
            onChange={(e) => updateStyle("custom_css", e.target.value)}
            placeholder={"/* 输入自定义 CSS */\n.module-title { font-weight: 700; }"}
            className="w-full min-h-[100px] px-3 py-2 rounded-xl text-xs font-mono
              text-[var(--color-text)] bg-[#F2F2F7] border border-transparent
              focus:outline-none focus:bg-white focus:ring-4 focus:ring-brand/15
              focus:border-brand/40 transition-all duration-200
              resize-y placeholder:text-[var(--color-text-muted)]/60"
            rows={5}
            spellCheck={false}
          />
          <p className="text-[10px] text-[var(--color-text-muted)] mt-1 leading-relaxed">
            追加到模板样式末尾，可覆盖默认样式。
          </p>
        </div>
      </div>
    </div>
  );
}
