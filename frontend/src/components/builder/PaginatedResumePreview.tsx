/**
 * PaginatedResumePreview — 真实多页 A4 预览容器。
 *
 * ## 架构：隐藏测量层 + 可见分页层
 *
 * ```
 * ┌─ 隐藏测量层（width 794px、scale=1、visibility hidden、不占布局） ─┐
 * │  完整渲染所有 section → usePagination 逐个测 offsetHeight        │
 * └────────────────────────────────────────────────────────────────┘
 *          ↓ metrics: [{id:"basic_info",height:180}, ...]
 *          ↓ computeFitScale → scaleFactor
 *          ↓ packPages(metrics, capacity / scaleFactor)
 * ┌─ 可见分页层 ─┐
 * │  第 1 页（独立 A4 白纸 + 独立 padding + 阴影 + 页码）             │
 * │  ↕ gap                                                         │
 * │  第 2 页                                                       │
 * └────────────────────────────────────────────────────────────────┘
 * ```
 *
 * ## 单向数据流，无震荡
 *
 * 测量层内容恒为全量 section、宽度恒为 794px、不受任何缩放影响，
 * 因此 `metrics` 是稳定输入。缩放系数与装箱都是它的纯函数派生值：
 *
 *   metrics → scaleFactor → capacity/scaleFactor → pages
 *
 * 可见层的变化不会回流到测量层，切断了旧实现「测量 → 缩放 → 重排 → 再测量」的自反馈环。
 *
 * ## 与三个参考项目的差异（已实地探查）
 *
 * - magic-resume / resume-design：单长 DOM + 画红线，线横穿文字且与 PDF 分页错位
 * - reactive-resume：渲染真 PDF（预览=导出，但需用 @react-pdf/renderer 重写全部模板）
 * - 本方案：保留 HTML 模板，做真实 DOM 装箱，section 整体不跨页
 */

import { useEffect, useMemo, type CSSProperties } from "react";
import { ResumeTemplateView } from "../templates";
import { isMultiColumnTemplate, SIDEBAR_TYPES } from "../templates/registry";
import {
  usePagination,
  packByItems,
  computeFitScale,
  A4_WIDTH_PX,
  A4_HEIGHT_PX,
  MM_TO_PX,
  type PageSlice,
} from "./usePagination";
import type { ModuleType, ResumeModule, ResumeStyle } from "../../api/builder";

export interface PaginatedPreviewState {
  pageCount: number;
  isScaled: boolean;
  cannotFit: boolean;
  scaleFactor: number;
}

export interface PaginatedResumePreviewProps {
  modules: ResumeModule[];
  style: ResumeStyle;
  /** 视口缩放（工具栏 50/75/100%），只影响显示大小，不参与分页计算 */
  zoom: number;
  /** 自动压缩到 N 页（0 = 关闭） */
  fitPages: number;
  interactive?: boolean;
  onSelectSection?: (moduleType: ModuleType) => void;
  /** 分页/压缩状态回调（供工具栏显示页数与提示） */
  onStateChange?: (state: PaginatedPreviewState) => void;
}

/** 页边距解析：style.margin 可能是 "16mm"（默认）或 "48px"（模板切换写入） */
function resolvePagePadding(margin: string | undefined): number {
  const raw = (margin ?? "16mm").trim();
  const value = parseFloat(raw) || 0;
  const px = /px$/i.test(raw) ? value : value * MM_TO_PX;
  return Math.max(px, 8);
}

/** 把一页的 slices（含条目区间/标题标志）转为带 itemRange/showTitle 的 ResumeModule[] */
function slicesToModules(
  slices: PageSlice[],
  moduleMap: Map<string, ResumeModule>,
): ResumeModule[] {
  const out: ResumeModule[] = [];
  for (const s of slices) {
    const m = moduleMap.get(s.moduleType);
    if (!m) continue;
    out.push({ ...m, itemRange: s.itemRange, showTitle: s.showTitle });
  }
  return out;
}

