/**
 * 模板预览缩略图 — 按模板 config 颜色/布局动态生成的 SVG 色块图。
 *
 * 每个缩略图以简化的 SVG 呈现模板视觉风格概览：
 * - 双栏（侧栏）模板：左侧主色侧栏 + 主内容区
 * - 单栏模板：按模板特征差异化布局（头带 / 卡片 / 时间轴 / 技能胶囊），
 *   避免此前所有单栏模板共用同一套色块布局、仅换颜色导致缩略图雷同
 *
 * 颜色取自 getTemplateConfigs() 的 colorScheme，18 套全覆盖，
 * 无需为每套手绘。内联 SVG，不增加网络请求。
 */

import type { JSX } from "react";
import { getTemplateConfigs } from "../templates/registry";
import type { TemplateConfig } from "../templates/registry";

interface ThumbnailProps {
  className?: string;
}

/** 双栏（侧栏）模板 id —— 与 MULTI_COLUMN_TEMPLATES 对齐 */
const MULTI_IDS = new Set([
  "azurill",
  "teal",
  "gengar",
  "slate",
  "orange",
  "chikorita",
  "golden-elegant",
]);

/** 单栏模板缩略图布局变体（体现各自排版特征，避免色块千篇一律） */
type SingleLayout = "plain" | "headband" | "cards" | "timeline" | "skills";

const SINGLE_LAYOUTS: Record<string, SingleLayout> = {
  executive: "headband", // 深蓝头带横贯顶部
  ditto: "cards", // 浅灰底 + 白卡片模块
  "timeline-pro": "timeline", // 左侧时间轴竖线 + 节点圆点
  "skills-first": "skills", // 顶部技能胶囊
};

interface Palette {
  primary: string;
  secondary: string;
  background: string;
  text: string;
}

/** 通用：单栏章节内容块（标题 + 两行正文） */
function contentBlock(p: Palette, x: number, y: number): JSX.Element {
  return (
    <g key={`cb-${x}-${y}`}>
      <rect x={x} y={y} width="34" height="3" fill={p.primary} rx="1" />
      <rect x={x} y={y + 10} width="88" height="3" fill={p.secondary} opacity="0.4" rx="0.5" />
      <rect x={x} y={y + 16} width="70" height="3" fill={p.secondary} opacity="0.4" rx="0.5" />
    </g>
  );
}

/** 单栏各布局主体（不含背景 rect） */
function renderSingleBody(layout: SingleLayout, p: Palette): JSX.Element {
  switch (layout) {
    case "headband":
      return (
        <>
          {/* 顶部横贯头带 */}
          <rect x="0" y="0" width="120" height="34" fill={p.primary} />
          <rect x="14" y="11" width="52" height="7" fill="#ffffff" opacity="0.95" rx="1" />
          <rect x="14" y="22" width="72" height="3" fill="#ffffff" opacity="0.55" rx="0.5" />
          {contentBlock(p, 14, 48)}
          {contentBlock(p, 14, 80)}
          {contentBlock(p, 14, 112)}
        </>
      );
    case "cards":
      return (
        <>
          <rect x="12" y="12" width="50" height="6" fill={p.text} rx="1" />
          <rect x="12" y="24" width="72" height="3" fill={p.secondary} opacity="0.5" rx="0.5" />
          {/* 三张白卡片（带描边） */}
          {[
            { y: 36, w1: 40, w2: 80 },
            { y: 66, w1: 40, w2: 70 },
            { y: 96, w1: 40, w2: 76 },
          ].map((c, i) => (
            <g key={`card-${i}`}>
              <rect x="12" y={c.y} width="96" height="24" fill="#ffffff"
                stroke={p.secondary} strokeOpacity="0.4" rx="2" />
              <rect x="18" y={c.y + 6} width={c.w1} height="3" fill={p.primary} rx="0.5" />
              <rect x="18" y={c.y + 12} width={c.w2} height="2.5" fill={p.secondary} opacity="0.45" rx="0.5" />
              <rect x="18" y={c.y + 16.5} width={c.w2 - 20} height="2.5" fill={p.secondary} opacity="0.45" rx="0.5" />
            </g>
          ))}
        </>
      );
    case "timeline":
      return (
        <>
          <rect x="14" y="14" width="50" height="7" fill={p.text} rx="1" />
          {/* 左侧时间轴竖线 + 节点圆点 */}
          <line x1="26" y1="36" x2="26" y2="152" stroke={p.primary} strokeWidth="2" opacity="0.45" />
          {[
            { cy: 46, wy: 43, ly: 53 },
            { cy: 80, wy: 77, ly: 87 },
            { cy: 114, wy: 111, ly: 121 },
          ].map((n, i) => (
            <g key={`tl-${i}`}>
              <circle cx="26" cy={n.cy} r="4" fill={p.primary} />
              <rect x="38" y={n.wy} width="32" height="5" fill={p.text} rx="0.5" />
              <rect x="38" y={n.ly} width="68" height="3" fill={p.secondary} opacity="0.4" rx="0.5" />
            </g>
          ))}
        </>
      );
    case "skills":
      return (
        <>
          <rect x="14" y="14" width="50" height="7" fill={p.text} rx="1" />
          {/* 顶部技能胶囊（两排） */}
          <g>
            <rect x="14" y="28" width="30" height="10" rx="5" fill={p.primary} />
            <rect x="48" y="28" width="24" height="10" rx="5" fill={p.primary} opacity="0.7" />
            <rect x="76" y="28" width="26" height="10" rx="5" fill={p.primary} opacity="0.5" />
            <rect x="14" y="42" width="22" height="9" rx="4.5" fill={p.primary} opacity="0.55" />
            <rect x="40" y="42" width="28" height="9" rx="4.5" fill={p.primary} opacity="0.35" />
          </g>
          {contentBlock(p, 14, 62)}
          {contentBlock(p, 14, 94)}
          {contentBlock(p, 14, 126)}
        </>
      );
    case "plain":
    default:
      return (
        <>
          {/* 姓名强调条 + 章节色块 */}
          <rect x="14" y="14" width="50" height="7" fill={p.text} rx="1" />
          <rect x="14" y="25" width="70" height="3" fill={p.secondary} opacity="0.5" rx="0.5" />
          {contentBlock(p, 14, 36)}
          {contentBlock(p, 14, 70)}
          {contentBlock(p, 14, 104)}
        </>
      );
  }
}

