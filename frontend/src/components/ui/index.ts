/**
 * ui/ — 全站基础组件库统一出口。
 *
 * 组件库分层（P0）：通用基础组件（Button/Spinner/Badge/Tooltip/Modal）
 * 从 components/ 根目录沉淀到 ui/ 子目录，供各域目录（chat、builder、resume…）复用。
 * 命名约定：基础组件默认导出，具名导出类型（ButtonVariant 等）。
 */
export { default as Button } from "./Button";
export type { ButtonVariant, ButtonSize } from "./Button";
export { default as Spinner } from "./Spinner";
export { default as Badge } from "./Badge";
export type { BadgeVariant } from "./Badge";
export { default as Tooltip } from "./Tooltip";
export type { TooltipSide } from "./Tooltip";
export { default as Modal } from "./Modal";
export type { ModalSize } from "./Modal";
