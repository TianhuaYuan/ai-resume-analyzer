/**
 * usePagination — A4 内容分页测量（真实多页容器方案）。
 *
 * ## 为什么需要它
 *
 * 旧方案是「单条长 DOM + 画上去的红色虚线」，虚线位置靠 `i × 页高` 除法算出，
 * 完全不考虑元素边界 —— 线会直接横穿文字，且浏览器打印时按 `@page` 硬切，
 * 两者必然错位。探查 magic-resume / resume-design 后确认它们都是这个方案，
 * 所以「预览分页 ≠ PDF 分页」是方案本身的缺陷，不是参数没调好。
 *
 * ## 本方案：测量 + 装箱（bin packing）
 *
 * 1. 隐藏的测量层以基准宽度 794px、scale=1 渲染全部 section
 * 2. 逐个读 section 的 `offsetHeight + margin`，得到原始高度列表
 * 3. 纯函数 `packPages` 按容量装箱，section 整体挪走（禁止拆开条目）
 *
 * 测量与装箱分离的原因：自动压缩的缩放系数依赖总高度，而装箱容量又依赖缩放系数。
 * 若把两者塞进同一个 hook，会形成「装箱 → 缩放 → 装箱」的循环依赖。
 * 拆成「测量（有副作用）+ 装箱（纯函数）」后依赖是单向的，不会震荡。
 *
 * 为什么用 `offsetHeight` 而非 `getBoundingClientRect()`：
 * 后者返回**变换后**的视觉尺寸，会被祖先的 `transform: scale()` 污染；
 * 前者是布局尺寸，与缩放无关，测量结果稳定。
 */

import { useCallback, useEffect, useRef, useState } from "react";

/** A4 尺寸：210mm × 297mm @ 96dpi。96 / 25.4 = 3.779528（不用 magic-resume 的 3.78 近似值） */
export const MM_TO_PX = 96 / 25.4;
export const A4_WIDTH_PX = 210 * MM_TO_PX; // 793.70
export const A4_HEIGHT_PX = 297 * MM_TO_PX; // 1122.52

/** 单个 section 的测量结果 */
export interface SectionMetric {
  id: string;
  /** 占用垂直空间（offsetHeight + 上下 margin），scale=1 基准 */
  height: number;
  /** 模块标题占用垂直空间（含上下 margin；basic_info 无标题为 0） */
  titleHeight: number;
  /** 条目级高度（列表模块按 data-resume-item-index 排列；平铺模块为空数组） */
  items: ItemMetric[];
}

/** 单个条目（如一条工作经历）的测量结果 */
export interface ItemMetric {
  /** 全局稳定下标（data-resume-item-index，sliceRows 保留原始下标） */
  index: number;
  /** 条目占用垂直空间（offsetHeight + 上下 margin），scale=1 基准 */
  height: number;
}

/**
 * 元素占用的垂直空间 = offsetHeight + 上下 margin。
 * section 之间靠 `margin-bottom: var(--section-spacing)` 拉开间距，
 * 漏算 margin 会导致每页少算 N × spacing，累积后分页明显偏下。
 */
function outerHeight(el: HTMLElement): number {
  const cs = getComputedStyle(el);
  const mt = parseFloat(cs.marginTop) || 0;
  const mb = parseFloat(cs.marginBottom) || 0;
  return el.offsetHeight + mt + mb;
}

export interface UsePaginationOptions {
  /** 内容签名：变化时重新测量 */
  contentKey: string;
}

export interface UsePaginationResult {
  /** 挂到隐藏测量层容器上 */
  measureRef: React.RefObject<HTMLDivElement | null>;
  /** 各 section 高度（按文档顺序） */
  metrics: SectionMetric[];
  /** 全部内容总高度 */
  totalHeight: number;
  /** 是否已完成首次测量 */
  measured: boolean;
}

