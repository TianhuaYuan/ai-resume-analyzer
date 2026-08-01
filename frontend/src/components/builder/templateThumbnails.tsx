/**
 * Task 10: 模板预览缩略图 — 3 套模板的 SVG 内联缩略图。
 *
 * 每个缩略图以 SVG 简化呈现模板的视觉风格概览：
 * - default: 经典风格，左侧色条标题
 * - minimal: 极简风格，大留白 + 上划线标题
 * - business: 商务风格，顶部色块头部
 *
 * 内联 SVG，不增加网络请求。
 */

interface ThumbnailProps {
  className?: string;
}

/** 经典模板缩略图 */
function DefaultThumbnail({ className = "" }: ThumbnailProps) {
  return (
    <svg
      viewBox="0 0 120 160"
      className={className}
      role="img"
      aria-label="经典模板预览"
    >
      <rect width="120" height="160" fill="#ffffff" />
      {/* 姓名 */}
      <rect x="12" y="10" width="50" height="7" fill="#1a1a1a" rx="1" />
      <rect x="12" y="20" width="70" height="3" fill="#999" rx="1" />
      {/* 分隔线 */}
      <rect x="12" y="30" width="96" height="0.5" fill="#eee" />
      {/* Section 1: 左色条 + 标题 */}
      <rect x="12" y="38" width="3" height="8" fill="#2563eb" />
      <rect x="18" y="39" width="35" height="6" fill="#1a1a1a" rx="1" />
      <rect x="18" y="50" width="80" height="3" fill="#555" rx="0.5" />
      <rect x="18" y="56" width="65" height="3" fill="#555" rx="0.5" />
      <rect x="18" y="62" width="72" height="3" fill="#555" rx="0.5" />
      {/* Section 2 */}
      <rect x="12" y="74" width="3" height="8" fill="#2563eb" />
      <rect x="18" y="75" width="40" height="6" fill="#1a1a1a" rx="1" />
      <rect x="18" y="86" width="80" height="3" fill="#555" rx="0.5" />
      <rect x="18" y="92" width="55" height="3" fill="#555" rx="0.5" />
      {/* Section 3 */}
      <rect x="12" y="104" width="3" height="8" fill="#2563eb" />
      <rect x="18" y="105" width="30" height="6" fill="#1a1a1a" rx="1" />
      <rect x="18" y="116" width="80" height="3" fill="#555" rx="0.5" />
      <rect x="18" y="122" width="70" height="3" fill="#555" rx="0.5" />
      <rect x="18" y="128" width="60" height="3" fill="#555" rx="0.5" />
      {/* Section 4 */}
      <rect x="12" y="140" width="3" height="8" fill="#2563eb" />
      <rect x="18" y="141" width="25" height="6" fill="#1a1a1a" rx="1" />
      <rect x="18" y="152" width="50" height="3" fill="#555" rx="0.5" />
    </svg>
  );
}

/** 极简模板缩略图 */
function MinimalThumbnail({ className = "" }: ThumbnailProps) {
  return (
    <svg
      viewBox="0 0 120 160"
      className={className}
      role="img"
      aria-label="极简模板预览"
    >
      <rect width="120" height="160" fill="#ffffff" />
      {/* 姓名 — 大字，轻字重 */}
      <rect x="14" y="14" width="55" height="8" fill="#111" rx="1" />
      <rect x="14" y="26" width="65" height="2.5" fill="#aaa" rx="0.5" />
      {/* Section 1: 上划线标题 */}
      <rect x="14" y="42" width="92" height="0.5" fill="#ddd" />
      <rect x="14" y="46" width="30" height="4" fill="#222" rx="0.5" />
      <rect x="14" y="56" width="80" height="2.5" fill="#666" rx="0.5" />
      <rect x="14" y="62" width="65" height="2.5" fill="#666" rx="0.5" />
      <rect x="14" y="68" width="72" height="2.5" fill="#666" rx="0.5" />
      {/* Section 2 */}
      <rect x="14" y="82" width="92" height="0.5" fill="#ddd" />
      <rect x="14" y="86" width="35" height="4" fill="#222" rx="0.5" />
      <rect x="14" y="96" width="80" height="2.5" fill="#666" rx="0.5" />
      <rect x="14" y="102" width="60" height="2.5" fill="#666" rx="0.5" />
      {/* Section 3 */}
      <rect x="14" y="116" width="92" height="0.5" fill="#ddd" />
      <rect x="14" y="120" width="28" height="4" fill="#222" rx="0.5" />
      <rect x="14" y="130" width="75" height="2.5" fill="#666" rx="0.5" />
      <rect x="14" y="136" width="55" height="2.5" fill="#666" rx="0.5" />
      <rect x="14" y="142" width="68" height="2.5" fill="#666" rx="0.5" />
    </svg>
  );
}

/** 商务模板缩略图 */
function BusinessThumbnail({ className = "" }: ThumbnailProps) {
  return (
    <svg
      viewBox="0 0 120 160"
      className={className}
      role="img"
      aria-label="商务模板预览"
    >
      <rect width="120" height="160" fill="#ffffff" />
      {/* 顶部色块头部 */}
      <rect x="0" y="0" width="120" height="32" fill="#2563eb" />
      <rect x="12" y="8" width="50" height="7" fill="#fff" rx="1" />
      <rect x="12" y="19" width="70" height="2.5" fill="rgba(255,255,255,0.8)" rx="0.5" />
      <rect x="12" y="24" width="40" height="2.5" fill="rgba(255,255,255,0.8)" rx="0.5" />
      {/* Section 1: 下划线标题 */}
      <rect x="12" y="44" width="92" height="1" fill="#2563eb" />
      <rect x="12" y="48" width="30" height="5" fill="#2563eb" rx="0.5" />
      {/* 左边竖线条目 */}
      <rect x="14" y="58" width="1.5" height="14" fill="#e0e0e0" />
      <rect x="18" y="58" width="60" height="3" fill="#1a1a1a" rx="0.5" />
      <rect x="18" y="64" width="80" height="2.5" fill="#555" rx="0.5" />
      <rect x="18" y="69" width="65" height="2.5" fill="#555" rx="0.5" />
      {/* Section 2 */}
      <rect x="12" y="82" width="92" height="1" fill="#2563eb" />
      <rect x="12" y="86" width="35" height="5" fill="#2563eb" rx="0.5" />
      <rect x="14" y="96" width="1.5" height="14" fill="#e0e0e0" />
      <rect x="18" y="96" width="55" height="3" fill="#1a1a1a" rx="0.5" />
      <rect x="18" y="102" width="80" height="2.5" fill="#555" rx="0.5" />
      <rect x="18" y="107" width="70" height="2.5" fill="#555" rx="0.5" />
      {/* Section 3 */}
      <rect x="12" y="120" width="92" height="1" fill="#2563eb" />
      <rect x="12" y="124" width="25" height="5" fill="#2563eb" rx="0.5" />
      <rect x="14" y="134" width="1.5" height="14" fill="#e0e0e0" />
      <rect x="18" y="134" width="50" height="3" fill="#1a1a1a" rx="0.5" />
      <rect x="18" y="140" width="75" height="2.5" fill="#555" rx="0.5" />
      <rect x="18" y="145" width="60" height="2.5" fill="#555" rx="0.5" />
    </svg>
  );
}

/** 模板 ID → 缩略图组件映射 */
export const TEMPLATE_THUMBNAILS: Record<string, (props: ThumbnailProps) => React.JSX.Element> = {
  default: DefaultThumbnail,
  minimal: MinimalThumbnail,
  business: BusinessThumbnail,
};
