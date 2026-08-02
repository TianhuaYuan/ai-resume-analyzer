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

/** 专业双栏模板缩略图：深色侧栏 + 主内容区 */
function ProfessionalThumbnail({ className = "" }: ThumbnailProps) {
  return (
    <svg
      viewBox="0 0 120 160"
      className={className}
      role="img"
      aria-label="专业双栏模板预览"
    >
      {/* 背景 */}
      <rect width="120" height="160" fill="#ffffff" />
      {/* 深色侧栏 */}
      <rect width="42" height="160" fill="#1a202c" />
      {/* 侧栏：姓名 + 分段条 */}
      <rect x="8" y="14" width="26" height="5" fill="#ffffff" rx="0.5" />
      <rect x="8" y="22" width="18" height="2.5" fill="#60a5fa" rx="0.5" />
      <rect x="8" y="34" width="26" height="1" fill="#4a5568" />
      <rect x="8" y="40" width="20" height="2.5" fill="#cbd5e0" rx="0.5" />
      <rect x="8" y="45" width="22" height="2.5" fill="#cbd5e0" rx="0.5" />
      <rect x="8" y="52" width="18" height="2.5" fill="#cbd5e0" rx="0.5" />
      <rect x="8" y="64" width="26" height="1" fill="#4a5568" />
      <rect x="8" y="70" width="14" height="2.5" fill="#94a3b8" rx="0.5" />
      <rect x="8" y="75" width="18" height="2.5" fill="#94a3b8" rx="0.5" />
      {/* 主内容区 */}
      <rect x="52" y="12" width="60" height="1" fill="#2563eb" />
      <rect x="52" y="16" width="30" height="5" fill="#1a202c" rx="0.5" />
      <rect x="52" y="24" width="46" height="2.5" fill="#555" rx="0.5" />
      <rect x="52" y="29" width="40" height="2.5" fill="#555" rx="0.5" />
      <rect x="52" y="38" width="60" height="1" fill="#2563eb" opacity="0.4" />
      <rect x="52" y="42" width="18" height="5" fill="#2563eb" rx="0.5" />
      <rect x="52" y="51" width="1.5" height="14" fill="#e0e0e0" />
      <rect x="56" y="51" width="40" height="3" fill="#1a1a1a" rx="0.5" />
      <rect x="56" y="57" width="44" height="2.5" fill="#555" rx="0.5" />
      <rect x="52" y="70" width="60" height="1" fill="#2563eb" opacity="0.4" />
      <rect x="52" y="74" width="18" height="5" fill="#2563eb" rx="0.5" />
      <rect x="52" y="83" width="1.5" height="14" fill="#e0e0e0" />
      <rect x="56" y="83" width="34" height="3" fill="#1a1a1a" rx="0.5" />
      <rect x="56" y="89" width="40" height="2.5" fill="#555" rx="0.5" />
    </svg>
  );
}

/** 简约优雅：居中姓名 + 细线分隔 */
function ElegantThumbnail({ className = "" }: ThumbnailProps) {
  return (
    <svg viewBox="0 0 120 160" className={className} role="img" aria-label="简约优雅模板预览">
      <rect width="120" height="160" fill="#ffffff" />
      <rect x="40" y="14" width="40" height="6" fill="#27272a" rx="1" />
      <rect x="48" y="24" width="24" height="3" fill="#a1a1aa" rx="1" />
      <rect x="20" y="36" width="80" height="1" fill="#d4d4d8" />
      <rect x="20" y="44" width="22" height="4" fill="#27272a" rx="1" />
      <rect x="20" y="52" width="1.5" height="12" fill="#e4e4e7" />
      <rect x="24" y="52" width="50" height="3" fill="#3f3f46" rx="1" />
      <rect x="24" y="58" width="60" height="2.5" fill="#a1a1aa" rx="1" />
      <rect x="20" y="72" width="22" height="4" fill="#27272a" rx="1" />
      <rect x="20" y="80" width="1.5" height="12" fill="#e4e4e7" />
      <rect x="24" y="80" width="44" height="3" fill="#3f3f46" rx="1" />
      <rect x="24" y="86" width="56" height="2.5" fill="#a1a1aa" rx="1" />
      <rect x="20" y="100" width="22" height="4" fill="#27272a" rx="1" />
      <rect x="20" y="108" width="1.5" height="12" fill="#e4e4e7" />
      <rect x="24" y="108" width="48" height="3" fill="#3f3f46" rx="1" />
      <rect x="24" y="114" width="52" height="2.5" fill="#a1a1aa" rx="1" />
    </svg>
  );
}