export function usePagination({ contentKey }: UsePaginationOptions): UsePaginationResult {
  const measureRef = useRef<HTMLDivElement>(null);
  const [metrics, setMetrics] = useState<SectionMetric[]>([]);
  const [measured, setMeasured] = useState(false);

  const measure = useCallback(() => {
    const root = measureRef.current;
    if (!root) return;

    const nodes = Array.from(root.querySelectorAll<HTMLElement>("[data-resume-section-id]"));
    const next: SectionMetric[] = nodes.map((node) => {
      // 条目级高度：data-resume-item-index 是全局稳定下标（跨页 sliceRows 保留）
      const items = Array.from(
        node.querySelectorAll<HTMLElement>("[data-resume-item-index]"),
      )
        .map((el) => ({
          index: Number(el.dataset.resumeItemIndex) || 0,
          height: outerHeight(el),
        }))
        .sort((a, b) => a.index - b.index);
      // 标题高度：basic_info 无标题（SectionWrapper 不渲染 h2），titleHeight 为 0
      const titleEl = node.querySelector<HTMLElement>(".module-title");
      const titleHeight = titleEl ? outerHeight(titleEl) : 0;
      return {
        id: node.dataset.resumeSectionId ?? "",
        height: outerHeight(node),
        titleHeight,
        items,
      };
    });

    setMetrics((prev) => {
      const same =
        prev.length === next.length &&
        prev.every(
          (p, i) =>
            p.id === next[i].id &&
            Math.abs(p.height - next[i].height) < 0.5 &&
            Math.abs(p.titleHeight - next[i].titleHeight) < 0.5 &&
            p.items.length === next[i].items.length &&
            p.items.every(
              (it, j) =>
                it.index === next[i].items[j].index &&
                Math.abs(it.height - next[i].items[j].height) < 0.5,
            ),
        );
      return same ? prev : next;
    });
    setMeasured(true);
  }, []);

  useEffect(() => {
    const root = measureRef.current;
    if (!root) return;

    let raf = 0;
    const schedule = () => {
      cancelAnimationFrame(raf);
      // 双 rAF：等本轮样式应用完成后再测，避免读到中间态
      raf = requestAnimationFrame(() => requestAnimationFrame(measure));
    };

    schedule();
    const ro = new ResizeObserver(schedule);
    ro.observe(root);
    const mo = new MutationObserver(schedule);
    mo.observe(root, { childList: true, subtree: true, characterData: true });

    // 字体加载完成会改变文本高度，必须重测
    void document.fonts?.ready.then(schedule);

    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      mo.disconnect();
    };
  }, [measure, contentKey]);

  const totalHeight = metrics.reduce((sum, m) => sum + m.height, 0);

  return { measureRef, metrics, totalHeight, measured };
}

// ── 纯函数：装箱 & 缩放计算 ────────────────────────────────────

/**
 * 按容量把 section 装箱到多页。
 *
 * 规则：
 * - section 整体不跨页（避免标题与内容被硬切分离）
 * - 单个 section 本身超过一页容量时独占一页（允许其内部溢出，由浏览器软换行处理）
 *
 * @param capacity 单页可容纳的内容高度（scale=1 基准）
 */
export function packPages(metrics: SectionMetric[], capacity: number): string[][] {
  if (metrics.length === 0) return [];
  const cap = Math.max(capacity, 50);

  const pages: string[][] = [];
  let current: string[] = [];
  let currentH = 0;

  for (const { id, height } of metrics) {
    if (height > cap) {
      if (current.length > 0) {
        pages.push(current);
        current = [];
        currentH = 0;
      }
      pages.push([id]);
      continue;
    }
    if (currentH + height > cap && current.length > 0) {
      pages.push(current);
      current = [id];
      currentH = height;
    } else {
      current.push(id);
      currentH += height;
    }
  }
  if (current.length > 0) pages.push(current);
  return pages;
}

/**
 * 单页渲染的最小单元：一个 section 的整块，或列表 section 的一段条目。
 * 分页时把 modules 拆成 slices 列表，每页只渲染属于自己的 slices。
 */
export interface ItemRange {
  start: number;
  end: number;
}

export interface PageSlice {
  /** section id（module_type） */
  moduleType: string;
  /** 该页渲染的条目区间（列表模块；平铺模块不传 = 整块） */
  itemRange?: ItemRange;
  /** 是否显示模块标题（续页不显示标题，标题只跟第一条） */
  showTitle: boolean;
}

