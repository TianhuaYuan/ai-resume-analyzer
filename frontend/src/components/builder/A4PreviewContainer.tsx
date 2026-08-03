/**
 * A4PreviewContainer — A4 缩略图容器（卡片场景专用）。
 *
 * 用于简历列表页卡片、模板画廊缩略图：按父容器宽度等比缩放一整页 A4，
 * 超出首页的内容裁掉（缩略图只需展示首页）。
 *
 * 编辑页的多页预览不走这里 —— 见 PaginatedResumePreview（真实多页装箱）。
 *
 * 用法：
 *   <A4PreviewContainer className="absolute inset-0">
 *     <ResumeTemplateView modules={...} style={...} />
 *   </A4PreviewContainer>
 *
 *   // iframe 兜底（后端 preview_html）
 *   <A4PreviewContainer>
 *     <iframe srcDoc={html} className="w-full h-full border-0" />
 *   </A4PreviewContainer>
 */

import { useEffect, useRef, useState, type ReactNode } from "react";

/** A4 尺寸：210mm × 297mm @ 96dpi（96 / 25.4 = 3.779528） */
export const A4_BASE_WIDTH = 210 * (96 / 25.4); // 793.70
export const A4_BASE_HEIGHT = 297 * (96 / 25.4); // 1122.52

export interface A4PreviewContainerProps {
  children: ReactNode;
  className?: string;
  /** 固定缩放比例（可选）。默认按容器宽度自动等比缩放 */
  scale?: number;
  /** 外层容器 id */
  id?: string;
}

export function A4PreviewContainer({
  children,
  className = "",
  scale: fixedScale,
  id,
}: A4PreviewContainerProps) {
  const ref = useRef<HTMLDivElement>(null);
  const [autoScale, setAutoScale] = useState(1);

  useEffect(() => {
    if (fixedScale !== undefined) return;
    const el = ref.current;
    if (!el) return;
    const update = () => {
      if (el.clientWidth > 0) setAutoScale(el.clientWidth / A4_BASE_WIDTH);
    };
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, [fixedScale]);

  const scale = fixedScale ?? autoScale;

  return (
    <div
      ref={ref}
      id={id}
      className={`relative w-full bg-white overflow-hidden ${className}`}
      style={{ aspectRatio: "210 / 297" }}
    >
      <div
        className="a4-preview-scale-wrapper absolute top-0 left-0 origin-top-left overflow-hidden"
        style={{
          width: A4_BASE_WIDTH,
          height: A4_BASE_HEIGHT,
          transform: `scale(${scale})`,
        }}
      >
        {children}
      </div>
    </div>
  );
}

export default A4PreviewContainer;