/** 稳重大气：深色头带 + 结构化 */
function SteadyThumbnail({ className = "" }: ThumbnailProps) {
  return (
    <svg viewBox="0 0 120 160" className={className} role="img" aria-label="稳重大气模板预览">
      <rect width="120" height="160" fill="#ffffff" />
      <rect width="120" height="34" fill="#1c2333" />
      <rect x="16" y="10" width="42" height="5" fill="#ffffff" rx="1" />
      <rect x="16" y="18" width="28" height="3" fill="#60a5fa" rx="1" />
      <rect x="16" y="25" width="70" height="2" fill="#cbd5e1" rx="1" />
      <rect x="16" y="44" width="3" height="14" fill="#2563eb" />
      <rect x="24" y="44" width="24" height="4" fill="#1c2333" rx="1" />
      <rect x="24" y="51" width="56" height="2.5" fill="#9ca3af" rx="1" />
      <rect x="24" y="56" width="48" height="2.5" fill="#cbd5e1" rx="1" />
      <rect x="16" y="66" width="3" height="14" fill="#2563eb" />
      <rect x="24" y="66" width="30" height="4" fill="#1c2333" rx="1" />
      <rect x="24" y="73" width="60" height="2.5" fill="#9ca3af" rx="1" />
      <rect x="24" y="78" width="52" height="2.5" fill="#cbd5e1" rx="1" />
      <rect x="16" y="88" width="3" height="14" fill="#2563eb" />
      <rect x="24" y="88" width="22" height="4" fill="#1c2333" rx="1" />
      <rect x="16" y="110" width="20" height="5" fill="#1c2333" rx="1" />
      <rect x="16" y="118" width="46" height="2.5" fill="#4b5563" rx="1" />
      <rect x="16" y="123" width="38" height="2.5" fill="#4b5563" rx="1" />
    </svg>
  );
}

/** 活泼明朗：渐变头带 + 圆角卡片 */
function VibrantThumbnail({ className = "" }: ThumbnailProps) {
  return (
    <svg viewBox="0 0 120 160" className={className} role="img" aria-label="活泼明朗模板预览">
      <rect width="120" height="160" fill="#f8fafc" />
      <rect x="0" y="0" width="120" height="32" fill="#6366f1" rx="0" />
      <rect x="0" y="24" width="120" height="8" fill="#7c3aed" rx="0" />
      <rect x="16" y="8" width="40" height="5" fill="#ffffff" rx="1" />
      <rect x="16" y="16" width="56" height="2.5" fill="#e0e7ff" rx="1" />
      <rect x="16" y="42" width="88" height="26" fill="#ffffff" rx="4" stroke="#e5e7eb" />
      <rect x="22" y="48" width="24" height="4" fill="#6366f1" rx="1" />
      <rect x="22" y="56" width="60" height="2.5" fill="#cbd5e1" rx="1" />
      <rect x="22" y="61" width="52" height="2.5" fill="#e2e8f0" rx="1" />
      <rect x="16" y="76" width="88" height="26" fill="#ffffff" rx="4" stroke="#e5e7eb" />
      <rect x="22" y="82" width="24" height="4" fill="#6366f1" rx="1" />
      <rect x="22" y="90" width="56" height="2.5" fill="#cbd5e1" rx="1" />
      <rect x="22" y="95" width="48" height="2.5" fill="#e2e8f0" rx="1" />
      <rect x="16" y="110" width="88" height="26" fill="#ffffff" rx="4" stroke="#e5e7eb" />
      <rect x="22" y="116" width="24" height="4" fill="#6366f1" rx="1" />
      <rect x="22" y="124" width="40" height="2.5" fill="#cbd5e1" rx="1" />
    </svg>
  );
}

/** 模板 ID → 缩略图组件映射 */
export const TEMPLATE_THUMBNAILS: Record<string, (props: ThumbnailProps) => React.JSX.Element> = {
  default: DefaultThumbnail,
  minimal: MinimalThumbnail,
  business: BusinessThumbnail,
  professional: ProfessionalThumbnail,
  elegant: ElegantThumbnail,
  steady: SteadyThumbnail,
  vibrant: VibrantThumbnail,
};