/**
 * 条目级流式装箱（借鉴 reactive-resume 的流式分页：条目可跨页，每页尽量填满）。
 *
 * 与 packPages（section 整体装箱）的区别：
 * - 列表 section 按条目拆分：标题 + 第一条绑定同页，其余条目流入后续页
 * - 超长 section 不再独占一页被裁，而是条目均匀分布到连续页
 * - 每页按条目高度尽量填满，避免"上一页尾部大片空白"
 * - 平铺模块（basic_info/interests 等无条目）仍整体一块不拆
 */
export function packByItems(metrics: SectionMetric[], capacity: number): PageSlice[][] {
  const pages: PageSlice[][] = [];
  let cur: PageSlice[] = [];
  let curH = 0;

  const flush = () => {
    if (cur.length > 0) {
      pages.push(cur);
      cur = [];
      curH = 0;
    }
  };

  for (const sec of metrics) {
    if (sec.items.length === 0) {
      // 平铺模块：整体块，不拆（sec.height 已含模块 padding）
      if (curH + sec.height > capacity && cur.length > 0) flush();
      cur.push({ moduleType: sec.id, showTitle: true });
      curH += sec.height;
      continue;
    }

    // 列表模块：标题 + 第一条同页，其余条目流式续排
    const items = sec.items;
    // 模块固定开销（padding/间距等非标题非条目空间）：
    // sec.height 含标题 + 全部条目 + pad，反推 pad，每页该模块出现都要计一次
    const itemSum = items.reduce((s, it) => s + it.height, 0);
    const pad = Math.max(0, sec.height - sec.titleHeight - itemSum);
    // 首条所在页：pad + 标题 + 第一条
    const firstH = pad + sec.titleHeight + items[0].height;
    if (curH + firstH > capacity && cur.length > 0) flush();
    cur.push({
      moduleType: sec.id,
      itemRange: { start: items[0].index, end: items[0].index + 1 },
      showTitle: true,
    });
    curH += firstH;

    for (let i = 1; i < items.length; i++) {
      const h = items[i].height;
      // 放同页只计 item（pad 已计入该模块在本页的首个 slice）；
      // 放不下则翻页，翻页首条额外计 pad（新一页的模块 padding）
      if (curH + h > capacity && cur.length > 0) {
        flush();
        cur.push({
          moduleType: sec.id,
          itemRange: { start: items[i].index, end: items[i].index + 1 },
          showTitle: false,
        });
        curH = pad + h;
        continue;
      }
      // 同 section 连续条目并入当前 slice（扩展 itemRange）
      const last = cur[cur.length - 1];
      if (last.moduleType === sec.id && last.itemRange && last.itemRange.end === items[i].index) {
        last.itemRange.end = items[i].index + 1;
        curH += h;
      } else {
        cur.push({
          moduleType: sec.id,
          itemRange: { start: items[i].index, end: items[i].index + 1 },
          showTitle: false,
        });
        curH += h;
      }
    }
  }
  flush();
  return pages;
}

/**
 * 自动压缩缩放系数。
 *
 * 与 magic-resume 的差异：
 * - 支持压到任意目标页数（不只是 1 页）
 * - 下限放宽到 0.75（magic-resume 的 0.9 过于保守，内容稍多就判 cannotFit）
 */
export const MIN_SCALE = 0.75;

export interface FitResult {
  scaleFactor: number;
  isScaled: boolean;
  cannotFit: boolean;
}

export function computeFitScale({
  totalHeight,
  availableHeight,
  targetPages = 1,
}: {
  totalHeight: number;
  availableHeight: number;
  targetPages?: number;
}): FitResult {
  const capacity = availableHeight * Math.max(targetPages, 1);
  if (totalHeight <= 0 || totalHeight <= capacity) {
    return { scaleFactor: 1, isScaled: false, cannotFit: false };
  }
  const ideal = capacity / totalHeight;
  if (ideal >= MIN_SCALE) return { scaleFactor: ideal, isScaled: true, cannotFit: false };
  return { scaleFactor: MIN_SCALE, isScaled: true, cannotFit: true };
}