export function PaginatedResumePreview({
  modules,
  style,
  zoom,
  fitPages,
  interactive = false,
  onSelectSection,
  onStateChange,
}: PaginatedResumePreviewProps) {
  const pagePadding = resolvePagePadding(style?.margin);
  /** 单页可用内容高度（扣除上下页边距） */
  const availableHeight = Math.max(A4_HEIGHT_PX - 2 * pagePadding, 100);

  // 内容签名：modules 或影响排版的 style 字段变化时重新测量
  const contentKey = useMemo(
    () =>
      JSON.stringify({
        m: modules.map((m) => [m.module_type, m.sort_order, JSON.stringify(m.content)]),
        s: [
          style?.font_size,
          style?.line_height,
          style?.section_spacing,
          style?.spacing,
          style?.margin,
          style?.template_id,
          style?.font_family,
        ],
      }),
    [modules, style],
  );

  const { measureRef, metrics, totalHeight, measured } = usePagination({ contentKey });

  /**
   * 双栏模板：section 分散在左右两栏，`totalHeight`（垂直累加）会是实际视觉高度的约两倍，
   * 直接用它算压缩系数会过度压缩。这里取测量层容器的真实高度作为替代。
   */
  const isMultiColumn = isMultiColumnTemplate(style?.template_id);
  const effectiveHeight = useMemo(() => {
    if (!isMultiColumn) return totalHeight;
    const root = measureRef.current;
    return root ? root.offsetHeight : totalHeight;
    // measured 变化时重新读取（测量完成后 DOM 高度才稳定）
  }, [isMultiColumn, totalHeight, measured, measureRef]);

  // ① 缩放系数（仅依赖测量结果，纯函数）
  const fit = useMemo(
    () =>
      fitPages > 0
        ? computeFitScale({ totalHeight: effectiveHeight, availableHeight, targetPages: fitPages })
        : { scaleFactor: 1, isScaled: false, cannotFit: false },
    [fitPages, effectiveHeight, availableHeight],
  );

  // ② 装箱（条目级流式分页，借鉴 reactive-resume/Magic-Resume：条目可跨页、每页尽量填满）
  //
  // 单栏：packByItems 按条目装箱——列表模块按条目拆分（标题跟第一条，其余条目流入后续页），
  // 超长 section 不再独占一页被裁，上一页也不再留大片空白。
  // 双栏：侧栏流与主栏流各自按条目装箱，页数取最大值逐页配对。
  const pages = useMemo(() => {
    if (metrics.length === 0) return [] as PageSlice[][];
    const capacity = availableHeight / fit.scaleFactor;
    if (isMultiColumn) {
      const sidebar = metrics.filter((m) => SIDEBAR_TYPES.has(m.id));
      const main = metrics.filter((m) => !SIDEBAR_TYPES.has(m.id));
      const sidebarPages = packByItems(sidebar, capacity);
      const mainPages = packByItems(main, capacity);
      const count = Math.max(sidebarPages.length, mainPages.length);
      return Array.from({ length: count }, (_, i) => [
        ...(sidebarPages[i] ?? []),
        ...(mainPages[i] ?? []),
      ]);
    }
    return packByItems(metrics, capacity);
  }, [metrics, availableHeight, fit.scaleFactor, isMultiColumn]);

  const pageCount = pages.length;

  // 状态上报（副作用必须放 useEffect，不能放 useMemo）
  useEffect(() => {
    onStateChange?.({
      pageCount,
      isScaled: fit.isScaled,
      cannotFit: fit.cannotFit,
      scaleFactor: fit.scaleFactor,
    });
  }, [pageCount, fit.isScaled, fit.cannotFit, fit.scaleFactor, onStateChange]);

  const moduleMap = useMemo(() => {
    const map = new Map<string, ResumeModule>();
    for (const m of modules) map.set(m.module_type, m);
    return map;
  }, [modules]);

  /**
   * 内容压缩层样式。
   *
   * 借鉴 magic-resume 的反震荡技巧：scale 的同时把 width 反向放大 1/scale，
   * 让缩放后内容依然铺满 794px 逻辑宽度（否则会左侧留白、右侧内容被压窄）。
   * 这里安全，因为可见层不参与测量。
   */
  const contentScale = fit.scaleFactor;
  const contentStyle: CSSProperties =
    contentScale < 1
      ? {
          transform: `scale(${contentScale})`,
          transformOrigin: "top left",
          width: `${100 / contentScale}%`,
        }
      : {};

  return (
    <div className="paginated-resume-preview flex flex-col items-center gap-6">
      {/* ── 隐藏测量层：固定 794px、scale=1、不占布局空间 ── */}
      <div
        aria-hidden="true"
        style={{
          position: "absolute",
          top: 0,
          left: -99999,
          width: A4_WIDTH_PX,
          visibility: "hidden",
          pointerEvents: "none",
        }}
      >
        <div ref={measureRef} style={{ width: A4_WIDTH_PX }}>
          <ResumeTemplateView modules={modules} style={style} />
        </div>
      </div>

      {/* 首次测量前的占位骨架 */}
      {!measured && (
        <div
          className="paper-surface bg-white shadow-lg rounded-sm animate-pulse"
          style={{ width: A4_WIDTH_PX * zoom, height: A4_HEIGHT_PX * zoom }}
        />
      )}

      {/* ── 可见分页层：每页一张独立 A4 白纸 ── */}
      {pages.map((slices, pageIndex) => {
        const pageModules = slicesToModules(slices, moduleMap);
        return (
          <figure key={pageIndex} className="shrink-0 m-0">
            <figcaption className="mb-1 text-[10px] text-[var(--color-text-muted)] text-center select-none">
              第 {pageIndex + 1} / {pageCount} 页
            </figcaption>
            <div
              className="paper-surface resume-page bg-white shadow-lg rounded-sm overflow-hidden"
              data-resume-page={pageIndex + 1}
              style={{ width: A4_WIDTH_PX * zoom, height: A4_HEIGHT_PX * zoom }}
            >
              {/* 视口缩放层：794×1123 逻辑纸张 → 按 zoom 显示 */}
              <div
                className="a4-preview-scale-wrapper origin-top-left"
                style={{
                  width: A4_WIDTH_PX,
                  height: A4_HEIGHT_PX,
                  transform: `scale(${zoom})`,
                }}
              >
                {/* 内容压缩层（自动一页），每页独立 padding 由模板的 var(--margin) 提供 */}
                <div style={{ height: "100%", overflow: "hidden", ...contentStyle }}>
                  <ResumeTemplateView
                    modules={pageModules}
                    style={style}
                    interactive={interactive}
                    onSelectSection={onSelectSection}
                  />
                </div>
              </div>
            </div>
          </figure>
        );
      })}
    </div>
  );
}

export default PaginatedResumePreview;
