/**
 * 计算会话预警状态。
 *
 * 抽成纯函数便于 TDD 测试，避免和 React 组件 / 定时器耦合。
 *
 * @param expMs token 过期时间戳（毫秒）
 * @param nowMs 当前时间戳（毫秒）
 * @param warningBeforeSeconds 预警提前秒数
 */
export type SessionWarningResult =
  | { kind: "expired" }
  | { kind: "warning"; remainingSeconds: number }
  | { kind: "schedule"; delayMs: number };

export function computeSessionWarning(
  expMs: number,
  nowMs: number,
  warningBeforeSeconds: number
): SessionWarningResult {
  const warningBeforeMs = warningBeforeSeconds * 1000;
  const warningAt = expMs - warningBeforeMs;

  if (nowMs >= expMs) {
    return { kind: "expired" };
  }
  if (nowMs >= warningAt) {
    const remainingSeconds = Math.ceil((expMs - nowMs) / 1000);
    return { kind: "warning", remainingSeconds };
  }
  return { kind: "schedule", delayMs: warningAt - nowMs };
}
