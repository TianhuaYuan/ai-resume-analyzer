import type { Variants } from "framer-motion";

/**
 * useModalMotion — 全站统一弹窗动效 token。
 *
 * 对齐 Open WebUI 的「统一过渡」思路，但保留 Apple 弹簧质感：
 * - 面板入场：弹簧（stiffness 420 / damping 32）微上移 + 缩放入场
 * - 遮罩：fade 200ms
 * - 退场：快速淡出缩拢（150ms），不拖泥带水
 *
 * motion-reduce 场景由 framer-motion 的 useReducedMotion 在 Modal 内部兜底，
 * 此处只产出 variants 供消费方复用。
 */
export const overlayVariants: Variants = {
  hidden: { opacity: 0 },
  visible: { opacity: 1, transition: { duration: 0.2, ease: "easeOut" } },
  exit: { opacity: 0, transition: { duration: 0.15, ease: "easeOut" } },
};

export const panelVariants: Variants = {
  hidden: { opacity: 0, scale: 0.95, y: 14 },
  visible: {
    opacity: 1,
    scale: 1,
    y: 0,
    transition: { type: "spring", stiffness: 420, damping: 32, mass: 0.9 },
  },
  exit: {
    opacity: 0,
    scale: 0.96,
    y: 10,
    transition: { duration: 0.15, ease: "easeOut" },
  },
};

/** 统一弹窗动效 hook：返回遮罩与面板 variants，供 Modal 及各 Dialog 复用 */
export function useModalMotion() {
  return { overlayVariants, panelVariants };
}
