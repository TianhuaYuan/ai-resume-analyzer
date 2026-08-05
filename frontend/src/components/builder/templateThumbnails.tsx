/**
 * 模板预览缩略图 — 按模板 config 颜色/布局动态生成的 SVG 色块图。
 *
 * 每个缩略图以简化的 SVG 呈现模板视觉风格概览：
 * - 双栏（侧栏）模板：左侧主色侧栏 + 主内容区
 * - 单栏模板：姓名强调条 + 章节色块
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

function makeThumbnail(
  config: TemplateConfig,
  multiColumn: boolean,
): (props: ThumbnailProps) => JSX.Element {
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
          <>
            {/* 单栏：姓名强调条 + 章节色块 */}
            <rect x="14" y="14" width="50" height="7" fill={text} rx="1" />
            <rect x="14" y="25" width="70" height="3" fill={secondary} opacity="0.5" rx="0.5" />
            <rect x="14" y="36" width="34" height="3" fill={primary} rx="1" />
            <rect x="14" y="46" width="88" height="3" fill={secondary} opacity="0.4" rx="0.5" />
            <rect x="14" y="52" width="74" height="3" fill={secondary} opacity="0.4" rx="0.5" />
            <rect x="14" y="64" width="34" height="3" fill={primary} rx="1" />
            <rect x="14" y="74" width="88" height="3" fill={secondary} opacity="0.4" rx="0.5" />
            <rect x="14" y="80" width="60" height="3" fill={secondary} opacity="0.4" rx="0.5" />
            <rect x="14" y="92" width="34" height="3" fill={primary} rx="1" />
            <rect x="14" y="102" width="80" height="3" fill={secondary} opacity="0.4" rx="0.5" />
            <rect x="14" y="108" width="66" height="3" fill={secondary} opacity="0.4" rx="0.5" />
          </>
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