function makeThumbnail(
  config: TemplateConfig,
  multiColumn: boolean,
): (props: ThumbnailProps) => JSX.Element {
  const singleLayout: SingleLayout = multiColumn ? "plain" : (SINGLE_LAYOUTS[config.id] ?? "plain");
  return function Thumbnail({ className = "" }: ThumbnailProps) {
    const { primary, secondary, background, text } = config.colorScheme;
    return (
      <svg
        viewBox="0 0 120 160"
        className={className}
        role="img"
        aria-label={`${config.name}模板预览`}
      >
        <rect width="120" height="160" fill={background} />
        {multiColumn ? (
          <>
            {/* 侧栏：主色铺满左侧 */}
            <rect width="42" height="160" fill={primary} />
            <rect x="8" y="16" width="26" height="5" fill="#ffffff" opacity="0.92" rx="0.5" />
            <rect x="8" y="26" width="20" height="3" fill="#ffffff" opacity="0.55" rx="0.5" />
            <rect x="8" y="40" width="26" height="1" fill="#ffffff" opacity="0.3" />
            <rect x="8" y="46" width="22" height="3" fill="#ffffff" opacity="0.6" rx="0.5" />
            <rect x="8" y="52" width="18" height="3" fill="#ffffff" opacity="0.6" rx="0.5" />
            <rect x="8" y="60" width="26" height="1" fill="#ffffff" opacity="0.3" />
            <rect x="8" y="66" width="20" height="3" fill="#ffffff" opacity="0.6" rx="0.5" />
            {/* 主内容区 */}
            <rect x="52" y="14" width="60" height="1" fill={primary} />
            <rect x="52" y="18" width="30" height="5" fill={text} rx="0.5" />
            <rect x="52" y="27" width="50" height="3" fill={secondary} opacity="0.5" rx="0.5" />
            <rect x="52" y="33" width="42" height="3" fill={secondary} opacity="0.5" rx="0.5" />
            <rect x="52" y="44" width="60" height="1" fill={primary} opacity="0.4" />
            <rect x="52" y="48" width="22" height="5" fill={primary} rx="0.5" />
            <rect x="52" y="58" width="52" height="3" fill={secondary} opacity="0.5" rx="0.5" />
            <rect x="52" y="64" width="44" height="3" fill={secondary} opacity="0.5" rx="0.5" />
          </>
        ) : (
          renderSingleBody(singleLayout, { primary, secondary, background, text })
        )}
      </svg>
    );
  };
}

/** 模板 ID → 缩略图组件（按 config 颜色/布局动态生成） */
export const TEMPLATE_THUMBNAILS: Record<string, (props: ThumbnailProps) => JSX.Element> = {};

for (const config of getTemplateConfigs()) {
  TEMPLATE_THUMBNAILS[config.id] = makeThumbnail(config, MULTI_IDS.has(config.id));
}
